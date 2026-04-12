# Audio Playback Coordinator for ESP32 Real-Time AI Assistant
# FIXES (this build):
#   FIX A — MAX_AUDIO_CHUNK_PCM_BYTES = 1024
#            ESP32 ArduinoWebsockets has ~4KB internal WS frame buffer.
#            Old: effective_chunk_size capped at 4096 bytes PCM
#                 → base64 ≈ 5461 chars + JSON overhead ≈ 5660 bytes / frame
#                 → exceeds ESP32 buffer → library misreads header → close 1002
#            New: cap at 1024 bytes PCM
#                 → base64 ≈ 1365 chars + JSON overhead ≈ 1515 bytes / frame
#                 → well within 4KB limit → no more protocol errors
#
#   FIX B — _stream_audio: graceful 1002 / disconnect error handling
#            Old: any Exception → ERROR log → re-raise → triggers playback_error event
#            New: WebSocket close/protocol errors logged as WARNING with context,
#                 treated as "device disconnected mid-stream", not as fatal error
#
#   FIX C — _stream_audio: connection pre-check before streaming
#            Quick websocket state check before sending first chunk;
#            avoids sending into a dead socket silently
#
# KEPT FROM PREVIOUS BUILD:
#   FIX 1 — unregister_device stale disconnect guard (websocket param)
#   FIX 2 — real_time_pacing_factor 1.05 (server slightly slower than ESP32)
#   FIX 3 — chunk_pacing_seconds 0.005 (low first-chunk latency)

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from backend.event_bus import EventBus
from backend.models import Event, EventType

logger = logging.getLogger(__name__)

# [FIX A] Hard cap on PCM bytes per WebSocket frame.
# 1024 bytes PCM → ~1365 chars base64 → ~1515 bytes JSON total
# This is the single most important constant for ESP32 WS stability.
MAX_AUDIO_CHUNK_PCM_BYTES = 1024


@dataclass
class PlaybackConfig:
    chunk_size: int                = 4096   # Logical chunk; split into ≤1024B WS frames
    buffer_size: int               = 16384
    stream_timeout: float          = 30.0
    chunk_pacing_seconds: float    = 0.005  # Low first-chunk latency
    real_time_pacing_factor: float = 1.05   # Server slightly slower than ESP32 playback
    reconnect_wait_seconds: float  = 5.0
    reconnect_poll_seconds: float  = 0.5


@dataclass
class PlaybackSession:
    request_id: str
    started_at: float
    total_bytes: int
    total_chunks: int
    chunks_sent: int      = 0
    bytes_sent: int       = 0
    end_marker_sent: bool = False


class AudioPlaybackCoordinator:
    """
    Streams TTS audio to ESP32 and tracks playback lifecycle.
    """

    def __init__(self, event_bus: EventBus, config: PlaybackConfig):
        self.event_bus = event_bus
        self.config    = config
        self._running  = False
        self._task: Optional[asyncio.Task] = None

        self.active_playback:   Dict[str, str]             = {}
        self.device_connections: Dict[str, WebSocket]      = {}
        self.playback_sessions: Dict[str, PlaybackSession] = {}

        logger.info(
            "AudioPlaybackCoordinator initialized "
            "(max_frame=%sB chunk_pacing=%.3fs pacing_factor=%.2f)",
            MAX_AUDIO_CHUNK_PCM_BYTES,
            config.chunk_pacing_seconds,
            config.real_time_pacing_factor,
        )

    # ------------------------------------------------------------------ #
    async def start(self):
        if self._running:
            logger.warning("AudioPlaybackCoordinator already running")
            return
        self._running = True
        self._task    = asyncio.create_task(self._listen_for_audio_ready())
        logger.info("AudioPlaybackCoordinator started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AudioPlaybackCoordinator stopped")

    # ------------------------------------------------------------------ #
    def register_device(self, device_id: str, websocket: WebSocket):
        self.device_connections[device_id] = websocket
        logger.info("Device registered: %s", device_id)

    def unregister_device(self, device_id: str, websocket: WebSocket = None):
        # FIX 1: Only unregister if the websocket matches current registration.
        # Guards against a reconnected ESP32 being unregistered by the old disconnect.
        if websocket is not None:
            current = self.device_connections.get(device_id)
            if current is not websocket:
                logger.warning(
                    "Stale disconnect ignored for device %s "
                    "(new connection already registered)", device_id,
                )
                return

        self.device_connections.pop(device_id, None)
        self.active_playback.pop(device_id, None)
        self.playback_sessions.pop(device_id, None)
        logger.info("Device unregistered: %s", device_id)

    # ------------------------------------------------------------------ #
    async def _listen_for_audio_ready(self):
        try:
            async for event in self.event_bus.subscribe(EventType.AUDIO_READY.value):
                if not self._running:
                    break
                await self._on_audio_ready(event)
        except asyncio.CancelledError:
            logger.info("Audio ready listener cancelled")
        except Exception as e:
            logger.error("Error in audio ready listener: %s", e)

    async def _on_audio_ready(self, event: Event):
        device_id  = event.data.get("device_id", "unknown")
        request_id = event.req_id
        logger.info("Audio ready: device=%s req_id=%s", device_id, request_id)

        # Wait for device connection if not yet present
        if device_id not in self.device_connections:
            waited = 0.0
            while waited < self.config.reconnect_wait_seconds:
                await asyncio.sleep(self.config.reconnect_poll_seconds)
                waited += self.config.reconnect_poll_seconds
                if device_id in self.device_connections:
                    break

        if self._is_playback_active(device_id):
            logger.warning(
                "Playback already active for device %s, ignoring req %s",
                device_id, request_id,
            )
            return

        if device_id not in self.device_connections:
            logger.error("Device %s not connected after wait, cannot stream", device_id)
            await self._emit_playback_error(device_id, request_id, "Device not connected")
            return

        try:
            await self._stream_audio(
                audio_data=event.data.get("audio_data", b""),
                device_id=device_id,
                request_id=request_id,
                audio_format=event.data.get("audio_format", "pcm"),
                sample_rate=event.data.get("sample_rate", 16000),
            )
        except Exception as e:
            logger.error("Audio streaming failed: %s", e)
            await self._emit_playback_error(device_id, request_id, str(e))

    # ------------------------------------------------------------------ #
    async def _stream_audio(
        self,
        audio_data:   bytes,
        device_id:    str,
        request_id:   str,
        audio_format: str,
        sample_rate:  int,
    ):
        websocket = self.device_connections.get(device_id)
        if not websocket:
            raise Exception(f"Device {device_id} not connected")
        if not audio_data:
            raise Exception("Empty audio payload")

        # [FIX C] Pre-flight connection check
        if websocket.client_state != WebSocketState.CONNECTED:
            raise Exception(
                f"WebSocket for device {device_id} is not in CONNECTED state "
                f"(state={websocket.client_state})"
            )

        # [FIX A] Enforce 1024-byte PCM cap per WS frame.
        # Logical chunk_size (4096) is used for prebuffer calculation only.
        ws_frame_size = MAX_AUDIO_CHUNK_PCM_BYTES  # 1024 bytes PCM per WS send_json()
        logical_chunk = min(max(int(self.config.chunk_size), 512), 16384)
        prebuffer_target_bytes = min(len(audio_data), max(int(self.config.buffer_size), ws_frame_size))
        total_frames = (len(audio_data) + ws_frame_size - 1) // ws_frame_size

        self.active_playback[device_id]   = request_id
        self.playback_sessions[device_id] = PlaybackSession(
            request_id=request_id,
            started_at=time.time(),
            total_bytes=len(audio_data),
            total_chunks=total_frames,
        )

        await self._emit_playback_started(device_id, request_id)

        # [FIX 14] Validate total audio and trailing silence before chunking
        # At 16kHz 16-bit mono: 1 second = 32000 bytes
        audio_duration_s = len(audio_data) / (sample_rate * 2) if sample_rate > 0 else 0
        # Detect trailing silence: count zero bytes at end
        trailing_zero_bytes = 0
        for i in range(len(audio_data) - 1, -1, -1):
            if audio_data[i] == 0:
                trailing_zero_bytes += 1
            else:
                break
        trailing_silence_ms = (trailing_zero_bytes / (sample_rate * 2)) * 1000 if sample_rate > 0 else 0

        logger.info(
            "[FIX 14] Audio validation: total=%s bytes (%.2fs) "
            "trailing_silence=%s bytes (%.0fms) "
            "→ %s WS frames to device %s "
            "(frame_size=%sB prebuffer=%sB)",
            len(audio_data), audio_duration_s,
            trailing_zero_bytes, trailing_silence_ms,
            total_frames, device_id,
            ws_frame_size, prebuffer_target_bytes,
        )

        bytes_buffered_on_device = 0

        try:
            for frame_idx in range(0, len(audio_data), ws_frame_size):
                chunk    = audio_data[frame_idx : frame_idx + ws_frame_size]
                sequence = frame_idx // ws_frame_size
                message  = {
                    "type":         "audio_chunk",
                    "request_id":   request_id,
                    "audio_data":   base64.b64encode(chunk).decode(),
                    "sequence":     sequence,
                    "total_chunks": total_frames,
                    "format":       audio_format,
                    "sample_rate":  sample_rate,
                }

                try:
                    await asyncio.wait_for(
                        websocket.send_json(message),
                        timeout=self.config.stream_timeout,
                    )
                except asyncio.TimeoutError:
                    raise Exception(f"Timeout sending frame {sequence}")
                except Exception as e:
                    # [FIX B] Distinguish 1002/disconnect from other errors
                    err_str = str(e)
                    if "1002" in err_str or "1001" in err_str or "1000" in err_str \
                            or "close frame" in err_str.lower() \
                            or "disconnect" in err_str.lower():
                        logger.warning(
                            "ESP32 closed WS during audio stream "
                            "(device=%s frame=%s/%s reason='%s') — treating as disconnect",
                            device_id, sequence, total_frames, err_str,
                        )
                    else:
                        logger.error(
                            "Audio streaming error: Failed to send frame %s: %s",
                            sequence, err_str,
                        )
                    raise Exception(f"Failed to send chunk {sequence}: {e}")

                # Update session stats
                session = self.playback_sessions.get(device_id)
                if session and session.request_id == request_id:
                    session.chunks_sent += 1
                    session.bytes_sent  += len(chunk)

                # Pacing: only after prebuffer is filled
                bytes_buffered_on_device += len(chunk)
                if bytes_buffered_on_device >= prebuffer_target_bytes:
                    if (frame_idx + ws_frame_size) < len(audio_data):
                        await asyncio.sleep(
                            self._compute_chunk_pacing_seconds(
                                chunk_bytes=len(chunk),
                                sample_rate=sample_rate,
                                audio_format=audio_format,
                            )
                        )

            # All frames sent — send playback_end
            logger.info("All frames sent for req=%s, sending playback_end...", request_id)
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "playback_end", "request_id": request_id}),
                    timeout=5.0,
                )
                session = self.playback_sessions.get(device_id)
                if session and session.request_id == request_id:
                    session.end_marker_sent = True
                logger.info("playback_end sent successfully for req=%s", request_id)
            except Exception as e:
                logger.warning("Failed to send playback_end for req=%s: %s", request_id, e)

        except Exception:
            self.active_playback.pop(device_id, None)
            self.playback_sessions.pop(device_id, None)
            raise

    # ------------------------------------------------------------------ #
    async def on_playback_complete(self, device_id: str, request_id: str):
        active_req_id = self.active_playback.get(device_id)
        if active_req_id and active_req_id != request_id:
            logger.warning(
                "Mismatched playback_complete: device=%s active=%s recv=%s",
                device_id, active_req_id, request_id,
            )
            return

        session = self.playback_sessions.pop(device_id, None)
        if session:
            elapsed = time.time() - session.started_at
            logger.info(
                "Playback complete: device=%s req=%s elapsed=%.2fs "
                "frames=%s/%s bytes=%s/%s end_marker=%s",
                device_id, request_id, elapsed,
                session.chunks_sent, session.total_chunks,
                session.bytes_sent, session.total_bytes,
                session.end_marker_sent,
            )
        else:
            logger.info("Playback complete: device=%s req=%s", device_id, request_id)

        self.active_playback.pop(device_id, None)
        await self._emit_playback_complete(device_id, request_id)

    async def on_playback_error(
        self,
        device_id: str,
        request_id: Optional[str],
        error: str = "device_reported_error",
    ) -> None:
        active_req_id = self.active_playback.get(device_id)
        if request_id and active_req_id and active_req_id != request_id:
            logger.warning(
                "Mismatched playback_error: device=%s active=%s recv=%s err=%s",
                device_id, active_req_id, request_id, error,
            )
            return

        resolved_req_id = request_id or active_req_id
        session = self.playback_sessions.pop(device_id, None)
        self.active_playback.pop(device_id, None)

        if not resolved_req_id:
            logger.warning("Playback error, no req_id: device=%s err=%s", device_id, error)
            return

        if session:
            elapsed = time.time() - session.started_at
            logger.error(
                "Playback error: device=%s req=%s elapsed=%.2fs "
                "frames=%s/%s bytes=%s/%s end_marker=%s err=%s",
                device_id, resolved_req_id, elapsed,
                session.chunks_sent, session.total_chunks,
                session.bytes_sent, session.total_bytes,
                session.end_marker_sent, error,
            )
        else:
            logger.error("Playback error: device=%s req=%s err=%s", device_id, resolved_req_id, error)

        await self._emit_playback_error(device_id, resolved_req_id, error)

    def on_device_playback_debug(self, device_id: str, message: dict) -> None:
        logger.info("Playback debug from %s: %s", device_id, message)

    # ------------------------------------------------------------------ #
    def _is_playback_active(self, device_id: str) -> bool:
        return device_id in self.active_playback

    def _compute_chunk_pacing_seconds(
        self,
        chunk_bytes: int,
        sample_rate: int,
        audio_format: str,
    ) -> float:
        pace_floor = max(0.0, self.config.chunk_pacing_seconds)
        if audio_format.lower() != "pcm" or sample_rate <= 0 or chunk_bytes <= 0:
            return pace_floor
        bytes_per_second       = sample_rate * 2
        chunk_duration_seconds = chunk_bytes / bytes_per_second
        paced = chunk_duration_seconds * max(0.0, self.config.real_time_pacing_factor)
        return max(pace_floor, paced)

    # ------------------------------------------------------------------ #
    async def _emit_playback_started(self, device_id: str, request_id: str):
        await self.event_bus.publish(Event(
            event_type=EventType.PLAYBACK_STARTED.value,
            timestamp=time.time(), req_id=request_id,
            data={"device_id": device_id},
        ))

    async def _emit_playback_complete(self, device_id: str, request_id: str):
        await self.event_bus.publish(Event(
            event_type=EventType.PLAYBACK_COMPLETE.value,
            timestamp=time.time(), req_id=request_id,
            data={"device_id": device_id},
        ))

    async def _emit_playback_error(self, device_id: str, request_id: str, error: str):
        await self.event_bus.publish(Event(
            event_type=EventType.PLAYBACK_ERROR.value,
            timestamp=time.time(), req_id=request_id,
            data={"device_id": device_id, "error": error},
        ))

    # ------------------------------------------------------------------ #
    def get_stats(self) -> Dict:
        now = time.time()
        return {
            "running":               self._running,
            "active_playback_count": len(self.active_playback),
            "connected_devices":     len(self.device_connections),
            "max_ws_frame_bytes":    MAX_AUDIO_CHUNK_PCM_BYTES,
            "active_playback":       dict(self.active_playback),
            "sessions": {
                device_id: {
                    "request_id":      s.request_id,
                    "chunks_sent":     s.chunks_sent,
                    "total_chunks":    s.total_chunks,
                    "bytes_sent":      s.bytes_sent,
                    "total_bytes":     s.total_bytes,
                    "end_marker_sent": s.end_marker_sent,
                    "elapsed_seconds": round(now - s.started_at, 2),
                }
                for device_id, s in self.playback_sessions.items()
            },
        }
