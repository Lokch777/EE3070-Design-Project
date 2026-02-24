# Error handling and recovery system for ESP32 Real-Time AI Assistant
import logging
import time
from typing import Dict, Optional
from dataclasses import dataclass
from backend.models import Event, EventType, ErrorType
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ErrorMessage:
    """Error message configuration"""
    error_type: str
    message_text: str
    prerecorded_file: Optional[str] = None
    retry_allowed: bool = False
    max_retries: int = 0


class ErrorHandler:
    """
    Centralized error handling and recovery system.
    Generates appropriate error messages and manages retry logic.
    """
    
    # Error message mappings
    ERROR_MESSAGES: Dict[str, ErrorMessage] = {
        # ASR errors
        ErrorType.ASR_CONNECTION_FAILED.value: ErrorMessage(
            error_type=ErrorType.ASR_CONNECTION_FAILED.value,
            message_text="I couldn't understand that, please try again",
            prerecorded_file="error_asr.pcm",
            retry_allowed=False
        ),
        ErrorType.ASR_TIMEOUT.value: ErrorMessage(
            error_type=ErrorType.ASR_TIMEOUT.value,
            message_text="I couldn't understand that, please try again",
            prerecorded_file="error_asr.pcm",
            retry_allowed=False
        ),
        
        # Capture errors
        ErrorType.CAPTURE_TIMEOUT.value: ErrorMessage(
            error_type=ErrorType.CAPTURE_TIMEOUT.value,
            message_text="Camera unavailable, please try again",
            prerecorded_file="error_camera.pcm",
            retry_allowed=True,
            max_retries=2
        ),
        ErrorType.CAPTURE_FAILED.value: ErrorMessage(
            error_type=ErrorType.CAPTURE_FAILED.value,
            message_text="Camera unavailable, please try again",
            prerecorded_file="error_camera.pcm",
            retry_allowed=True,
            max_retries=2
        ),
        ErrorType.INVALID_IMAGE.value: ErrorMessage(
            error_type=ErrorType.INVALID_IMAGE.value,
            message_text="Camera unavailable, please try again",
            prerecorded_file="error_camera.pcm",
            retry_allowed=True,
            max_retries=2
        ),
        
        # Vision errors
        ErrorType.VISION_TIMEOUT.value: ErrorMessage(
            error_type=ErrorType.VISION_TIMEOUT.value,
            message_text="I couldn't analyze the image, please try again",
            prerecorded_file="error_vision.pcm",
            retry_allowed=False
        ),
        ErrorType.VISION_API_ERROR.value: ErrorMessage(
            error_type=ErrorType.VISION_API_ERROR.value,
            message_text="I couldn't analyze the image, please try again",
            prerecorded_file="error_vision.pcm",
            retry_allowed=False
        ),
        
        # TTS errors
        "tts_failed": ErrorMessage(
            error_type="tts_failed",
            message_text="Audio system error",
            prerecorded_file="error_tts.pcm",
            retry_allowed=True,
            max_retries=1
        ),
        
        # Network errors
        ErrorType.CONNECTION_FAILED.value: ErrorMessage(
            error_type=ErrorType.CONNECTION_FAILED.value,
            message_text="Connection lost, reconnecting",
            prerecorded_file="error_network.pcm",
            retry_allowed=True,
            max_retries=3
        ),
        ErrorType.WEBSOCKET_CLOSED.value: ErrorMessage(
            error_type=ErrorType.WEBSOCKET_CLOSED.value,
            message_text="Connection lost, reconnecting",
            prerecorded_file="error_network.pcm",
            retry_allowed=True,
            max_retries=3
        ),
        
        # Memory errors
        "memory_low": ErrorMessage(
            error_type="memory_low",
            message_text="Memory low, please wait",
            prerecorded_file="error_memory.pcm",
            retry_allowed=False
        ),
    }
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.retry_counts: Dict[str, int] = {}
        logger.info("ErrorHandler initialized")
    
    def get_error_message(self, error_type: str) -> Optional[ErrorMessage]:
        """
        Get error message configuration for error type.
        
        Args:
            error_type: Type of error
            
        Returns:
            ErrorMessage configuration or None if not found
        """
        return self.ERROR_MESSAGES.get(error_type)
    
    async def handle_error(
        self,
        error_type: str,
        req_id: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> bool:
        """
        Handle error and generate appropriate error message.
        
        Args:
            error_type: Type of error
            req_id: Request ID (if applicable)
            context: Additional error context
            
        Returns:
            True if error was handled, False otherwise
        """
        error_msg = self.get_error_message(error_type)
        
        if not error_msg:
            logger.error(f"Unknown error type: {error_type}")
            # Use generic error message
            error_msg = ErrorMessage(
                error_type="unknown",
                message_text="System error, please try again",
                retry_allowed=False
            )
        
        logger.info(f"Handling error: {error_type}, req_id={req_id}")
        
        # Publish error event with message
        error_event = Event(
            event_type=EventType.ERROR.value,
            timestamp=time.time(),
            req_id=req_id,
            data={
                "error_type": error_type,
                "message": error_msg.message_text,
                "prerecorded_file": error_msg.prerecorded_file,
                "context": context or {}
            }
        )
        
        await self.event_bus.publish(error_event)
        
        # Trigger TTS for error message (unless it's a TTS error)
        if error_type != "tts_failed":
            await self._generate_error_audio(error_msg, req_id)
        
        return True
    
    async def _generate_error_audio(
        self,
        error_msg: ErrorMessage,
        req_id: Optional[str]
    ) -> None:
        """
        Generate audio for error message.
        
        Args:
            error_msg: Error message configuration
            req_id: Request ID
        """
        # Publish event to request TTS conversion of error message
        tts_event = Event(
            event_type="error.tts_required",
            timestamp=time.time(),
            req_id=req_id,
            data={
                "text": error_msg.message_text,
                "prerecorded_file": error_msg.prerecorded_file,
                "is_error_message": True
            }
        )
        
        await self.event_bus.publish(tts_event)
    
    def should_retry(self, error_type: str, req_id: str) -> bool:
        """
        Check if error should be retried.
        
        Args:
            error_type: Type of error
            req_id: Request ID
            
        Returns:
            True if retry is allowed, False otherwise
        """
        error_msg = self.get_error_message(error_type)
        
        if not error_msg or not error_msg.retry_allowed:
            return False
        
        # Track retry count
        retry_key = f"{req_id}:{error_type}"
        current_retries = self.retry_counts.get(retry_key, 0)
        
        if current_retries >= error_msg.max_retries:
            logger.info(f"Max retries reached for {error_type}, req_id={req_id}")
            # Clean up retry count
            if retry_key in self.retry_counts:
                del self.retry_counts[retry_key]
            return False
        
        # Increment retry count
        self.retry_counts[retry_key] = current_retries + 1
        logger.info(f"Retry {current_retries + 1}/{error_msg.max_retries} for {error_type}, req_id={req_id}")
        
        return True
    
    def reset_retry_count(self, req_id: str, error_type: Optional[str] = None) -> None:
        """
        Reset retry count for request.
        
        Args:
            req_id: Request ID
            error_type: Specific error type to reset (or all if None)
        """
        if error_type:
            retry_key = f"{req_id}:{error_type}"
            if retry_key in self.retry_counts:
                del self.retry_counts[retry_key]
        else:
            # Reset all retry counts for this request
            keys_to_delete = [k for k in self.retry_counts.keys() if k.startswith(f"{req_id}:")]
            for key in keys_to_delete:
                del self.retry_counts[key]
