# Capture Coordinator for managing image capture requests
import asyncio
import time
import logging
from typing import Optional, Dict
from backend.models import Event, EventType, RequestState
from backend.event_bus import EventBus
from PIL import Image
import io

logger = logging.getLogger(__name__)


class CaptureCoordinator:
    """
    Coordinates image capture requests between trigger engine and ESP32.
    Manages timeouts and validates received images.
    """
    
    def __init__(self, event_bus: EventBus, timeout_seconds: int = 5):
        self.event_bus = event_bus
        self.timeout_seconds = timeout_seconds
        self.pending_captures: Dict[str, asyncio.Future] = {}
        self.state = RequestState.LISTENING.value
        
        logger.info(f"CaptureCoordinator initialized with {timeout_seconds}s timeout")
    
    async def request_capture(self, req_id: str, trigger_text: str) -> None:
        """
        Send CAPTURE command to ESP32.
        
        Args:
            req_id: Request ID
            trigger_text: Original trigger text
        """
        self.state = RequestState.CAPTURE_REQUESTED.value
        
        # Create capture request event
        event = Event(
            event_type=EventType.CAPTURE_REQUESTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"trigger_text": trigger_text}
        )
        
        await self.event_bus.publish(event)
        logger.info(f"Capture requested: req_id={req_id}")
        
        # Create future for waiting
        future = asyncio.Future()
        self.pending_captures[req_id] = future
        
        self.state = RequestState.WAITING_IMAGE.value
    
    async def wait_for_image(self, req_id: str) -> Optional[bytes]:
        """
        Wait for image from ESP32 with timeout.
        
        Args:
            req_id: Request ID to wait for
            
        Returns:
            Image bytes if received, None if timeout
        """
        if req_id not in self.pending_captures:
            logger.error(f"No pending capture for req_id={req_id}")
            return None
        
        future = self.pending_captures[req_id]
        
        try:
            # Wait with timeout
            image_bytes = await asyncio.wait_for(future, timeout=self.timeout_seconds)
            logger.info(f"Image received for req_id={req_id}")
            self.state = RequestState.DONE.value
            return image_bytes
            
        except asyncio.TimeoutError:
            logger.error(f"Capture timeout for req_id={req_id}")
            self.state = RequestState.ERROR.value
            
            # Publish timeout error event
            error_event = Event(
                event_type=EventType.ERROR.value,
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "error_type": "capture_timeout",
                    "message": f"ESP32 未在 {self.timeout_seconds} 秒內回應影像"
                }
            )
            await self.event_bus.publish(error_event)
            
            return None
            
        finally:
            # Clean up
            if req_id in self.pending_captures:
                del self.pending_captures[req_id]
            
            # Reset state
            if self.state != RequestState.ERROR.value:
                self.state = RequestState.LISTENING.value
    
    def receive_image(self, req_id: str, image_bytes: bytes) -> bool:
        """
        Receive image from ESP32 and validate.
        
        Args:
            req_id: Request ID
            image_bytes: JPEG image data
            
        Returns:
            True if valid and accepted, False otherwise
        """
        # Validate image
        if not self.validate_image(image_bytes):
            logger.error(f"Invalid image for req_id={req_id}")
            return False
        
        # Check if we're waiting for this image
        if req_id not in self.pending_captures:
            logger.warning(f"Received unexpected image for req_id={req_id}")
            return False
        
        # Fulfill the future
        future = self.pending_captures[req_id]
        if not future.done():
            future.set_result(image_bytes)
            logger.info(f"Image accepted for req_id={req_id}")
            return True
        else:
            logger.warning(f"Future already completed for req_id={req_id}")
            return False
    
    def validate_image(self, image_bytes: bytes) -> bool:
        """
        Validate image size and format.
        
        Args:
            image_bytes: Image data to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Check file size (max 200KB)
        max_size = 200 * 1024
        if len(image_bytes) > max_size:
            logger.error(f"Image too large: {len(image_bytes)} bytes (max {max_size})")
            return False
        
        # Try to open image and check resolution
        try:
            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
            
            # Check resolution (max 640x480)
            if width > 640 or height > 480:
                logger.error(f"Image resolution too high: {width}x{height} (max 640x480)")
                return False
            
            logger.debug(f"Image validated: {width}x{height}, {len(image_bytes)} bytes")
            return True
            
        except Exception as e:
            logger.error(f"Failed to validate image: {e}")
            return False
    
    def cancel_request(self, req_id: str) -> None:
        """Cancel pending capture request"""
        if req_id in self.pending_captures:
            future = self.pending_captures[req_id]
            if not future.done():
                future.cancel()
            del self.pending_captures[req_id]
            logger.info(f"Capture request cancelled: req_id={req_id}")
        
        self.state = RequestState.LISTENING.value
