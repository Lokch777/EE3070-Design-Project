# Unit tests for TTS Adapter
import pytest
import asyncio
import time
from backend.tts_adapter import TTSAdapter, AudioData
from backend.tts_client import TTSClient, TTSConfig, MockTTSClient, TTSError
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


@pytest.mark.asyncio
async def test_tts_service_failure(event_bus, tts_config):
    """Test TTS service failure scenario"""
    # Create client that always fails
    class AlwaysFailClient:
        def __init__(self, config):
            self.config = config
        async def connect(self):
            pass
        async def disconnect(self):
            pass
        async def convert_to_speech(self, text: str) -> bytes:
            raise TTSError("Service unavailable")
    
    failing_client = AlwaysFailClient(tts_config)
    adapter = TTSAdapter(event_bus, failing_client, tts_config)
    await adapter.start()
    
    try:
        # Send vision response
        vision_event = Event(
            event_type=EventType.VISION_RESULT.value,
            timestamp=time.time(),
            req_id="test_failure",
            data={
                "description": "Test description",
                "device_id": "test_device"
            }
        )
        
        await event_bus.publish(vision_event)
        await asyncio.sleep(1.0)
        
        # Check for error event
        history = event_bus.get_history(limit=10)
        error_events = [
            e for e in history 
            if e.event_type == EventType.TTS_ERROR.value
        ]
        
        assert len(error_events) > 0, "Expected TTS error event"
        assert "error" in error_events[0].data
        
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_chinese_language_support(tts_adapter, event_bus):
    """Test Chinese language support"""
    # Send Chinese text
    vision_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id="test_chinese",
        data={
            "description": "这是一个测试描述",
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
    
    assert len(audio_events) > 0, "Expected audio event for Chinese text"
    assert len(audio_events[0].data["audio_data"]) > 0


@pytest.mark.asyncio
async def test_empty_description_handling(tts_adapter, event_bus):
    """Test handling of empty description"""
    # Send empty description
    vision_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id="test_empty",
        data={
            "description": "",
            "device_id": "test_device"
        }
    )
    
    await event_bus.publish(vision_event)
    await asyncio.sleep(0.5)
    
    # Should not produce audio event for empty description
    history = event_bus.get_history(limit=10)
    audio_events = [
        e for e in history 
        if e.event_type == EventType.AUDIO_READY.value
    ]
    
    assert len(audio_events) == 0, "Should not produce audio for empty description"


@pytest.mark.asyncio
async def test_adapter_start_stop(event_bus, mock_tts_client, tts_config):
    """Test adapter start and stop"""
    adapter = TTSAdapter(event_bus, mock_tts_client, tts_config)
    
    # Initially not running
    assert not adapter._running
    
    # Start adapter
    await adapter.start()
    assert adapter._running
    
    # Stop adapter
    await adapter.stop()
    assert not adapter._running


@pytest.mark.asyncio
async def test_adapter_double_start(event_bus, mock_tts_client, tts_config):
    """Test that double start is handled gracefully"""
    adapter = TTSAdapter(event_bus, mock_tts_client, tts_config)
    
    await adapter.start()
    await adapter.start()  # Should not raise error
    
    assert adapter._running
    await adapter.stop()


@pytest.mark.asyncio
async def test_get_stats(tts_adapter):
    """Test statistics retrieval"""
    stats = tts_adapter.get_stats()
    
    assert "running" in stats
    assert "config" in stats
    assert stats["config"]["voice"] == "zhifeng_emo"
    assert stats["config"]["language"] == "zh-CN"
    assert stats["config"]["audio_format"] == "pcm"
    assert stats["config"]["sample_rate"] == 16000


@pytest.mark.asyncio
async def test_audio_data_structure(tts_adapter, event_bus):
    """Test that audio data structure is correct"""
    vision_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id="test_structure",
        data={
            "description": "Test description",
            "device_id": "test_device"
        }
    )
    
    await event_bus.publish(vision_event)
    await asyncio.sleep(1.0)
    
    # Check audio event structure
    history = event_bus.get_history(limit=10)
    audio_events = [
        e for e in history 
        if e.event_type == EventType.AUDIO_READY.value
    ]
    
    assert len(audio_events) > 0
    audio_event = audio_events[0]
    
    # Verify all required fields
    assert "audio_data" in audio_event.data
    assert "audio_format" in audio_event.data
    assert "sample_rate" in audio_event.data
    assert "duration_seconds" in audio_event.data
    assert "device_id" in audio_event.data
    
    # Verify types
    assert isinstance(audio_event.data["audio_data"], bytes)
    assert isinstance(audio_event.data["audio_format"], str)
    assert isinstance(audio_event.data["sample_rate"], int)
    assert isinstance(audio_event.data["duration_seconds"], float)
    assert isinstance(audio_event.data["device_id"], str)


@pytest.mark.asyncio
async def test_long_description(tts_adapter, event_bus):
    """Test handling of long descriptions"""
    long_text = "This is a very long description. " * 50
    
    vision_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id="test_long",
        data={
            "description": long_text,
            "device_id": "test_device"
        }
    )
    
    await event_bus.publish(vision_event)
    await asyncio.sleep(1.0)
    
    # Should still produce audio
    history = event_bus.get_history(limit=10)
    audio_events = [
        e for e in history 
        if e.event_type == EventType.AUDIO_READY.value
    ]
    
    assert len(audio_events) > 0
    assert len(audio_events[0].data["audio_data"]) > 0


@pytest.mark.asyncio
async def test_special_characters_in_description(tts_adapter, event_bus):
    """Test handling of special characters"""
    text_with_special = "Test! @#$% description with 123 numbers & symbols"
    
    vision_event = Event(
        event_type=EventType.VISION_RESULT.value,
        timestamp=time.time(),
        req_id="test_special",
        data={
            "description": text_with_special,
            "device_id": "test_device"
        }
    )
    
    await event_bus.publish(vision_event)
    await asyncio.sleep(1.0)
    
    # Should handle special characters
    history = event_bus.get_history(limit=10)
    audio_events = [
        e for e in history 
        if e.event_type == EventType.AUDIO_READY.value
    ]
    
    assert len(audio_events) > 0
