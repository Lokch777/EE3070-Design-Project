# Application Coordinator - Integrates all components
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
        
        # Initialize event bus
        self.event_bus = EventBus(buffer_size=settings.event_buffer_size)
        
        # Initialize resource management
        self.resource_manager = ResourceManager(
            event_bus=self.event_bus,
            max_concurrent_requests=settings.max_concurrent_requests
        )
        self.memory_monitor = MemoryMonitor(
            event_bus=self.event_bus,
            low_memory_threshold=0.8
        )
        
        # Initialize error handler
        self.error_handler = ErrorHandler(event_bus=self.event_bus)
        
        # Initialize ASR bridge
        self.asr_bridge = ASRBridge(
            api_key=settings.asr_api_key,
            endpoint=settings.asr_endpoint,
            event_bus=self.event_bus
        )
        
        # Initialize trigger engines
        self.trigger_engine = TriggerEngine(
            event_bus=self.event_bus,
            cooldown_seconds=settings.cooldown_seconds
        )
        
        # Initialize question trigger engine
        english_phrases = [p.strip() for p in settings.trigger_english_phrases.split(',')]
        chinese_phrases = [p.strip() for p in settings.trigger_chinese_phrases.split(',')]
        
        trigger_config = TriggerConfig(
            english_triggers=english_phrases,
            chinese_triggers=chinese_phrases,
            cooldown_seconds=float(settings.cooldown_seconds),
            fuzzy_match_threshold=settings.trigger_fuzzy_threshold
        )
        self.question_trigger_engine = QuestionTriggerEngine(
            event_bus=self.event_bus,
            config=trigger_config
        )
        
        # Initialize capture coordinator
        self.capture_coordinator = CaptureCoordinator(
            event_bus=self.event_bus,
            timeout_seconds=settings.capture_timeout_seconds,
            max_retries=2
        )
        
        # Initialize vision adapter
        if settings.vision_api_key and settings.vision_api_key != "your_vision_api_key_here":
            self.vision_adapter: VisionLLMAdapter = QwenOmniAdapter(
                api_key=settings.vision_api_key,
                model=settings.vision_model,
                endpoint=settings.vision_endpoint,
                timeout_seconds=settings.vision_timeout_seconds
            )
        else:
            logger.warning("Using mock vision adapter (no API key configured)")
            self.vision_adapter = MockVisionAdapter()
        
        # Initialize TTS components
        tts_config = TTSConfig(
            api_key=settings.tts_api_key,
            endpoint=settings.tts_endpoint,
            voice=settings.tts_voice,
            language=settings.tts_language,
            speed=settings.tts_speed,
            pitch=settings.tts_pitch,
            audio_format=settings.tts_audio_format,
            sample_rate=settings.tts_sample_rate,
            timeout_seconds=settings.tts_timeout_seconds
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
            retry_attempts=settings.tts_retry_attempts
        )

        # Initialize audio playback coordinator
        playback_config = PlaybackConfig(
            chunk_size=settings.audio_chunk_size,
            buffer_size=settings.audio_buffer_size,
            stream_timeout=settings.audio_stream_timeout
        )
        self.audio_playback_coordinator = AudioPlaybackCoordinator(
            event_bus=self.event_bus,
            config=playback_config
        )
        
        self.running = False
        self.tasks = []
        self._asr_task: Optional[asyncio.Task] = None
        
        logger.info("AppCoordinator initialized with TTS support")
    
    async def start(self):
        """Start the application coordinator"""
        self.running = True
        logger.info("Starting AppCoordinator...")
        
        # Start question trigger engine
        await self.question_trigger_engine.start()
        
        # Start TTS adapter
        await self.tts_adapter.start()
        
        # Start audio playback coordinator
        await self.audio_playback_coordinator.start()

        # Connect ASR bridge and start receiver
        asr_connected = await self.asr_bridge.connect()
        if asr_connected:
            self._asr_task = asyncio.create_task(self._consume_asr_stream())
            self.tasks.append(self._asr_task)
        else:
            logger.warning("ASR bridge did not connect at startup; audio transcription unavailable")
        
        # Start event processing task
        event_task = asyncio.create_task(self.process_events())
        self.tasks.append(event_task)
        
        logger.info("AppCoordinator started with all TTS components")
    
    async def stop(self):
        """Stop the application coordinator"""
        self.running = False
        logger.info("Stopping AppCoordinator...")

        await self.question_trigger_engine.stop()
        await self.tts_adapter.stop()
        await self.audio_playback_coordinator.stop()

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self._asr_task = None

        # Close ASR connection
        await self.asr_bridge.close()
        
        logger.info("AppCoordinator stopped")

    async def _consume_asr_stream(self) -> None:
        """Continuously consume ASR results and auto-reconnect when disconnected."""
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

    async def handle_audio_chunk(self, audio_chunk: bytes, device_id: str = "default") -> None:
        """Forward audio chunk from device to ASR service."""
        if not self.asr_bridge.connected:
            logger.warning("ASR bridge not connected while receiving audio; attempting reconnect")
            connected = await self.asr_bridge.connect()
            if connected and not self._asr_task:
                self._asr_task = asyncio.create_task(self._consume_asr_stream())
                self.tasks.append(self._asr_task)

        if not self.asr_bridge.connected:
            logger.error(f"Dropping audio chunk from {device_id}: ASR unavailable")
            return

        if not self.asr_bridge.validate_audio_format(audio_chunk):
            logger.warning(f"Audio chunk from {device_id} has unexpected format/size")

        await self.asr_bridge.send_audio(audio_chunk, device_id=device_id)

    def register_audio_device(self, device_id: str, websocket: WebSocket) -> None:
        """Register an audio websocket for downstream playback streaming."""
        self.audio_playback_coordinator.register_device(device_id, websocket)

    def unregister_audio_device(self, device_id: str) -> None:
        """Unregister device websocket when disconnected."""
        self.audio_playback_coordinator.unregister_device(device_id)

    async def on_audio_control_message(self, device_id: str, message: dict) -> None:
        """Handle non-audio control messages from /ws_audio channel."""
        msg_type = message.get("type")
        if msg_type == "playback_complete":
            req_id = message.get("request_id")
            if req_id:
                await self.audio_playback_coordinator.on_playback_complete(device_id, req_id)
        elif msg_type == "request_more_audio":
            # Current coordinator pushes full audio eagerly; keep for telemetry/debug only.
            logger.debug(
                "Device requested more audio: device_id=%s request_id=%s buffer_available=%s",
                device_id,
                message.get("request_id"),
                message.get("buffer_available")
            )
    
    async def process_events(self):
        """Process events from event bus and coordinate actions"""
        try:
            async for event in self.event_bus.subscribe("*"):
                if not self.running:
                    break
                
                # Handle different event types
                if event.event_type == EventType.ASR_FINAL.value:
                    await self.handle_asr_final(event)
                
                elif event.event_type == EventType.TRIGGER_FIRED.value:
                    await self.handle_trigger_fired(event)
                
                elif event.event_type == EventType.QUESTION_DETECTED.value:
                    await self.handle_question_detected(event)
                
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
    
    async def handle_asr_final(self, event: Event):
        """Handle ASR final text event"""
        text = event.data.get("text", "")
        device_id = event.data.get("device_id", "default")
        logger.debug(f"ASR final: {text}")
        
        # Check for trigger
        trigger_event = self.trigger_engine.check_trigger(text, device_id=device_id)
        
        if trigger_event:
            # Publish trigger event
            await self.event_bus.publish(trigger_event)
    
    async def handle_question_detected(self, event: Event):
        """Handle question detected event from QuestionTriggerEngine"""
        req_id = event.req_id
        question = event.data.get("question", "")
        device_id = event.data.get("device_id", "default")
        
        logger.info(f"Handling question: req_id={req_id}, question={question}")
        
        # Check resource availability
        if not await self.resource_manager.acquire_request_lock(req_id, device_id):
            logger.warning(f"Request rejected due to concurrent request limit: req_id={req_id}")
            await self.error_handler.handle_error("concurrent_request_limit", req_id)
            return
        
        # Check memory availability
        if not await self.memory_monitor.check_memory_available(device_id, req_id):
            logger.warning(f"Request rejected due to low memory: req_id={req_id}")
            await self.error_handler.handle_error("memory_low", req_id)
            await self.resource_manager.release_request_lock(req_id, device_id)
            return
        
        # Request capture
        await self.capture_coordinator.request_capture(req_id, question, device_id=device_id)
        
        # Wait for image
        image_bytes = await self.capture_coordinator.wait_for_image(req_id)
        
        if image_bytes:
            # Image received, proceed to vision analysis with question context
            await self.analyze_with_vision(req_id, question, image_bytes, device_id)
        else:
            # Timeout or error
            logger.error(f"Failed to receive image for req_id={req_id}")
            await self.error_handler.handle_error("capture_timeout", req_id)
            await self.resource_manager.release_request_lock(req_id, device_id)
    
    async def handle_vision_result(self, event: Event):
        """Handle vision result event - trigger TTS conversion"""
        req_id = event.req_id
        text = event.data.get("text", "") or event.data.get("description", "")
        
        logger.info(f"Vision result received: req_id={req_id}, text_length={len(text)}")
        
        # TTS adapter will automatically handle this event
        # No action needed here, just logging
    
    async def handle_playback_complete(self, event: Event):
        """Handle playback complete event - release resources"""
        req_id = event.req_id
        device_id = event.data.get("device_id", "default")
        
        logger.info(f"Playback complete: req_id={req_id}, device_id={device_id}")
        
        # Release request lock only if this request currently owns it.
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_tts_error(self, event: Event):
        """Release request lock when TTS conversion fails."""
        req_id = event.req_id
        device_id = event.data.get("device_id", "default")
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)

    async def handle_playback_error(self, event: Event):
        """Release request lock when audio playback transport fails."""
        req_id = event.req_id
        device_id = event.data.get("device_id", "default")
        active_lock = self.resource_manager.get_active_request(device_id)
        if active_lock and active_lock.req_id == req_id:
            await self.resource_manager.release_request_lock(req_id, device_id)
    
    async def handle_error(self, event: Event):
        """Handle error events"""
        req_id = event.req_id
        error_type = event.data.get("error_type", "unknown")
        message = event.data.get("message", "")
        
        logger.error(f"Error event: req_id={req_id}, type={error_type}, message={message}")
        
        # Error handler will generate appropriate error messages
        # No additional action needed here
    
    async def handle_trigger_fired(self, event: Event):
        """Handle trigger fired event"""
        req_id = event.req_id
        trigger_text = event.data.get("trigger_text", "")
        device_id = event.data.get("device_id", "default")
        
        logger.info(f"Handling trigger: req_id={req_id}")
        
        # Update trigger engine state
        self.trigger_engine.update_request_state(req_id, RequestState.CAPTURING.value)
        
        # Request capture
        await self.capture_coordinator.request_capture(req_id, trigger_text, device_id=device_id)
        
        # Wait for image
        image_bytes = await self.capture_coordinator.wait_for_image(req_id)
        
        if image_bytes:
            # Image received, proceed to vision analysis
            await self.analyze_with_vision(req_id, trigger_text, image_bytes, device_id)
        else:
            # Timeout or error
            logger.error(f"Failed to receive image for req_id={req_id}")
            self.trigger_engine.complete_request(req_id)
    
    async def handle_capture_received(self, event: Event):
        """Handle capture received event"""
        req_id = event.req_id
        filename = event.data.get("filename")
        
        logger.info(f"Capture received: req_id={req_id}, filename={filename}")
        
        # Load image from file
        image_path = Path("images") / filename
        
        if image_path.exists():
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            
            # Notify capture coordinator
            self.capture_coordinator.receive_image(req_id, image_bytes)
    
    async def analyze_with_vision(self, req_id: str, prompt: str, image_bytes: bytes, device_id: str = "default"):
        """Analyze image with vision model, including question context"""
        logger.info(f"Starting vision analysis: req_id={req_id}, prompt={prompt}")
        
        # Update resource manager state
        await self.resource_manager.update_request_state(req_id, device_id, "processing")
        
        # Publish vision started event
        vision_started_event = Event(
            event_type=EventType.VISION_STARTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={
                "prompt": prompt,
                "device_id": device_id
            }
        )
        await self.event_bus.publish(vision_started_event)
        
        # Call vision model with question context
        result = await self.vision_adapter.analyze_image(image_bytes, prompt, req_id)
        
        if result.error:
            # Vision analysis failed
            logger.error(f"Vision analysis failed: {result.error}")
            
            # Use fallback message from vision adapter (already user-friendly)
            vision_result_event = Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "text": result.text,  # Fallback message
                    "confidence": None,
                    "device_id": device_id,
                    "is_error": True
                }
            )
            await self.event_bus.publish(vision_result_event)
        else:
            # Vision analysis successful
            logger.info(f"Vision analysis complete: req_id={req_id}")
            
            vision_result_event = Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "text": result.text,
                    "confidence": result.confidence,
                    "device_id": device_id,
                    "is_error": False
                }
            )
            await self.event_bus.publish(vision_result_event)
    
    def get_event_bus(self) -> EventBus:
        """Get event bus instance"""
        return self.event_bus
    
    def get_capture_coordinator(self) -> CaptureCoordinator:
        """Get capture coordinator instance"""
        return self.capture_coordinator
