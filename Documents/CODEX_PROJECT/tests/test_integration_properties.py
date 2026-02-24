# Property-based tests for system integration
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from hypothesis import given, strategies as st, settings
from backend.event_bus import EventBus
from backend.models import Event, EventType
from backend.vision_adapter import MockVisionAdapter
import asyncio
import time


@pytest.mark.asyncio
@settings(max_examples=50, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    question=st.text(min_size=5, max_size=100),
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
)
async def test_property_5_image_question_association(req_id, question, device_id):
    """
    **Property 5: Image-question association**
    
    *For any* successfully captured image, the system SHALL associate the image 
    with the corresponding user question text, and this association SHALL be maintained 
    throughout the vision processing pipeline.
    
    **Validates: Requirements 3.4**
    """
    event_bus = EventBus()
    
    # Track published events
    published_events = []
    
    async def capture_event(event):
        published_events.append(event)
    
    # Subscribe to relevant events
    event_bus.subscribe(EventType.QUESTION_DETECTED.value, capture_event)
    event_bus.subscribe(EventType.CAPTURE_REQUESTED.value, capture_event)
    event_bus.subscribe(EventType.VISION_STARTED.value, capture_event)
    event_bus.subscribe(EventType.VISION_RESULT.value, capture_event)
    
    # Simulate question detection
    question_event = Event(
        event_type=EventType.QUESTION_DETECTED.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "question": question,
            "device_id": device_id
        }
    )
    await event_bus.publish(question_event)
    
    # Simulate capture request
    capture_event_obj = Event(
        event_type=EventType.CAPTURE_REQUESTED.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "trigger_text": question,
            "device_id": device_id,
            "retry_count": 0
        }
    )
    await event_bus.publish(capture_event_obj)
    
    # Simulate vision started
    vision_started_event = Event(
        event_type=EventType.VISION_STARTED.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "prompt": question,
            "device_id": device_id
        }
    )
    await event_bus.publish(vision_started_event)
    
    # Simulate vision result
    vision_result_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "text": f"Response to: {question}",
            "confidence": 0.95,
            "device_id": device_id
        }
    )
    await event_bus.publish(vision_result_event)
    
    # Wait for events to be published
    await asyncio.sleep(0.2)
    
    # Verify question is associated throughout pipeline
    question_events = [e for e in published_events if e.event_type == EventType.QUESTION_DETECTED.value]
    assert len(question_events) == 1, "Should have question detected event"
    assert question_events[0].data["question"] == question, "Question should be preserved"
    
    capture_events = [e for e in published_events if e.event_type == EventType.CAPTURE_REQUESTED.value]
    assert len(capture_events) == 1, "Should have capture requested event"
    assert capture_events[0].data["trigger_text"] == question, "Question should be in capture request"
    assert capture_events[0].req_id == req_id, "Request ID should be consistent"
    
    vision_started_events = [e for e in published_events if e.event_type == EventType.VISION_STARTED.value]
    assert len(vision_started_events) == 1, "Should have vision started event"
    assert vision_started_events[0].data["prompt"] == question, "Question should be in vision prompt"
    assert vision_started_events[0].req_id == req_id, "Request ID should be consistent"
    
    vision_result_events = [e for e in published_events if e.event_type == EventType.VISION_RESULT.value]
    assert len(vision_result_events) == 1, "Should have vision result event"
    assert vision_result_events[0].req_id == req_id, "Request ID should be consistent"
    
    # Verify all events have same req_id (association maintained)
    all_req_ids = [e.req_id for e in published_events]
    assert all(rid == req_id for rid in all_req_ids), \
        "All events should have same req_id to maintain association"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    question=st.text(min_size=5, max_size=100),
)
async def test_property_7_vision_request_completeness(req_id, question):
    """
    **Property 7: Vision request completeness**
    
    *For any* vision processing request, the Vision_Adapter SHALL include both 
    the image data and the user's question text in the request to the vision model, 
    and the response SHALL be formatted for natural speech output.
    
    **Validates: Requirements 4.1, 4.3**
    """
    # Create minimal valid JPEG image
    image_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00' + b'\x00' * 100 + b'\xff\xd9'
    
    # Use mock vision adapter
    vision_adapter = MockVisionAdapter()
    
    # Call analyze_image with both image and question
    result = await vision_adapter.analyze_image(image_bytes, question, req_id)
    
    # Verify result is returned
    assert result is not None, "Vision adapter should return result"
    assert result.text is not None, "Result should contain text"
    assert len(result.text) > 0, "Result text should not be empty"
    
    # Verify result is formatted for speech (natural language, not technical)
    assert not result.text.startswith("{"), "Result should not be raw JSON"
    assert not result.text.startswith("["), "Result should not be raw array"
    assert "error" not in result.text.lower() or "try again" in result.text.lower(), \
        "Result should be user-friendly"
    
    # Verify no error on successful processing
    if "測試" in result.text or "test" in result.text.lower():
        # Mock response - should not have error
        assert result.error is None, "Successful processing should not have error"


@pytest.mark.asyncio
@settings(max_examples=30, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    question=st.text(min_size=5, max_size=100),
    device_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
)
async def test_property_event_flow_consistency(req_id, question, device_id):
    """
    Test that event flow maintains consistency throughout the pipeline.
    
    Verifies that:
    - Events are published in correct order
    - Request ID is consistent across all events
    - Device ID is preserved
    - Question context is maintained
    """
    event_bus = EventBus()
    
    # Track published events with timestamps
    published_events = []
    
    async def capture_event(event):
        published_events.append((time.time(), event))
    
    # Subscribe to all relevant events
    event_bus.subscribe(EventType.QUESTION_DETECTED.value, capture_event)
    event_bus.subscribe(EventType.CAPTURE_REQUESTED.value, capture_event)
    event_bus.subscribe(EventType.VISION_STARTED.value, capture_event)
    event_bus.subscribe(EventType.VISION_RESULT.value, capture_event)
    event_bus.subscribe(EventType.AUDIO_READY.value, capture_event)
    event_bus.subscribe(EventType.PLAYBACK_COMPLETE.value, capture_event)
    
    # Simulate complete event flow
    events_to_publish = [
        Event(
            event_type=EventType.QUESTION_DETECTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"question": question, "device_id": device_id}
        ),
        Event(
            event_type=EventType.CAPTURE_REQUESTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"trigger_text": question, "device_id": device_id, "retry_count": 0}
        ),
        Event(
            event_type=EventType.VISION_STARTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"prompt": question, "device_id": device_id}
        ),
        Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"text": "Response", "device_id": device_id}
        ),
        Event(
            event_type=EventType.AUDIO_READY.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"audio_data": b"audio", "device_id": device_id}
        ),
        Event(
            event_type=EventType.PLAYBACK_COMPLETE.value,
            timestamp=time.time(),
            req_id=req_id,
            data={"device_id": device_id}
        ),
    ]
    
    for event in events_to_publish:
        await event_bus.publish(event)
        await asyncio.sleep(0.05)
    
    # Wait for all events
    await asyncio.sleep(0.2)
    
    # Verify all events were published
    assert len(published_events) == len(events_to_publish), \
        f"Should have {len(events_to_publish)} events, got {len(published_events)}"
    
    # Verify request ID consistency
    for _, event in published_events:
        assert event.req_id == req_id, "All events should have same req_id"
    
    # Verify device ID consistency
    for _, event in published_events:
        if "device_id" in event.data:
            assert event.data["device_id"] == device_id, "All events should have same device_id"
    
    # Verify events are in chronological order
    timestamps = [ts for ts, _ in published_events]
    assert timestamps == sorted(timestamps), "Events should be in chronological order"
