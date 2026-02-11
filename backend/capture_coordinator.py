# Capture Coordinator for managing image capture requests
import asyncio
import time
import logging
from typing import Optional, Dict
from backend.models import Event, EventType, RequestState, ErrorType
from backend.event_bus import EventBus
from PIL import Image
import io

logger = logging.getLogger(__name__)


class CaptureCoordinator:
    """
    Coordinates image capture requests between trigger engine and ESP32.
    Manages timeouts, validates received images, and implements retry logic.
    """
    
    def __init__(self, event_bus: EventBus, timeout_seconds: int = 5, max_retries: int = 2):
        self.event_bus = event_bus
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.pending_captures: Dict[str, asyncio.Future] = {}
        self.retry_counts: Dict[str, int] = {}
        self.state = RequestState.LISTENING.value
        
        logger.info(f"CaptureCoordinator initialized with {timeout_seconds}s timeout, {max_retries} max retries")
    
    async def request_capture(self, req_id: str, trigger_text: str, retry_count: int = 0) -> None:
        """
        Send CAPTURE command to ESP32.
        
        Args:
            req_id: Request ID
            trigger_text: Original trigger text
            retry_count: Current retry attempt number
        """
        self.state = RequestState.CAPTURE_REQUESTED.value
        
        # Track retry count
        self.retry_counts[req_id] = retry_count
        
        # Create capture request event
        event = Event(
            event_type=EventType.CAPTURE_REQUESTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={
                "trigger_text": trigger_text,
                "retry_count": retry_count
            }
        )
        
        await self.event_bus.publish(event)
        logger.info(f"Capture requested: req_id={req_id}, retry={retry_count}/{self.max_retries}")
        
        # Create future for waiting
        future = asyncio.Future()
        self.pending_captures[req_id] = future
        
        self.state = RequestState.WAITING_IMAGE.value
    
    async def wait_for_image(self, req_id: str) -> Optional[bytes]:
        """
        Wait for image from ESP32 with timeout and retry logic.
        
        Args:
            req_id: Request ID to wait for
            
        Returns:
            Image bytes if received, None if all retries exhausted
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
            
            # Clean up retry count on success
            if req_id in self.retry_counts:
                del self.retry_counts[req_id]
            
            return image_bytes
            
        except asyncio.TimeoutError:
            retry_count = self.retry_counts.get(req_id, 0)
            logger.error(f"Capture timeout for req_id={req_id}, retry={retry_count}/{self.max_retries}")
            
            # Check if we should retry
            if retry_count < self.max_retries:
                # Publish timeout error event (for logging)
                error_event = Event(
                    event_type=EventType.ERROR.value,
                    timestamp=time.time(),
                    req_id=req_id,
                    data={
                        "error_type": ErrorType.CAPTURE_TIMEOUT.value,
                        "message": f"Capture timeout, retrying {retry_count + 1}/{self.max_retries}",
                        "retry_count": retry_count
                    }
                )
                await self.event_bus.publish(error_event)
                
                # Clean up current future
                if req_id in self.pending_captures:
                    del self.pending_captures[req_id]
                
                # Retry capture
                await self.request_capture(req_id, "", retry_count + 1)
                return await self.wait_for_image(req_id)
            else:
                # All retries exhausted
                self.state = RequestState.ERROR.value
                
                # Publish final timeout error event
                error_event = Event(
                    event_type=EventType.ERROR.value,
                    timestamp=time.time(),
                    req_id=req_id,
                    data={
                        "error_type": ErrorType.CAPTURE_TIMEOUT.value,
                        "message": f"ESP32 未在 {self.timeout_seconds} 秒內回應影像 (已重試 {self.max_retries} 次)",
                        "retry_count": retry_count
                    }
                )
                await self.event_bus.publish(error_event)
                
                # Clean up retry count
                if req_id in self.retry_counts:
                    del self.retry_counts[req_id]
                
                return None
            
        finally:
            # Clean up pending capture
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
