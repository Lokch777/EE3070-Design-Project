# Property-based tests for resource management and concurrency control
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from hypothesis import given, strategies as st, settings
from backend.resource_manager import ResourceManager, MemoryMonitor
from backend.event_bus import EventBus
from backend.models import EventType
import asyncio


@pytest.mark.asyncio
@settings(max_examples=100, deadline=5000)
@given(
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    req_ids=st.lists(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
        min_size=2,
        max_size=5,
        unique=True
    ),
)
async def test_property_19_concurrent_request_limitation(device_id, req_ids):
    """
    **Property 19: Concurrent request limitation**
    
    *For any* system state, the system SHALL limit concurrent audio processing 
    to one request at a time, rejecting new requests while a request is in progress.
    
    **Validates: Requirements 11.3**
    """
    event_bus = EventBus()
    resource_manager = ResourceManager(event_bus, max_concurrent_requests=1)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to events
    event_bus.subscribe("request.lock_acquired", capture_event)
    event_bus.subscribe("request.rejected", capture_event)
    event_bus.subscribe("request.lock_released", capture_event)
    
    # Try to acquire lock for first request (should succeed)
    first_req_id = req_ids[0]
    result1 = await resource_manager.acquire_request_lock(first_req_id, device_id)
    await asyncio.sleep(0.1)
    
    assert result1 is True, "First request should acquire lock successfully"
    
    # Verify lock acquired event
    lock_events = [e for e in published_events if e.event_type == "request.lock_acquired"]
    assert len(lock_events) == 1, "Should have one lock acquired event"
    assert lock_events[0].req_id == first_req_id
    
    # Try to acquire lock for subsequent requests (should fail)
    for req_id in req_ids[1:]:
        result = await resource_manager.acquire_request_lock(req_id, device_id)
        await asyncio.sleep(0.1)
        
        assert result is False, f"Concurrent request {req_id} should be rejected"
    
    # Verify rejection events
    rejection_events = [e for e in published_events if e.event_type == "request.rejected"]
    assert len(rejection_events) == len(req_ids) - 1, \
        f"Should have {len(req_ids) - 1} rejection events for concurrent requests"
    
    # Verify all rejections mention the active request
    for event in rejection_events:
        assert event.data["active_req_id"] == first_req_id, \
            "Rejection should mention the active request ID"
        assert event.data["reason"] == "concurrent_request_limit", \
            "Rejection reason should be concurrent_request_limit"
    
    # Release the first request lock
    await resource_manager.release_request_lock(first_req_id, device_id)
    await asyncio.sleep(0.1)
    
    # Verify lock released event
    release_events = [e for e in published_events if e.event_type == "request.lock_released"]
    assert len(release_events) == 1, "Should have one lock released event"
    assert release_events[0].req_id == first_req_id
    
    # Now a new request should succeed
    second_req_id = req_ids[1]
    result2 = await resource_manager.acquire_request_lock(second_req_id, device_id)
    await asyncio.sleep(0.1)
    
    assert result2 is True, "New request should acquire lock after previous release"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=5000)
@given(
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    memory_usage=st.floats(min_value=0.8, max_value=1.0),
)
async def test_property_20_low_memory_protection(device_id, req_id, memory_usage):
    """
    **Property 20: Low memory protection**
    
    *For any* ESP32 device in a low memory state, the system SHALL reject new requests 
    and play a pre-configured memory error message.
    
    **Validates: Requirements 11.4**
    """
    event_bus = EventBus()
    memory_monitor = MemoryMonitor(event_bus, low_memory_threshold=0.8)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to memory events
    event_bus.subscribe("memory.low", capture_event)
    
    # Set device memory to low state
    memory_monitor.update_memory_usage(device_id, memory_usage)
    
    # Check memory availability (should fail)
    result = await memory_monitor.check_memory_available(device_id, req_id)
    await asyncio.sleep(0.1)
    
    # Verify memory check failed
    assert result is False, f"Memory check should fail when usage={memory_usage*100:.1f}% >= 80%"
    
    # Verify low memory event was published
    memory_events = [e for e in published_events if e.event_type == "memory.low"]
    assert len(memory_events) == 1, "Should publish low memory event"
    
    memory_event = memory_events[0]
    assert memory_event.req_id == req_id, "Memory event should have correct req_id"
    assert memory_event.data["device_id"] == device_id, "Memory event should have correct device_id"
    assert memory_event.data["memory_usage"] == memory_usage, "Memory event should report actual usage"
    assert "message" in memory_event.data, "Memory event should contain error message"
    assert len(memory_event.data["message"]) > 0, "Error message should not be empty"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=5000)
@given(
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    memory_usage=st.floats(min_value=0.0, max_value=0.79),
)
async def test_property_memory_available_when_sufficient(device_id, req_id, memory_usage):
    """
    Test that memory check passes when memory is sufficient.
    
    Verifies that:
    - Memory check succeeds when usage is below threshold
    - No low memory event is published
    """
    event_bus = EventBus()
    memory_monitor = MemoryMonitor(event_bus, low_memory_threshold=0.8)
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to memory events
    event_bus.subscribe("memory.low", capture_event)
    
    # Set device memory to normal state
    memory_monitor.update_memory_usage(device_id, memory_usage)
    
    # Check memory availability (should succeed)
    result = await memory_monitor.check_memory_available(device_id, req_id)
    await asyncio.sleep(0.1)
    
    # Verify memory check passed
    assert result is True, f"Memory check should pass when usage={memory_usage*100:.1f}% < 80%"
    
    # Verify no low memory event was published
    memory_events = [e for e in published_events if e.event_type == "memory.low"]
    assert len(memory_events) == 0, "Should not publish low memory event when memory is sufficient"


@pytest.mark.asyncio
@settings(max_examples=30, deadline=5000)
@given(
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    states=st.lists(
        st.sampled_from(["processing", "playback", "complete"]),
        min_size=1,
        max_size=3
    ),
)
async def test_property_request_state_tracking(device_id, req_id, states):
    """
    Test that request state is tracked correctly throughout lifecycle.
    
    Verifies that:
    - Request state can be updated
    - State transitions are tracked
    - Lock is maintained during state changes
    """
    event_bus = EventBus()
    resource_manager = ResourceManager(event_bus, max_concurrent_requests=1)
    
    # Acquire lock
    result = await resource_manager.acquire_request_lock(req_id, device_id)
    assert result is True, "Should acquire lock"
    
    # Update states
    for state in states:
        await resource_manager.update_request_state(req_id, device_id, state)
        
        # Verify lock is still active
        active_lock = resource_manager.get_active_request(device_id)
        assert active_lock is not None, "Lock should remain active during state changes"
        assert active_lock.req_id == req_id, "Lock should be for correct request"
        assert active_lock.state == state, f"State should be updated to {state}"
    
    # Release lock
    await resource_manager.release_request_lock(req_id, device_id)
    
    # Verify lock is released
    active_lock = resource_manager.get_active_request(device_id)
    assert active_lock is None, "Lock should be released"
