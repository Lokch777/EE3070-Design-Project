# Property-based tests for TTS Adapter
import pytest
import asyncio
import time
from hypothesis import given, strategies as st, settings
from backend.tts_adapter import TTSAdapter, AudioData
from backend.tts_client import TTSClient, TTSConfig, MockTTSClient
from backend.event_bus import EventBus
from backend.models import Event, EventType


@pytest.fixture
def event_bus():
    """Create event bus for testing"""
    return EventBus(buffer_size=100)


@pytest.fixture
def tts_config():
    """Create TTS configuration for testing"""
    return TTSConfig(
        api_key="test_api_key",
        endpoint="wss://test.example.com/tts",
        voice="zhifeng_emo",
        language="zh-CN",
        speed=1.0,
        pitch=1.0,
        audio_format="pcm",
        sample_rate=16000,
        timeout_seconds=5.0
    )


@pytest.fixture
def mock_tts_client(tts_config):
    """Create mock TTS client for testing"""
    return MockTTSClient(tts_config)


@pytest.fixture
async def tts_adapter(event_bus, mock_tts_client, tts_config):
    """Create and start TTS adapter for testing"""
    adapter = TTSAdapter(event_bus, mock_tts_client, tts_config)
    await adapter.start()
    yield adapter
    await adapter.stop()


# Strategy for generating text descriptions
@st.composite
def text_description(draw):
    """Generate random text descriptions"""
    # Mix of English and Chinese characters
    text = draw(st.text(
        min_size=10,
        max_size=200,
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs', 'Lo')
        )
    ))
    return text.strip() or "Default description"


@pytest.mark.asyncio
@given(description=text_description())
@settings(max_examples=100, deadline=None)
async def test_property_tts_conversion_pipeline(description):
    """
    **Property 10: TTS conversion pipeline**
    
    For any text description from the vision model, the TTS_Adapter SHALL
    convert the text to audio in the configured format (PCM16 at 16kHz or MP3),
    and SHALL emit an audio-ready event containing the audio data.
    
    **Validates: Requirements 5.1, 5.3, 5.5**
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    tts_config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        voice="zhifeng_emo",
        language="zh-CN",
        audio_format="pcm",
        sample_rate=16000,
        timeout_seconds=5.0
    )
    mock_client = MockTTSClient(tts_config)
    adapter = TTSAdapter(event_bus, mock_client, tts_config)
    await adapter.start()
    
    try:
        # Create vision response event
        vision_event = Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id=f"test_{int(time.time() * 1000)}",
            data={
                "description": description,
                "device_id": "test_device",
                "confidence": 0.95
            }
        )
        
        # Publish vision response
        await event_bus.publish(vision_event)
        
        # Wait for TTS processing
        await asyncio.sleep(1.0)
        
        # Check that audio ready event was emitted
        history = event_bus.get_history(limit=10)
        audio_events = [
            e for e in history 
            if e.event_type == EventType.AUDIO_READY.value
        ]
        
        # Verify audio ready event was emitted
        assert len(audio_events) > 0, \
            f"Expected audio ready event for description: {description[:50]}..."
        
        # Verify audio data is present
        audio_event = audio_events[0]
        assert "audio_data" in audio_event.data, \
            "Audio data missing from event"
        assert isinstance(audio_event.data["audio_data"], bytes), \
            "Audio data should be bytes"
        assert len(audio_event.data["audio_data"]) > 0, \
            "Audio data should not be empty"
        
        # Verify audio format
        assert audio_event.data["audio_format"] == "pcm", \
            f"Expected PCM format, got {audio_event.data['audio_format']}"
        assert audio_event.data["sample_rate"] == 16000, \
            f"Expected 16kHz sample rate, got {audio_event.data['sample_rate']}"
        
        # Verify duration is calculated
        assert "duration_seconds" in audio_event.data, \
            "Duration missing from audio event"
        assert audio_event.data["duration_seconds"] > 0, \
            "Duration should be positive"
        
        # Verify device ID is preserved
        assert audio_event.data["device_id"] == "test_device", \
            "Device ID not preserved"
        
    finally:
        await adapter.stop()


@pytest.mark.asyncio
@given(
    description=text_description(),
    sample_rate=st.sampled_from([8000, 16000, 24000, 48000])
)
@settings(max_examples=50, deadline=None)
async def test_property_tts_audio_format_compliance(description, sample_rate):
    """
    Test that TTS adapter produces audio in the configured format.
    
    Verifies that audio format and sample rate match configuration.
    """
    # Create components with custom sample rate
    event_bus = EventBus(buffer_size=100)
    tts_config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        audio_format="pcm",
        sample_rate=sample_rate,
        timeout_seconds=5.0
    )
    mock_client = MockTTSClient(tts_config)
    adapter = TTSAdapter(event_bus, mock_client, tts_config)
    await adapter.start()
    
    try:
        # Create vision response event
        vision_event = Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id="test_format",
            data={
                "description": description,
                "device_id": "test_device"
            }
        )
        
        await event_bus.publish(vision_event)
        await asyncio.sleep(1.0)
        
        # Check audio event
        history = event_bus.get_history(limit=10)
        audio_events = [
            e for e in history 
            if e.event_type == EventType.AUDIO_READY.value
        ]
        
        assert len(audio_events) > 0
        audio_event = audio_events[0]
        
        # Verify format compliance
        assert audio_event.data["audio_format"] == "pcm"
        assert audio_event.data["sample_rate"] == sample_rate
        
        # Verify audio data size is consistent with sample rate
        audio_bytes = audio_event.data["audio_data"]
        duration = audio_event.data["duration_seconds"]
        expected_size = int(sample_rate * duration * 2)  # 2 bytes per sample
        
        assert len(audio_bytes) == expected_size, \
            f"Audio size mismatch: expected {expected_size}, got {len(audio_bytes)}"
        
    finally:
        await adapter.stop()


@pytest.mark.asyncio
@given(descriptions=st.lists(text_description(), min_size=1, max_size=5))
@settings(max_examples=30, deadline=None)
async def test_property_tts_multiple_conversions(descriptions):
    """
    Test that TTS adapter handles multiple conversions correctly.
    
    Verifies that each description produces a separate audio event.
    """
    event_bus = EventBus(buffer_size=100)
    tts_config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        audio_format="pcm",
        sample_rate=16000,
        timeout_seconds=5.0
    )
    mock_client = MockTTSClient(tts_config)
    adapter = TTSAdapter(event_bus, mock_client, tts_config)
    await adapter.start()
    
    try:
        # Send multiple vision responses
        for i, description in enumerate(descriptions):
            vision_event = Event(
                event_type=EventType.VISION_RESULT.value,
                timestamp=time.time(),
                req_id=f"test_{i}",
                data={
                    "description": description,
                    "device_id": "test_device"
                }
            )
            await event_bus.publish(vision_event)
            await asyncio.sleep(0.2)
        
        # Wait for all processing
        await asyncio.sleep(1.0)
        
        # Check audio events
        history = event_bus.get_history(limit=20)
        audio_events = [
            e for e in history 
            if e.event_type == EventType.AUDIO_READY.value
        ]
        
        # Verify one audio event per description
        assert len(audio_events) == len(descriptions), \
            f"Expected {len(descriptions)} audio events, got {len(audio_events)}"
        
        # Verify all have audio data
        for audio_event in audio_events:
            assert "audio_data" in audio_event.data
            assert len(audio_event.data["audio_data"]) > 0
        
    finally:
        await adapter.stop()



class FailingTTSClient:
    """Mock TTS client that fails a specified number of times"""
    
    def __init__(self, config: TTSConfig, fail_count: int = 1):
        self.config = config
        self.fail_count = fail_count
        self.attempt_count = 0
    
    async def connect(self):
        pass
    
    async def disconnect(self):
        pass
    
    async def convert_to_speech(self, text: str) -> bytes:
        """Fail for first N attempts, then succeed"""
        self.attempt_count += 1
        
        if self.attempt_count <= self.fail_count:
            from backend.tts_client import TTSError
            raise TTSError(f"Simulated failure (attempt {self.attempt_count})")
        
        # Success after failures
        await asyncio.sleep(0.1)
        sample_count = self.config.sample_rate * 1
        return b"\x00\x00" * sample_count


@pytest.mark.asyncio
@given(
    description=text_description(),
    fail_count=st.integers(min_value=0, max_value=1)
)
@settings(max_examples=50, deadline=None)
async def test_property_tts_retry_logic(description, fail_count):
    """
    **Property 11: TTS retry logic**
    
    For any TTS conversion failure, the system SHALL retry once,
    and if both attempts fail, SHALL emit a TTS error event.
    
    **Validates: Requirements 5.4**
    """
    # Create components with failing client
    event_bus = EventBus(buffer_size=100)
    tts_config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        audio_format="pcm",
        sample_rate=16000,
        timeout_seconds=2  # Allow 1 retry
    )
    failing_client = FailingTTSClient(tts_config, fail_count=fail_count)
    adapter = TTSAdapter(event_bus, failing_client, tts_config)
    await adapter.start()
    
    try:
        # Create vision response event
        vision_event = Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id="test_retry",
            data={
                "description": description,
                "device_id": "test_device"
            }
        )
        
        await event_bus.publish(vision_event)
        await asyncio.sleep(2.0)  # Wait for retries
        
        # Check events
        history = event_bus.get_history(limit=10)
        audio_events = [
            e for e in history 
            if e.event_type == EventType.AUDIO_READY.value
        ]
        error_events = [
            e for e in history 
            if e.event_type == EventType.TTS_ERROR.value
        ]
        
        if fail_count == 0:
            # Should succeed on first attempt
            assert len(audio_events) > 0, \
                "Expected audio event when no failures"
            assert len(error_events) == 0, \
                "Should not have error event on success"
            assert failing_client.attempt_count == 1
            
        elif fail_count == 1:
            # Should succeed on retry (second attempt)
            assert len(audio_events) > 0, \
                "Expected audio event after retry"
            assert len(error_events) == 0, \
                "Should not have error event after successful retry"
            assert failing_client.attempt_count == 2, \
                "Should have retried once"
        
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_property_tts_retry_exhaustion():
    """
    Test that TTS adapter emits error after all retries are exhausted.
    
    Verifies that error event is emitted when retries fail.
    """
    # Create components with client that always fails
    event_bus = EventBus(buffer_size=100)
    tts_config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        audio_format="pcm",
        sample_rate=16000,
        timeout_seconds=2  # Allow 1 retry
    )
    failing_client = FailingTTSClient(tts_config, fail_count=10)  # Always fail
    adapter = TTSAdapter(event_bus, failing_client, tts_config)
    await adapter.start()
    
    try:
        # Create vision response event
        vision_event = Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id="test_exhaustion",
            data={
                "description": "Test description",
                "device_id": "test_device"
            }
        )
        
        await event_bus.publish(vision_event)
        await asyncio.sleep(3.0)  # Wait for all retries
        
        # Check events
        history = event_bus.get_history(limit=10)
        audio_events = [
            e for e in history 
            if e.event_type == EventType.AUDIO_READY.value
        ]
        error_events = [
            e for e in history 
            if e.event_type == EventType.TTS_ERROR.value
        ]
        
        # Should have error event, no audio event
        assert len(error_events) > 0, \
            "Expected TTS error event after retry exhaustion"
        assert len(audio_events) == 0, \
            "Should not have audio event when all retries fail"
        
        # Verify error event contains error information
        error_event = error_events[0]
        assert "error" in error_event.data
        assert "error_type" in error_event.data
        
    finally:
        await adapter.stop()
