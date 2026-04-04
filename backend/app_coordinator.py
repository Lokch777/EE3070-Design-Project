# Application Coordinator - Integrates all components
# FIXES:
#   1. self._asr_connect_lock added inside __init__ (was at module level causing NameError)
#   2. _ensure_asr_ready wrapped with asyncio.Lock (prevents double ASR connect race)
#   3. unregister_audio_device passes websocket param (stale disconnect guard)
#   4. ASR model_id fallback aligned to qwen3-asr-flash-realtime-2026-02-10

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional
from fastapi import WebSocket

from backend.event_bus import EventBus
from backend.asr_bridge import ASRBridge
from backend.trigger_engine import TriggerEngine
from backend.question_trigger_engine import QuestionTriggerEngine, TriggerConfig
from backend.capture_coordinator import CaptureCoordinator
from backend.vision_adapter import VisionLLMAdapter, QwenOmniAdapter, MockVisionAdapter
from backend.tts_adapter import TTSAdapter
from backend.tts_client import TTSClient, TTSConfig, MockTTSClient
from backend.audio_playback_coordinator import AudioPlaybackCoordinator, PlaybackConfig
from backend.error_handler import ErrorHandler
from backend.resource_manager import ResourceManager, MemoryMonitor
from backend.models import Event, EventType, RequestState
from backend.config import Settings

logger = logging.getLogger(__name__)


class AppCoordinator:
    """
    Main application coordinator that integrates all components.
    Manages the complete flow: Audio → ASR → Trigger → Capture → Vision → UI
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        self.event_bus = EventBus(buffer_size=settings.event_buffer_size)

        self.resource_manager = ResourceManager(
            event_bus=self.event_bus,
            max_concurrent_requests=settings.max_concurrent_requests,
        )
        self.memory_monitor = MemoryMonitor(
            event_bus=self.event_bus,
            low_memory_threshold=0.8,
        )

        self.error_handler = ErrorHandler(event_bus=self.event_bus)

        # ✅ FIX 4: aligned fallback model_id
        self.asr_bridge = ASRBridge(
            api_key=settings.asr_api_key,
            endpoint=settings.asr_endpoint,
            event_bus=self.event_bus,
            model_id=getattr(settings, 'asr_model', 'qwen3-asr-flash-realtime-2026-02-10'),
        )

        self.trigger_engine = TriggerEngine(
            event_bus=self.event_bus,
            cooldown_seconds=settings.cooldown_seconds,
        )

        raw_english_phrases = [p.strip() for p in settings.trigger_english_phrases.split(',') if p.strip()]
        english_phrases = [p for p in raw_english_phrases if p.isascii()]
        if not english_phrases:
            english_phrases = ["what's in front of me", "describe the view", "what do I see"]
        chinese_phrases = [
            "描述一下眼前",
            "我看到什麼",
            "前面是什麼",
            "告訴我你看到什麼",
        ]

        trigger_config = TriggerConfig(
            english_triggers=english_phrases,
            chinese_triggers=chinese_phrases,
            cooldown_seconds=float(settings.cooldown_seconds),
            fuzzy_match_threshold=settings.trigger_fuzzy_threshold,
        )

        logger.info("Question trigger language mode: BILINGUAL")
        self.question_trigger_engine = QuestionTriggerEngine(
            event_bus=self.event_bus,
            config=trigger_config,
        )

        self.capture_coordinator = CaptureCoordinator(
            event_bus=self.event_bus,
            timeout_seconds=settings.capture_timeout_seconds,
            max_retries=2,
        )

        if settings.vision_api_key and settings.vision_api_key != "your_vision_api_key_here":
            self.vision_adapter: VisionLLMAdapter = QwenOmniAdapter(
                api_key=settings.vision_api_key,
                model=settings.vision_model,
                endpoint=settings.vision_endpoint,
                timeout_seconds=settings.vision_timeout_seconds,
            )
        else:
            logger.warning("Using mock vision adapter (no API key configured)")
            self.vision_adapter = MockVisionAdapter()

        tts_config = TTSConfig(
            api_key=settings.tts_api_key,
            endpoint=settings.tts_endpoint,
            voice=settings.tts_voice,
            language=settings.tts_language,
            speed=settings.tts_speed,
            pitch=settings.tts_pitch,
            audio_format=settings.tts_audio_format,
            sample_rate=settings.tts_sample_rate,
            timeout_seconds=settings.tts_timeout_seconds,
            fallback_max_chars=settings.tts_fallback_max_chars,
        )

        if settings.tts_api_key and settings.tts_api_key != "your_tts_api_key_here":
            self.tts_client = TTSClient(tts_config)
        else:
            logger.warning("Using mock TTS client (no API key configured)")
            self.tts_client = MockTTSClient(tts_config)

        self.tts_adapter = TTSAdapter(
            event_bus=self.event_bus,
            tts_client=self.tts_client,
            config=tts_config,
            retry_attempts=settings.tts_retry_attempts,
        )

        playback_config = PlaybackConfig(
            chunk_size=settings.audio_chunk_size,
            buffer_size=settings.audio_buffer_size,
            stream_timeout=settings.audio_stream_timeout,
            chunk_pacing_seconds=settings.audio_chunk_pacing_seconds,
            real_time_pacing_factor=settings.audio_realtime_pacing_factor,
        )
        self.audio_playback_coordinator = AudioPlaybackCoordinator(
            event_bus=self.event_bus,
            config=playback_config,
        )

        self.running       = False
        self.tasks         = []
        self._asr_task: Optional[asyncio.Task] = None
        self._audio_forward_task: Optional[asyncio.Task] = None
        self._audio_chunk_queue = asyncio.Queue(maxsize=24)
        self._audio_ingest_stats = {}
        self._audio_forward_stats = {}
        # ✅ FIX 1 & 2: lock lives here inside __init__, not at module level
        self._asr_connect_lock = asyncio.Lock()

        logger.info("AppCoordinator initialized with TTS support")

    # ------------------------------------------------------------------ #
    async def start(self):
        self.running = True
        logger.info("Starting AppCoordinator...")

        await self.question_trigger_engine.start()
        await self.tts_adapter.start()
        await self.audio_playback_coordinator.start()

        self._audio_forward_task = asyncio.create_task(self._forward_audio_chunks())
        self.tasks.append(self._audio_forward_task)

        event_task = asyncio.create_task(self.process_events())
        self.tasks.append(event_task)

        logger.info("AppCoordinator started with all TTS components (ASR lazy connect enabled)")

    async def stop(self):
        self.running = False
        logger.info("Stopping AppCoordinator...")

        await self.question_trigger_engine.stop()
        await self.tts_adapter.stop()
        await self.audio_playback_coordinator.stop()

        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self._clear_audio_chunk_queue()
        self._audio_forward_task = None
        self._asr_task = None

        await self.asr_bridge.close()
        logger.info("AppCoordinator stopped")

    # ------------------------------------------------------------------ #
    async def _consume_asr_stream(self) -> None:
        while self.running:
            try:
                async for _ in self.asr_bridge.receive_transcription():
                    if not self.running:
                        return
                if not self.running:
                    return
                reconnected = await self.asr_bridge.reconnect()
                if not reconnected:
                    logger.error("ASR reconnect failed; retrying after delay")
                    await asyncio.sleep(self.asr_bridge.reconnect_delay)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"ASR stream consumer error: {e}")
                await asyncio.sleep(1)

    async def _ensure_asr_ready(self) -> bool:
        # Fast path: already connected
        if self.asr_bridge.connected:
            if not self._asr_task or self._asr_task.done():
                self._asr_task = asyncio.create_task(self._consume_asr_stream())
                self.tasks.append(self._asr_task)
            return True

        # ✅ FIX 2: Lock prevents multiple concurrent audio chunks all
        # calling asr_bridge.connect() simultaneously → double-connection bug
        async with self._asr_connect_lock:
            # Double-check inside lock — another coroutine may have connected first
            if self.asr_bridge.connected:
                if not self._asr_task or self._asr_task.done():
                    self._asr_task = asyncio.create_task(self._consume_asr_stream())
                    self.tasks.append(self._asr_task)
                return True

            logger.info("Connecting ASR bridge on demand for incoming device audio")
            connected = await self.asr_bridge.connect()
            if not connected:
                return False

            if not self._asr_task or self._asr_task.done():
                self._asr_task = asyncio.create_task(self._consume_asr_stream())
                self.tasks.append(self._asr_task)
            return True

    async def _shutdown_asr_if_idle(self) -> None:
        if self.audio_playback_coordinator.device_connections:
            return

        self._clear_audio_chunk_queue()

        if self._asr_task:
            self._asr_task.cancel()
            try:
                await self._asr_task
            except asyncio.CancelledError:
                pass
            self._asr_task = None

        if self.asr_bridge.connected:
            logger.info("Closing ASR bridge because no audio devices are connected")
            await self.asr_bridge.close()

    # ------------------------------------------------------------------ #
    async def _forward_audio_chunks(self) -> None:
        while self.running:
            try:
                device_id, audio_chunk = await self._audio_chunk_queue.get()
            except asyncio.CancelledError:
                return

            try:
                if not await self._ensure_asr_ready():
                    logger.error("Dropping queued audio chunk from %s: ASR unavailable", device_id)
                    continue
                if not self.asr_bridge.validate_audio_format(audio_chunk):
                    logger.warning("Audio chunk from %s has unexpected format/size", device_id)
                await self.asr_bridge.send_audio(audio_chunk, device_id=device_id)
                self._record_audio_stat(
                    self._audio_forward_stats,
                    "Audio forward active",
                    device_id,
                    len(audio_chunk),
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Failed to forward audio chunk from %s: %s", device_id, e)
            finally:
                self._audio_chunk_queue.task_done()

    def _clear_audio_chunk_queue(self) -> None:
        while not self._audio_chunk_queue.empty():
            try:
                self._audio_chunk_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._audio_chunk_queue.task_done()

    async def handle_audio_chunk(self, audio_chunk: bytes, device_id: str = "default") -> None:
        if not audio_chunk:
            logger.warning("Dropping empty audio chunk from %s", device_id)
            return

        try:
            self._audio_chunk_queue.put_nowait((device_id, audio_chunk))
            self._record_audio_stat(
                self._audio_ingest_stats,
                "Audio ingress active",
                device_id,
                len(audio_chunk),
            )
        except asyncio.QueueFull:
            logger.warning(
                "Audio ingest queue full for %s (pending=%s); dropping chunk",
                device_id,
                self._audio_chunk_queue.qsize(),
            )

    def _record_audio_stat(
        self,
        stats_map: dict,
        label: str,
        device_id: str,
        chunk_bytes: int,
    ) -> None:
        now = time.time()
        stats = stats_map.setdefault(
            device_id,
            {"chunks": 0, "bytes": 0, "last_log_at": 0.0},
        )
        stats["chunks"] += 1
        stats["bytes"] += chunk_bytes

        if stats["chunks"] == 1 or (now - stats["last_log_at"]) >= 2.0:
            logger.info(
                "%s: device=%s chunks=%s bytes=%s queue=%s",
                label,
                device_id,
                stats["chunks"],
                stats["bytes"],
                self._audio_chunk_queue.qsize(),
            )
            stats["last_log_at"] = now

    def register_audio_device(self, device_id: str, websocket: WebSocket) -> None:
        self.audio_playback_coordinator.register_device(device_id, websocket)
        if self.running:
            asyncio.create_task(self._ensure_asr_ready())

    def unregister_audio_device(self, device_id: str, websocket: WebSocket = None) -> None:
        # ✅ FIX 3: pass websocket so coordinator can reject stale disconnects
        self.audio_playback_coordinator.unregister_device(device_id, websocket)
        asyncio.create_task(self._shutdown_asr_if_idle())

    async def on_audio_control_message(self, device_id: str, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "playback_complete":
            req_id = message.get("request_id")
            if req_id:
                await self.audio_playback_coordinator.on_playback_complete(device_id, req_id)
            else:
                logger.warning("playback_complete missing request_id from device_id=%s", device_id)
        elif msg_type == "playback_error":
            req_id = message.get("request_id")
            error  = message.get("reason") or message.get("error") or "device_reported_error"
            await self.audio_playback_coordinator.on_playback_error(device_id, req_id, error)
        elif msg_type == "request_more_audio":
            logger.debug(
                "Device requested more audio: device_id=%s request_id=%s buffer_available=%s",
                device_id, message.get("request_id"), message.get("buffer_available"),
            )
        elif msg_type in {"playback_debug", "playback_stats"}:
            self.audio_playback_coordinator.on_device_playback_debug(device_id, message)
        else:
            logger.debug("Unknown /ws_audio control message from %s: %s", device_id, message)

    # ------------------------------------------------------------------ #
    async def process_events(self):
        try:
            async for event in self.event_bus.subscribe("*"):
                if not self.running:
                    break

                if event.event_type == EventType.ASR_FINAL.value:
                    await self.handle_asr_final(event)

                elif event.event_type == EventType.TRIGGER_FIRED.value:
                    asyncio.create_task(self.handle_trigger_fired(event))

                elif event.event_type == EventType.QUESTION_DETECTED.value:
                    asyncio.create_task(self.handle_question_detected(event))

                elif event.event_type == EventType.CAPTURE_RECEIVED.value:
                    await self.handle_capture_received(event)

                elif event.event_type == EventType.VISION_RESULT.value:
                    await self.handle_vision_result(event)

                elif event.event_type == EventType.PLAYBACK_COMPLETE.value:
                    await self.handle_playback_complete(event)

                elif event.event_type == EventType.TTS_ERROR.value:
                    await self.handle_tts_error(event)

                elif event.event_type == EventType.PLAYBACK_ERROR.value:
                    await self.handle_playback_error(event)

                elif event.event_type == EventType.ERROR.value:
                    await self.handle_error(event)

        except asyncio.CancelledError:
            logger.info("Event processing cancelled")
        except Exception as e:
            logger.error(f"Error processing events: {e}")

    # ------------------------------------------------------------------ #
    async def handle_asr_final(self, event: Event):
        text      = event.data.get("text", "")
        device_id = event.data.get("device_id", "default")
        logger.debug(f"ASR final: {text}")
        trigger_event = self.trigger_engine.check_trigger(text, device_id=device_id)
        if trigger_event:
            await self.event_bus.publish(trigger_event)

    async def handle_question_detected(self, event: Event):
        req_id    = event.req_id
        question  = event.data.get("question", "")
        device_id = event.data.get("device_id", "default")
        logger.info(f"Handling question: req_id={req_id}, question={question}")

        if not await self.resource_manager.acquire_request_lock(req_id, device_id):
            logger.warning(f"Request rejected due to concurrent request limit: req_id={req_id}")
            await self.error_handler.handle_error("concurrent_request_limit", req_id)
            return

        if not await self.memory_monitor.check_memory_available(device_id, req_id):
            logger.warning(f"Request rejected due to low memory: req_id={req_id}")
            await self.error_handler.handle_error("memory_low", req_id)
            await self.resource_manager.release_request_lock(req_id, device_id)
            return

        await self.capture_coordinator.request_capture(req_id, question, device_id=device_id)
        image_bytes = await self.capture_coordinator.wait_for_image(req_id)

        if image_bytes:
            await self.analyze_with_vision(req_id, question, image_bytes, device_id)
        else:
            logger.error(f"Failed to receive image for req_id={req_id}")
            await self.error_handler.handle_error("capture_timeout", req_id)
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_vision_result(self, event: Event):
        req_id = event.req_id
        text   = event.data.get("text", "") or event.data.get("description", "")
        logger.info(f"Vision result received: req_id={req_id}, text_length={len(text)}")

    async def handle_playback_complete(self, event: Event):
        req_id    = event.req_id
        device_id = event.data.get("device_id", "default")
        logger.info(f"Playback complete: req_id={req_id}, device_id={device_id}")
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_tts_error(self, event: Event):
        req_id    = event.req_id
        device_id = event.data.get("device_id", "default")
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_playback_error(self, event: Event):
        req_id    = event.req_id
        device_id = event.data.get("device_id", "default")
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_error(self, event: Event):
        req_id     = event.req_id
        error_type = event.data.get("error_type", "unknown")
        message    = event.data.get("message", "")
        logger.error(f"Error event: req_id={req_id}, type={error_type}, message={message}")

    async def handle_trigger_fired(self, event: Event):
        req_id       = event.req_id
        trigger_text = event.data.get("trigger_text", "")
        device_id    = event.data.get("device_id", "default")
        logger.info(f"Handling trigger: req_id={req_id}")

        self.trigger_engine.update_request_state(req_id, RequestState.CAPTURING.value)
        await self.capture_coordinator.request_capture(req_id, trigger_text, device_id=device_id)
        image_bytes = await self.capture_coordinator.wait_for_image(req_id)

        if image_bytes:
            await self.analyze_with_vision(req_id, trigger_text, image_bytes, device_id)
        else:
            logger.error(f"Failed to receive image for req_id={req_id}")
            self.trigger_engine.complete_request(req_id)

    async def handle_capture_received(self, event: Event):
        req_id    = event.req_id
        filename  = event.data.get("filename")
        device_id = event.data.get("device_id", "default")
        logger.info(f"Capture received: req_id={req_id}, filename={filename}")

        image_path = Path("images") / filename
        if image_path.exists():
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            self.capture_coordinator.receive_image(req_id, image_bytes)

            if str(req_id).startswith("test-"):
                logger.info(f"強制測試捷徑啟動：直接分析圖片 {filename}")
                default_prompt = "請用簡短、口語的中文描述你看到了什麼。"
                asyncio.create_task(
                    self.analyze_with_vision(req_id, default_prompt, image_bytes, device_id)
                )
        else:
            logger.error(f"找不到圖片檔案：{image_path}")

    async def analyze_with_vision(
        self,
        req_id: str,
        prompt: str,
        image_bytes: bytes,
        device_id: str = "default",
    ):
        logger.info(f"Starting vision analysis: req_id={req_id}, prompt={prompt}")
        await self.resource_manager.update_request_state(req_id, device_id, "processing")

        await self.event_bus.publish(Event(
            event_type=EventType.VISION_STARTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"prompt": prompt, "device_id": device_id},
        ))

        result = await self.vision_adapter.analyze_image(image_bytes, prompt, req_id)

        if result.error:
            logger.error(f"Vision analysis failed: {result.error}")
            await self.event_bus.publish(Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "text":       result.text,
                    "confidence": None,
                    "device_id":  device_id,
                    "is_error":   True,
                },
            ))
        else:
            logger.info(f"Vision analysis complete: req_id={req_id}")
            await self.event_bus.publish(Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "text":       result.text,
                    "confidence": result.confidence,
                    "device_id":  device_id,
                    "is_error":   False,
                },
            ))

    # ------------------------------------------------------------------ #
    def get_event_bus(self) -> EventBus:
        return self.event_bus

    def get_capture_coordinator(self) -> CaptureCoordinator:
        return self.capture_coordinator
