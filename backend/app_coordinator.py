# Application Coordinator - Integrates all components
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from backend.event_bus import EventBus
from backend.asr_bridge import ASRBridge
from backend.trigger_engine import TriggerEngine
from backend.capture_coordinator import CaptureCoordinator
from backend.vision_adapter import VisionLLMAdapter, QwenOmniAdapter, MockVisionAdapter
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
        
        # Initialize ASR bridge
        self.asr_bridge = ASRBridge(
            api_key=settings.asr_api_key,
            endpoint=settings.asr_endpoint,
            event_bus=self.event_bus
        )
        
        # Initialize trigger engine
        self.trigger_engine = TriggerEngine(
            event_bus=self.event_bus,
            cooldown_seconds=settings.cooldown_seconds
        )
        
        # Initialize capture coordinator
        self.capture_coordinator = CaptureCoordinator(
            event_bus=self.event_bus,
            timeout_seconds=settings.capture_timeout_seconds
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
        
        self.running = False
        self.tasks = []
        
        logger.info("AppCoordinator initialized")
    
    async def start(self):
        """Start the application coordinator"""
        self.running = True
        logger.info("Starting AppCoordinator...")
        
        # Start event processing task
        event_task = asyncio.create_task(self.process_events())
        self.tasks.append(event_task)
        
        logger.info("AppCoordinator started")
    
    async def stop(self):
        """Stop the application coordinator"""
        self.running = False
        logger.info("Stopping AppCoordinator...")
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        
        # Close ASR connection
        await self.asr_bridge.close()
        
        logger.info("AppCoordinator stopped")
    
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
                
                elif event.event_type == EventType.CAPTURE_RECEIVED.value:
                    await self.handle_capture_received(event)
                
        except asyncio.CancelledError:
            logger.info("Event processing cancelled")
        except Exception as e:
            logger.error(f"Error processing events: {e}")
    
    async def handle_asr_final(self, event: Event):
        """Handle ASR final text event"""
        text = event.data.get("text", "")
        logger.debug(f"ASR final: {text}")
        
        # Check for trigger
        trigger_event = self.trigger_engine.check_trigger(text)
        
        if trigger_event:
            # Publish trigger event
            await self.event_bus.publish(trigger_event)
    
    async def handle_trigger_fired(self, event: Event):
        """Handle trigger fired event"""
        req_id = event.req_id
        trigger_text = event.data.get("trigger_text", "")
        
        logger.info(f"Handling trigger: req_id={req_id}")
        
        # Update trigger engine state
        self.trigger_engine.update_request_state(req_id, RequestState.CAPTURING.value)
        
        # Request capture
        await self.capture_coordinator.request_capture(req_id, trigger_text)
        
        # Wait for image
        image_bytes = await self.capture_coordinator.wait_for_image(req_id)
        
        if image_bytes:
            # Image received, proceed to vision analysis
            await self.analyze_with_vision(req_id, trigger_text, image_bytes)
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
    
    async def analyze_with_vision(self, req_id: str, prompt: str, image_bytes: bytes):
        """Analyze image with vision model"""
        logger.info(f"Starting vision analysis: req_id={req_id}")
        
        # Update state
        self.trigger_engine.update_request_state(req_id, RequestState.VISION_RUNNING.value)
        
        # Publish vision started event
        vision_started_event = Event(
            event_type=EventType.VISION_STARTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"prompt": prompt}
        )
        await self.event_bus.publish(vision_started_event)
        
        # Call vision model
        result = await self.vision_adapter.analyze_image(image_bytes, prompt, req_id)
        
        if result.error:
            # Vision analysis failed
            logger.error(f"Vision analysis failed: {result.error}")
            
            error_event = Event(
                event_type=EventType.ERROR.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "error_type": "vision_api_error",
                    "message": result.error
                }
            )
            await self.event_bus.publish(error_event)
        else:
            # Vision analysis successful
            logger.info(f"Vision analysis complete: req_id={req_id}")
            
            vision_result_event = Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "text": result.text,
                    "confidence": result.confidence
                }
            )
            await self.event_bus.publish(vision_result_event)
        
        # Complete request
        self.trigger_engine.complete_request(req_id)
    
    def get_event_bus(self) -> EventBus:
        """Get event bus instance"""
        return self.event_bus
    
    def get_capture_coordinator(self) -> CaptureCoordinator:
        """Get capture coordinator instance"""
        return self.capture_coordinator
