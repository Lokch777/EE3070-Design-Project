"""
OmniCoordinator — Phase 1 (Audio-Only)
========================================
Replaces AppCoordinator when OMNI_MODE=true.
Same interface so main.py can swap coordinators with minimal changes.

Responsibilities:
  1. Forward ESP32 MIC audio → OmniStreamAdapter.send_audio()
  2. Receive Omni audio deltas → resample 24→16kHz → stream to ESP32
  3. Handle barge-in → send stop_playback to ESP32
  4. Publish events to EventBus for dashboard UI
  5. Session lifecycle (auto-refresh at 110 min)

Phase 2 will add: handle_camera_frame() for continuous image stream.
"""

import asyncio
import base64
import logging
import time
from typing import Dict, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from backend.event_bus import EventBus
from backend.models import Event, EventType
from backend.config import Settings
from backend.omni_stream_adapter import (
    OmniStreamAdapter,
    OmniConfig,
    OmniSessionState,
    MAX_ESP32_WS_FRAME_PCM,
    ESP32_SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


class OmniCoordinator:
    """
    Drop-in replacement for AppCoordinator in Omni mode.
    Exposes the same public methods so main.py WebSocket handlers
    can work without code changes.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # EventBus for dashboard UI
        self.event_bus = EventBus(buffer_size=settings.event_buffer_size)

        # ── OmniStreamAdapter ──────────────────────────────────
        omni_config = OmniConfig(
            api_key=settings.asr_api_key,   # Same Dashscope key
            model=getattr(settings, 'omni_model', 'qwen3.5-omni-plus-realtime'),
            region="intl",
            voice=getattr(settings, 'omni_voice', 'Cherry'),
            instructions=getattr(
                settings, 'omni_instructions',
                '你是一個配戴在眼鏡上的智能助手。用繁體中文回答，語句簡短自然。'
            ),
            enable_search=getattr(settings, 'omni_enable_search', False),
            enable_transcription=getattr(settings, 'omni_enable_transcription', True),
            vad_enabled=True,
            vad_threshold=getattr(settings, 'omni_vad_threshold', 0.5),
            vad_silence_ms=getattr(settings, 'omni_vad_silence_ms', 800),
            session_timeout_min=getattr(settings, 'omni_session_refresh_min', 110),
        )
        self.omni = OmniStreamAdapter(omni_config, self.event_bus)

        # Wire Omni callbacks
        self.omni.on_audio_delta = self._on_omni_audio
        self.omni.on_text_delta = self._on_omni_text
        self.omni.on_response_done = self._on_response_done
        self.omni.on_user_transcript = self._on_user_transcript
        self.omni.on_speech_started = self._on_speech_started
        self.omni.on_speech_stopped = self._on_speech_stopped
        self.omni.on_barge_in = self._on_barge_in

        # ── Device connections (mirrors AppCoordinator's pattern) ──
        self._device_connections: Dict[str, WebSocket] = {}
        self._current_device_id: str = "default"

        # ── Audio queue (same pattern as AppCoordinator) ──────
        self._audio_chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=24)
        self._audio_forward_task: Optional[asyncio.Task] = None
        self._session_refresh_task: Optional[asyncio.Task] = None
        self._audio_ingest_stats: Dict[str, dict] = {}

        # ── Text accumulator for current response ─────────────
        self._response_text: str = ""
        self._response_id: str = ""

        self.running = False
        
        # ── Phase 2: Camera Stream Configuration ──────
        self.last_frame_time = 0
        self.frame_interval = 1.0  # 強制 1 FPS 限流
        
        logger.info("OmniCoordinator initialized (Phase 2: Audio + Continuous Vision)")
    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self):
        """Connect to Omni and start background tasks."""
        self.running = True
        logger.info("Starting OmniCoordinator...")

        connected = await self.omni.connect()
        if not connected:
            logger.error(
                "Failed to connect Omni — fallback to batch mode required. "
                "Set OMNI_MODE=false and restart."
            )
            return

        # Audio forwarding consumer
        self._audio_forward_task = asyncio.create_task(self._forward_audio_loop())

        # Session auto-refresh
        refresh_min = getattr(self.settings, 'omni_session_refresh_min', 110)
        self._session_refresh_task = asyncio.create_task(
            self._session_refresh_loop(refresh_min)
        )

        logger.info("OmniCoordinator started — Omni session active")

    async def stop(self):
        """Gracefully disconnect."""
        self.running = False
        logger.info("Stopping OmniCoordinator...")

        if self._audio_forward_task:
            self._audio_forward_task.cancel()
            try:
                await self._audio_forward_task
            except asyncio.CancelledError:
                pass

        if self._session_refresh_task:
            self._session_refresh_task.cancel()
            try:
                await self._session_refresh_task
            except asyncio.CancelledError:
                pass

        await self.omni.disconnect()
        logger.info("OmniCoordinator stopped")

    # ── Audio from ESP32 (same interface as AppCoordinator) ───

    async def handle_audio_chunk(self, audio_chunk: bytes, device_id: str = "default") -> None:
        """Queue raw PCM from ESP32 MIC for forwarding to Omni."""
        if not audio_chunk:
            return

        self._current_device_id = device_id

        try:
            self._audio_chunk_queue.put_nowait((device_id, audio_chunk))
        except asyncio.QueueFull:
            logger.warning(
                "Omni audio queue full for %s (qsize=%s); dropping chunk",
                device_id, self._audio_chunk_queue.qsize()
            )

    async def _forward_audio_loop(self):
        """Single consumer: dequeue and send to Omni."""
        while self.running:
            try:
                device_id, chunk = await self._audio_chunk_queue.get()
            except asyncio.CancelledError:
                return

            try:
                await self.omni.send_audio(chunk)
            except Exception as e:
                logger.error("Failed to forward audio to Omni: %s", e)
            finally:
                self._audio_chunk_queue.task_done()



    # ── Camera from ESP32 (Phase 2) ───────────────────────────

    async def handle_camera_frame(self, jpeg_bytes: bytes, device_id: str = "default") -> None:
        """Receive continuous JPEG stream from ESP32 and forward to Omni."""
        now = time.time()

        # 1. Server-side Rate Limiting (確保每秒最多 1 張)
        if (now - self.last_frame_time) < self.frame_interval:
            return

        # 2. File Size Safety Check (DashScope API 限制 < 500KB)
        if len(jpeg_bytes) > 500 * 1024:
            logger.warning("Image too large (%s bytes), dropping frame", len(jpeg_bytes))
            return

        self.last_frame_time = now
        
        # 如果你想在終端機看到傳送紀錄，可以保留這行 debug (平常可註解掉防洗版)
        logger.debug("Forwarding %s bytes to Omni Vision", len(jpeg_bytes))

        # 3. Forward to Omni model
        try:
            await self.omni.send_image(jpeg_bytes)
        except Exception as e:
            logger.error("Failed to forward image to Omni: %s", e)




    # ── Device registration (same interface as AppCoordinator) ─

    def register_audio_device(self, device_id: str, websocket: WebSocket) -> None:
        """Register an ESP32 audio WebSocket for playback streaming."""
        self._device_connections[device_id] = websocket
        self._current_device_id = device_id
        logger.info("OmniCoordinator: audio device registered: %s", device_id)

    def unregister_audio_device(self, device_id: str, websocket: WebSocket = None) -> None:
        """Unregister ESP32 audio device."""
        current_ws = self._device_connections.get(device_id)
        if websocket and current_ws is not websocket:
            # Stale unregister — a newer connection already replaced it
            return
        self._device_connections.pop(device_id, None)
        logger.info("OmniCoordinator: audio device unregistered: %s", device_id)

    async def on_audio_control_message(self, device_id: str, message: dict) -> None:
        """Handle control messages from ESP32 /ws_audio (playback_complete, etc.)."""
        msg_type = message.get("type")
        if msg_type == "playback_complete":
            req_id = message.get("request_id", "")
            logger.info("ESP32 playback_complete: device=%s req_id=%s", device_id, req_id)
        elif msg_type == "playback_error":
            error = message.get("reason") or message.get("error") or "unknown"
            logger.warning("ESP32 playback_error: device=%s error=%s", device_id, error)
        elif msg_type in {"playback_debug", "playback_stats"}:
            logger.debug("ESP32 playback debug: %s", message)
        else:
            logger.debug("Unknown /ws_audio control from %s: %s", device_id, message)

    # ── Omni Callbacks ────────────────────────────────────────

    def _on_omni_audio(self, pcm_16k: bytes, response_id: str):
        """Stream audio delta to ESP32 immediately."""
        asyncio.create_task(self._stream_audio_to_esp32(pcm_16k, response_id))

    async def _stream_audio_to_esp32(self, pcm_16k: bytes, response_id: str):
        """Send resampled PCM to ESP32 in ≤1024B WS frames."""
        ws = self._device_connections.get(self._current_device_id)
        if not ws:
            return

        # Check WS is still connected
        try:
            if ws.client_state != WebSocketState.CONNECTED:
                return
        except Exception:
            return

        for i in range(0, len(pcm_16k), MAX_ESP32_WS_FRAME_PCM):
            chunk = pcm_16k[i:i + MAX_ESP32_WS_FRAME_PCM]
            msg = {
                "type": "audio_chunk",
                "request_id": response_id,
                "audio_data": base64.b64encode(chunk).decode("ascii"),
                "sample_rate": ESP32_SAMPLE_RATE,
            }
            try:
                await ws.send_json(msg)
            except Exception as e:
                logger.warning("Failed to stream audio to ESP32: %s", e)
                break

    def _on_omni_text(self, text: str, response_id: str):
        """Accumulate response text and publish as vision_result for dashboard."""
        self._response_text += text
        self._response_id = response_id

        # Publish partial text as asr_partial-style event (for dashboard ASR card)
        asyncio.create_task(self.event_bus.publish(Event(
            event_type=EventType.ASR_PARTIAL.value,
            timestamp=time.time(),
            req_id=response_id,
            data={"text": self._response_text, "source": "omni_response"},
        )))

    def _on_user_transcript(self, text: str):
        """User's speech transcription from Omni."""
        logger.info("[User] %s", text)
        asyncio.create_task(self.event_bus.publish(Event(
            event_type=EventType.ASR_FINAL.value,
            timestamp=time.time(),
            data={"text": text, "source": "omni_transcript"},
        )))

    def _on_response_done(self, response_id: str):
        """Omni finished generating response."""
        # Send playback_end to ESP32
        asyncio.create_task(self._send_playback_end(response_id))

        # Publish full response as vision_result for dashboard
        if self._response_text:
            asyncio.create_task(self.event_bus.publish(Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=response_id,
                data={"text": self._response_text, "source": "omni"},
            )))

        # Publish tts_started event (for dashboard TTS progress bar)
        # NOTE: "tts_started" is not in the EventType enum — publish as raw string.
        #       Add TTS_STARTED = "tts_started" to EventType in models.py.
        asyncio.create_task(self.event_bus.publish(Event(
            event_type="tts_started",
            timestamp=time.time(),
            req_id=response_id,
            data={"text": self._response_text[:100]},
        )))

        self._response_text = ""
        self._response_id = ""

    def _on_speech_started(self):
        """Omni VAD detected user speaking."""
        logger.debug("Omni: speech_started")

    def _on_speech_stopped(self):
        """Omni VAD detected user stopped speaking."""
        logger.debug("Omni: speech_stopped")

    def _on_barge_in(self):
        """User interrupted during response — stop ESP32 playback."""
        logger.info("Barge-in detected → sending stop_playback to ESP32")
        asyncio.create_task(self._send_stop_playback())

    # ── ESP32 Commands ────────────────────────────────────────

    async def _send_stop_playback(self):
        """Tell ESP32 to immediately clear its playback buffer."""
        ws = self._device_connections.get(self._current_device_id)
        if not ws:
            return
        try:
            await ws.send_json({"type": "stop_playback"})
            logger.info("Sent stop_playback to ESP32 device=%s", self._current_device_id)
        except Exception as e:
            logger.warning("Failed to send stop_playback: %s", e)

    async def _send_playback_end(self, response_id: str):
        """Signal ESP32 that all audio for this response has been sent."""
        ws = self._device_connections.get(self._current_device_id)
        if not ws:
            return
        try:
            await ws.send_json({
                "type": "playback_end",
                "request_id": response_id,
            })
        except Exception as e:
            logger.warning("Failed to send playback_end: %s", e)

    # ── Session Refresh ───────────────────────────────────────

    async def _session_refresh_loop(self, refresh_min: int):
        """Proactively refresh Omni session before 120-min limit."""
        try:
            while self.running:
                await asyncio.sleep(refresh_min * 60)
                if not self.running:
                    break

                logger.info(
                    "Omni session approaching 120-min limit; refreshing..."
                )
                await self.omni.disconnect()
                success = await self.omni.connect()
                if success:
                    logger.info("Omni session refreshed successfully")
                else:
                    logger.error(
                        "Omni session refresh FAILED — attempting reconnect"
                    )
                    success = await self.omni.reconnect()
                    if not success:
                        logger.critical(
                            "Omni reconnect failed after session refresh. "
                            "Service degraded."
                        )
        except asyncio.CancelledError:
            pass

    # ── Stats / introspection ─────────────────────────────────

    def get_event_bus(self) -> EventBus:
        return self.event_bus

    def get_omni_stats(self) -> dict:
        """Return Omni adapter stats for /api/omni_status endpoint."""
        return self.omni.get_stats()
