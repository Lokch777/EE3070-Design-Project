# Unit tests for specific error messages
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from backend.error_handler import ErrorHandler
from backend.event_bus import EventBus
from backend.models import ErrorType, EventType
import asyncio


@pytest.mark.asyncio
async def test_asr_failure_error_message():
    """
    Test ASR failure error message.
    
    **Validates: Requirements 8.2**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle ASR error
    await error_handler.handle_error(ErrorType.ASR_CONNECTION_FAILED.value, "req_123")
    await asyncio.sleep(0.1)
    
    # Verify error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "I couldn't understand that, please try again"


@pytest.mark.asyncio
async def test_camera_failure_error_message():
    """
    Test camera failure error message.
    
    **Validates: Requirements 8.3**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle capture error
    await error_handler.handle_error(ErrorType.CAPTURE_TIMEOUT.value, "req_123")
    await asyncio.sleep(0.1)
    
    # Verify error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "Camera unavailable, please try again"


@pytest.mark.asyncio
async def test_vision_failure_error_message():
    """
    Test vision failure error message.
    
    **Validates: Requirements 8.4**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle vision error
    await error_handler.handle_error(ErrorType.VISION_TIMEOUT.value, "req_123")
    await asyncio.sleep(0.1)
    
    # Verify error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "I couldn't analyze the image, please try again"


@pytest.mark.asyncio
async def test_tts_failure_error_message():
    """
    Test TTS failure error message.
    
    **Validates: Requirements 8.5**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle TTS error
    await error_handler.handle_error("tts_failed", "req_123")
    await asyncio.sleep(0.1)
    
    # Verify error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "Audio system error"
    
    # Verify NO TTS event is published for TTS errors (to avoid infinite loop)
    tts_events = [e for e in published_events if e.event_type == "error.tts_required"]
    assert len(tts_events) == 0, "Should not request TTS for TTS errors"


@pytest.mark.asyncio
async def test_network_loss_error_message():
    """
    Test network loss error message.
    
    **Validates: Requirements 8.6**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle network error
    await error_handler.handle_error(ErrorType.CONNECTION_FAILED.value, "req_123")
    await asyncio.sleep(0.1)
    
    # Verify error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "Connection lost, reconnecting"


@pytest.mark.asyncio
async def test_prerecorded_error_message_fallback():
    """
    Test that prerecorded error message file is included in error events.
    
    **Validates: Requirements 8.5**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    
    # Handle error with prerecorded message
    await error_handler.handle_error(ErrorType.CAPTURE_TIMEOUT.value, "req_123")
    await asyncio.sleep(0.1)
    
    # Verify prerecorded file is included
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert "prerecorded_file" in error_events[0].data
    assert error_events[0].data["prerecorded_file"] == "error_camera.pcm"


@pytest.mark.asyncio
async def test_unknown_error_type_fallback():
    """
    Test that unknown error types get a generic fallback message.
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle unknown error type
    await error_handler.handle_error("unknown_error_type", "req_123")
    await asyncio.sleep(0.1)
    
    # Verify generic error message
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) == 1
    assert error_events[0].data["message"] == "System error, please try again"
