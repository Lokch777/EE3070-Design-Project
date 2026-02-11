# Unit tests for Question Trigger Engine
import pytest
import asyncio
import time
from backend.question_trigger_engine import QuestionTriggerEngine, TriggerConfig, TriggerMatch
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


# Test each English trigger phrase individually
@pytest.mark.asyncio
async def test_english_trigger_describe_the_view(trigger_engine):
    """Test English trigger: 'describe the view'"""
    text = "Please describe the view for me"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "describe the view"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_english_trigger_what_do_i_see(trigger_engine):
    """Test English trigger: 'what do I see'"""
    text = "what do I see in front of me"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "what do I see"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_english_trigger_whats_in_front_of_me(trigger_engine):
    """Test English trigger: 'what's in front of me'"""
    text = "Can you tell me what's in front of me"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "what's in front of me"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_english_trigger_tell_me_what_you_see(trigger_engine):
    """Test English trigger: 'tell me what you see'"""
    text = "tell me what you see right now"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "tell me what you see"
    assert match.confidence >= 0.85
    assert match.question == text


# Test each Chinese trigger phrase individually
@pytest.mark.asyncio
async def test_chinese_trigger_describe_view(trigger_engine):
    """Test Chinese trigger: '描述一下景象'"""
    text = "請描述一下景象"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "描述一下景象"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_chinese_trigger_what_do_i_see(trigger_engine):
    """Test Chinese trigger: '我看到什麼'"""
    text = "我看到什麼東西"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "我看到什麼"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_chinese_trigger_whats_in_front(trigger_engine):
    """Test Chinese trigger: '前面是什麼'"""
    text = "前面是什麼呢"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "前面是什麼"
    assert match.confidence >= 0.85
    assert match.question == text


@pytest.mark.asyncio
async def test_chinese_trigger_tell_me_what_you_see(trigger_engine):
    """Test Chinese trigger: '告訴我你看到什麼'"""
    text = "請告訴我你看到什麼"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "告訴我你看到什麼"
    assert match.confidence >= 0.85
    assert match.question == text


# Test fuzzy matching with variations
@pytest.mark.asyncio
async def test_fuzzy_match_describe_view_variation(trigger_engine):
    """Test fuzzy matching with slight variation"""
    text = "describe the views"  # 'views' instead of 'view'
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.confidence >= 0.85


@pytest.mark.asyncio
async def test_fuzzy_match_what_i_see_variation(trigger_engine):
    """Test fuzzy matching with slight variation"""
    text = "what do i sees"  # 'sees' instead of 'see'
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.confidence >= 0.85


@pytest.mark.asyncio
async def test_fuzzy_match_case_insensitive(trigger_engine):
    """Test case-insensitive matching"""
    text = "DESCRIBE THE VIEW"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.confidence >= 0.85


@pytest.mark.asyncio
async def test_no_trigger_in_text(trigger_engine):
    """Test that non-trigger text returns None"""
    text = "This is just a normal sentence without any triggers"
    match = trigger_engine._detect_trigger(text)
    
    assert match is None


@pytest.mark.asyncio
async def test_trigger_with_prefix(trigger_engine):
    """Test trigger detection with prefix text"""
    text = "Hello, can you describe the view for me?"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "describe the view"


@pytest.mark.asyncio
async def test_trigger_with_suffix(trigger_engine):
    """Test trigger detection with suffix text"""
    text = "describe the view please thank you"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "describe the view"


@pytest.mark.asyncio
async def test_trigger_with_prefix_and_suffix(trigger_engine):
    """Test trigger detection with both prefix and suffix"""
    text = "Hey there, what do I see right now?"
    match = trigger_engine._detect_trigger(text)
    
    assert match is not None
    assert match.phrase == "what do I see"


@pytest.mark.asyncio
async def test_cooldown_reset(trigger_engine):
    """Test cooldown reset functionality"""
    # Trigger cooldown
    trigger_engine.last_trigger_time = time.time()
    assert trigger_engine._is_cooldown_active()
    
    # Reset cooldown
    trigger_engine.reset_cooldown()
    assert not trigger_engine._is_cooldown_active()
    assert trigger_engine.last_trigger_time is None


@pytest.mark.asyncio
async def test_get_stats(trigger_engine):
    """Test statistics retrieval"""
    stats = trigger_engine.get_stats()
    
    assert "running" in stats
    assert "cooldown_active" in stats
    assert "last_trigger_time" in stats
    assert "active_request_id" in stats
    assert "trigger_count" in stats
    assert stats["trigger_count"] == 8  # 4 English + 4 Chinese


@pytest.mark.asyncio
async def test_engine_start_stop(event_bus, trigger_config):
    """Test engine start and stop"""
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    
    # Initially not running
    assert not engine._running
    
    # Start engine
    await engine.start()
    assert engine._running
    
    # Stop engine
    await engine.stop()
    assert not engine._running


@pytest.mark.asyncio
async def test_engine_double_start(event_bus, trigger_config):
    """Test that double start is handled gracefully"""
    engine = QuestionTriggerEngine(event_bus, trigger_config)
    
    await engine.start()
    await engine.start()  # Should not raise error
    
    assert engine._running
    await engine.stop()
