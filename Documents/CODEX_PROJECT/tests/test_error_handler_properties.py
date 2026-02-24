# Property-based tests for error handling system
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from hypothesis import given, strategies as st, settings
from backend.error_handler import ErrorHandler
from backend.event_bus import EventBus
from backend.models import ErrorType, EventType
import asyncio


# Strategy for generating error types
error_types = st.sampled_from([
    ErrorType.ASR_CONNECTION_FAILED.value,
    ErrorType.ASR_TIMEOUT.value,
    ErrorType.CAPTURE_TIMEOUT.value,
    ErrorType.CAPTURE_FAILED.value,
    ErrorType.INVALID_IMAGE.value,
    ErrorType.VISION_TIMEOUT.value,
    ErrorType.VISION_API_ERROR.value,
    "tts_failed",
    ErrorType.CONNECTION_FAILED.value,
    ErrorType.WEBSOCKET_CLOSED.value,
    "memory_low",
])


@pytest.mark.asyncio
@settings(max_examples=100)
@given(
    error_type=error_types,
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
)
async def test_property_15_error_message_generation(error_type, req_id):
    """
    **Property 15: Error message generation**
    
    *For any* component failure (ASR, capture, vision, TTS, network), 
    the system SHALL generate a spoken error message appropriate to the specific failure type.
    
    **Validates: Requirements 8.1**
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to error events
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    event_bus.subscribe("error.tts_required", capture_event)
    
    # Handle the error
    result = await error_handler.handle_error(error_type, req_id)
    
    # Wait for events to be published
    await asyncio.sleep(0.1)
    
    # Verify error was handled
    assert result is True, f"Error handler should return True for error_type={error_type}"
    
    # Verify error event was published
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) > 0, f"Error event should be published for error_type={error_type}"
    
    error_event = error_events[0]
    assert error_event.req_id == req_id, "Error event should have correct req_id"
    assert "error_type" in error_event.data, "Error event should contain error_type"
    assert "message" in error_event.data, "Error event should contain error message"
    
    # Verify error message is not empty
    message = error_event.data["message"]
    assert len(message) > 0, f"Error message should not be empty for error_type={error_type}"
    
    # Verify TTS event was published (unless it's a TTS error)
    if error_type != "tts_failed":
        tts_events = [e for e in published_events if e.event_type == "error.tts_required"]
        assert len(tts_events) > 0, f"TTS event should be published for error_type={error_type}"
        
        tts_event = tts_events[0]
        assert "text" in tts_event.data, "TTS event should contain text"
        assert tts_event.data["text"] == message, "TTS text should match error message"
        assert tts_event.data.get("is_error_message") is True, "TTS event should be marked as error message"


@pytest.mark.asyncio
@settings(max_examples=50)
@given(
    error_type=st.sampled_from([
        ErrorType.CAPTURE_TIMEOUT.value,
        ErrorType.CAPTURE_FAILED.value,
        "tts_failed",
        ErrorType.CONNECTION_FAILED.value,
    ]),
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
)
async def test_property_error_retry_logic(error_type, req_id):
    """
    Test that retry logic works correctly for retryable errors.
    
    Verifies that:
    - Retryable errors allow retries up to max_retries
    - Non-retryable errors do not allow retries
    - Retry count is tracked correctly
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    error_msg = error_handler.get_error_message(error_type)
    
    if error_msg and error_msg.retry_allowed:
        # Test retry logic for retryable errors
        for i in range(error_msg.max_retries):
            should_retry = error_handler.should_retry(error_type, req_id)
            assert should_retry is True, f"Should allow retry {i+1}/{error_msg.max_retries}"
        
        # After max retries, should not retry
        should_retry = error_handler.should_retry(error_type, req_id)
        assert should_retry is False, "Should not allow retry after max_retries"
    else:
        # Non-retryable errors should never retry
        should_retry = error_handler.should_retry(error_type, req_id)
        assert should_retry is False, f"Non-retryable error {error_type} should not allow retry"


@pytest.mark.asyncio
@settings(max_examples=50)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
)
async def test_property_error_retry_reset(req_id):
    """
    Test that retry count reset works correctly.
    
    Verifies that:
    - Retry count can be reset for specific error types
    - Retry count can be reset for all error types
    - After reset, retries are allowed again
    """
    event_bus = EventBus()
    error_handler = ErrorHandler(event_bus)
    
    error_type = ErrorType.CAPTURE_TIMEOUT.value
    
    # Exhaust retries
    while error_handler.should_retry(error_type, req_id):
        pass
    
    # Should not retry after exhaustion
    assert error_handler.should_retry(error_type, req_id) is False
    
    # Reset retry count
    error_handler.reset_retry_count(req_id, error_type)
    
    # Should allow retry again
    should_retry = error_handler.should_retry(error_type, req_id)
    assert should_retry is True, "Should allow retry after reset"
