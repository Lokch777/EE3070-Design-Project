# Property-based tests for Question Trigger Engine
import pytest
import asyncio
import time
from hypothesis import given, strategies as st, settings
from backend.question_trigger_engine import QuestionTriggerEngine, TriggerConfig
from backend.event_bus import EventBus
from backend.models import Event, EventType


# Test configuration
TRIGGER_PHRASES_ENGLISH = [
    "describe the view",
    "what do I see",
    "what's in front of me",
    "tell me what you see"
]

TRIGGER_PHRASES_CHINESE = [
    "描述一下景象",
    "我看到什麼",
    "前面是什麼",
    "告訴我你看到什麼"
]


@pytest.fixture
def event_bus():
    """Create event bus for testing"""
    return EventBus(buffer_size=100)


@pytest.fixture
def trigger_config():
    """Create trigger configuration for testing"""
    return TriggerConfig(
        english_triggers=TRIGGER_PHRASES_ENGLISH,
        chinese_triggers=TRIGGER_PHRASES_CHINESE,
        cooldown_seconds=3.0,
        fuzzy_match_threshold=0.85
    )


@pytest.fixture
async def trigger_engine(event_bus, trigger_config):
    """Create and start trigger engine for testing"""
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    await engine.start()
    yield engine
    await engine.stop()


# Strategy for generating transcriptions with trigger phrases
@st.composite
def transcription_with_trigger(draw):
    """Generate transcription containing a trigger phrase"""
    # Choose a random trigger phrase
    all_triggers = TRIGGER_PHRASES_ENGLISH + TRIGGER_PHRASES_CHINESE
    trigger = draw(st.sampled_from(all_triggers))
    
    # Add optional prefix and suffix
    prefix = draw(st.text(min_size=0, max_size=50, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs')
    )))
    suffix = draw(st.text(min_size=0, max_size=50, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs')
    )))
    
    # Combine into full transcription
    parts = [p for p in [prefix, trigger, suffix] if p.strip()]
    transcription = " ".join(parts)
    
    return transcription, trigger


@pytest.mark.asyncio
@given(data=transcription_with_trigger())
@settings(max_examples=100, deadline=None)
async def test_property_trigger_detection_and_question_extraction(data):
    """
    **Property 3: Trigger detection and question extraction**
    
    For any transcription containing a valid trigger phrase (English or Chinese),
    the Question_Trigger_Engine SHALL detect the trigger, extract the user's
    question text, and emit a capture event with the question context.
    
    **Validates: Requirements 2.1, 2.5**
    """
    transcription, expected_trigger = data
    
    # Create components
    event_bus = EventBus(buffer_size=100)
    trigger_config = TriggerConfig(
        english_triggers=TRIGGER_PHRASES_ENGLISH,
        chinese_triggers=TRIGGER_PHRASES_CHINESE,
        cooldown_seconds=3.0,
        fuzzy_match_threshold=0.85
    )
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    await engine.start()
    
    try:
        # Create ASR transcription event
        asr_event = Event(
            event_type=EventType.ASR_FINAL.value,
            timestamp=time.time(),
            req_id=f"test_{int(time.time() * 1000)}",
            data={
                "text": transcription,
                "device_id": "test_device",
                "confidence": 0.95
            }
        )
        
        # Publish ASR event
        await event_bus.publish(asr_event)
        
        # Wait for trigger engine to process
        await asyncio.sleep(0.1)
        
        # Check that question detected event was emitted
        history = event_bus.get_history(limit=10)
        question_events = [
            e for e in history 
            if e.event_type == EventType.QUESTION_DETECTED.value
        ]
        
        # Verify trigger was detected
        assert len(question_events) > 0, \
            f"Expected question detected event for transcription: {transcription}"
        
        # Verify question text was extracted
        question_event = question_events[0]
        assert "question" in question_event.data, \
            "Question data missing from event"
        assert question_event.data["question"] == transcription, \
            f"Question text mismatch: expected '{transcription}', got '{question_event.data['question']}'"
        
        # Verify device ID was preserved
        assert question_event.data["device_id"] == "test_device", \
            "Device ID not preserved"
        
    finally:
        await engine.stop()


@pytest.mark.asyncio
@given(
    trigger_phrase=st.sampled_from(TRIGGER_PHRASES_ENGLISH + TRIGGER_PHRASES_CHINESE),
    prefix=st.text(min_size=0, max_size=30),
    suffix=st.text(min_size=0, max_size=30)
)
@settings(max_examples=50, deadline=None)
async def test_property_trigger_detection_with_variations(trigger_phrase, prefix, suffix):
    """
    Test trigger detection with various text variations.
    
    Verifies that triggers are detected regardless of surrounding text.
    """
    # Create transcription with trigger phrase
    parts = [p for p in [prefix, trigger_phrase, suffix] if p.strip()]
    transcription = " ".join(parts)
    
    # Create components
    event_bus = EventBus(buffer_size=100)
    trigger_config = TriggerConfig(
        english_triggers=TRIGGER_PHRASES_ENGLISH,
        chinese_triggers=TRIGGER_PHRASES_CHINESE,
        cooldown_seconds=3.0,
        fuzzy_match_threshold=0.85
    )
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    
    # Test trigger detection (without starting engine)
    trigger_match = engine._detect_trigger(transcription)
    
    # Verify trigger was detected
    assert trigger_match is not None, \
        f"Failed to detect trigger '{trigger_phrase}' in '{transcription}'"
    assert trigger_match.confidence >= 0.85, \
        f"Confidence too low: {trigger_match.confidence}"
    assert trigger_match.question == transcription, \
        "Question text not extracted correctly"



@pytest.mark.asyncio
@given(
    trigger_count=st.integers(min_value=2, max_value=5),
    time_between=st.floats(min_value=0.1, max_value=2.9)
)
@settings(max_examples=100, deadline=None)
async def test_property_cooldown_prevention(trigger_count, time_between):
    """
    **Property 4: Cooldown prevention**
    
    For any sequence of trigger phrases detected within 3 seconds,
    the Question_Trigger_Engine SHALL process only the first trigger
    and ignore all subsequent triggers until the current request completes.
    
    **Validates: Requirements 2.4**
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    trigger_config = TriggerConfig(
        english_triggers=TRIGGER_PHRASES_ENGLISH,
        chinese_triggers=TRIGGER_PHRASES_CHINESE,
        cooldown_seconds=3.0,
        fuzzy_match_threshold=0.85
    )
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    await engine.start()
    
    try:
        # Send multiple trigger events within cooldown period
        for i in range(trigger_count):
            asr_event = Event(
                event_type=EventType.ASR_FINAL.value,
                timestamp=time.time(),
                req_id=f"test_{i}_{int(time.time() * 1000)}",
                data={
                    "text": f"describe the view {i}",
                    "device_id": "test_device",
                    "confidence": 0.95
                }
            )
            
            await event_bus.publish(asr_event)
            
            # Wait a short time between triggers (less than cooldown)
            if i < trigger_count - 1:
                await asyncio.sleep(time_between)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Check how many question detected events were emitted
        history = event_bus.get_history(limit=20)
        question_events = [
            e for e in history 
            if e.event_type == EventType.QUESTION_DETECTED.value
        ]
        
        # Verify only the first trigger was processed
        assert len(question_events) == 1, \
            f"Expected 1 question event, got {len(question_events)}. " \
            f"Cooldown should prevent processing of subsequent triggers."
        
        # Verify cooldown is active
        assert engine._is_cooldown_active(), \
            "Cooldown should be active after trigger"
        
    finally:
        await engine.stop()


@pytest.mark.asyncio
@given(
    cooldown_seconds=st.floats(min_value=1.0, max_value=5.0),
    wait_time=st.floats(min_value=0.1, max_value=0.9)
)
@settings(max_examples=50, deadline=None)
async def test_property_cooldown_timing(cooldown_seconds, wait_time):
    """
    Test that cooldown timing is enforced correctly.
    
    Verifies that triggers within cooldown period are ignored,
    and triggers after cooldown period are accepted.
    """
    # Create components with custom cooldown
    event_bus = EventBus(buffer_size=100)
    trigger_config = TriggerConfig(
        english_triggers=TRIGGER_PHRASES_ENGLISH,
        chinese_triggers=TRIGGER_PHRASES_CHINESE,
        cooldown_seconds=cooldown_seconds,
        fuzzy_match_threshold=0.85
    )
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    await engine.start()
    
    try:
        # First trigger
        asr_event1 = Event(
            event_type=EventType.ASR_FINAL.value,
            timestamp=time.time(),
            req_id="test_1",
            data={
                "text": "describe the view",
                "device_id": "test_device",
                "confidence": 0.95
            }
        )
        await event_bus.publish(asr_event1)
        await asyncio.sleep(0.1)
        
        # Second trigger within cooldown (should be ignored)
        await asyncio.sleep(wait_time)
        asr_event2 = Event(
            event_type=EventType.ASR_FINAL.value,
            timestamp=time.time(),
            req_id="test_2",
            data={
                "text": "what do I see",
                "device_id": "test_device",
                "confidence": 0.95
            }
        )
        await event_bus.publish(asr_event2)
        await asyncio.sleep(0.1)
        
        # Check events
        history = event_bus.get_history(limit=20)
        question_events = [
            e for e in history 
            if e.event_type == EventType.QUESTION_DETECTED.value
        ]
        
        # Should only have 1 event (second was within cooldown)
        assert len(question_events) == 1, \
            f"Expected 1 question event during cooldown, got {len(question_events)}"
        
        # Wait for cooldown to expire
        remaining_cooldown = cooldown_seconds - wait_time
        await asyncio.sleep(remaining_cooldown + 0.2)
        
        # Third trigger after cooldown (should be accepted)
        asr_event3 = Event(
            event_type=EventType.ASR_FINAL.value,
            timestamp=time.time(),
            req_id="test_3",
            data={
                "text": "tell me what you see",
                "device_id": "test_device",
                "confidence": 0.95
            }
        )
        await event_bus.publish(asr_event3)
        await asyncio.sleep(0.1)
        
        # Check events again
        history = event_bus.get_history(limit=20)
        question_events = [
            e for e in history 
            if e.event_type == EventType.QUESTION_DETECTED.value
        ]
        
        # Should now have 2 events (third was after cooldown)
        assert len(question_events) == 2, \
            f"Expected 2 question events after cooldown, got {len(question_events)}"
        
    finally:
        await engine.stop()
