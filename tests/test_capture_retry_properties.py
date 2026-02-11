# Property-based tests for capture retry logic
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from hypothesis import given, strategies as st, settings, assume
from backend.capture_coordinator import CaptureCoordinator
from backend.event_bus import EventBus
from backend.models import EventType
import asyncio


@pytest.mark.asyncio
@settings(max_examples=50, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    trigger_text=st.text(min_size=5, max_size=50),
    timeout_seconds=st.integers(min_value=1, max_value=3),
    max_retries=st.integers(min_value=1, max_value=3),
)
async def test_property_6_capture_retry_logic(req_id, trigger_text, timeout_seconds, max_retries):
    """
    **Property 6: Capture retry logic**
    
    *For any* image capture failure, the system SHALL retry up to 2 times, 
    and if all attempts fail, SHALL emit an error event with appropriate error message.
    
    **Validates: Requirements 3.3**
    """
    event_bus = EventBus()
    coordinator = CaptureCoordinator(event_bus, timeout_seconds=timeout_seconds, max_retries=max_retries)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to events
    event_bus.subscribe(EventType.CAPTURE_REQUESTED.value, capture_event)
    event_bus.subscribe(EventType.ERROR.value, capture_event)
    
    # Request capture (will timeout since no image is provided)
    await coordinator.request_capture(req_id, trigger_text)
    
    # Wait for image (will timeout and retry)
    result = await coordinator.wait_for_image(req_id)
    
    # Wait for all events to be published
    await asyncio.sleep(0.2)
    
    # Verify capture failed after retries
    assert result is None, "Capture should fail after all retries exhausted"
    
    # Verify capture was requested multiple times (initial + retries)
    capture_requests = [e for e in published_events if e.event_type == EventType.CAPTURE_REQUESTED.value]
    expected_requests = max_retries + 1  # Initial request + retries
    assert len(capture_requests) == expected_requests, \
        f"Should have {expected_requests} capture requests (1 initial + {max_retries} retries), got {len(capture_requests)}"
    
    # Verify retry count in events
    for i, event in enumerate(capture_requests):
        assert event.data["retry_count"] == i, f"Request {i} should have retry_count={i}"
    
    # Verify final error event was published
    error_events = [e for e in published_events if e.event_type == EventType.ERROR.value]
    assert len(error_events) >= 1, "At least one error event should be published"
    
    # Check final error event
    final_error = error_events[-1]
    assert final_error.req_id == req_id, "Final error should have correct req_id"
    assert "error_type" in final_error.data, "Final error should contain error_type"
    assert "message" in final_error.data, "Final error should contain error message"
    assert final_error.data["retry_count"] == max_retries, f"Final error should show {max_retries} retries"


@pytest.mark.asyncio
@settings(max_examples=30, deadline=5000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    trigger_text=st.text(min_size=5, max_size=50),
    image_size=st.integers(min_value=100, max_value=50000),
)
async def test_property_capture_success_no_retry(req_id, trigger_text, image_size):
    """
    Test that successful capture does not trigger retries.
    
    Verifies that:
    - When image is received successfully, no retries occur
    - Retry count is cleaned up on success
    """
    event_bus = EventBus()
    coordinator = CaptureCoordinator(event_bus, timeout_seconds=5, max_retries=2)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to events
    event_bus.subscribe(EventType.CAPTURE_REQUESTED.value, capture_event)
    
    # Request capture
    await coordinator.request_capture(req_id, trigger_text)
    
    # Simulate successful image receipt
    fake_image = b'\xff\xd8\xff\xe0' + b'\x00' * image_size + b'\xff\xd9'  # Minimal JPEG structure
    
    # Provide image immediately (before timeout)
    await asyncio.sleep(0.1)
    coordinator.receive_image(req_id, fake_image)
    
    # Wait for image (should succeed immediately)
    result = await coordinator.wait_for_image(req_id)
    
    # Wait for events
    await asyncio.sleep(0.1)
    
    # Verify only one capture request was made (no retries)
    capture_requests = [e for e in published_events if e.event_type == EventType.CAPTURE_REQUESTED.value]
    assert len(capture_requests) == 1, "Should have exactly 1 capture request (no retries on success)"
    
    # Verify retry count is 0
    assert capture_requests[0].data["retry_count"] == 0, "Initial request should have retry_count=0"
