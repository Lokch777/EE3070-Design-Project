# Unit tests for Audio Playback Coordinator
import pytest
import asyncio
import time
from backend.audio_playback_coordinator import AudioPlaybackCoordinator, PlaybackConfig
from backend.event_bus import EventBus
from backend.models import Event, EventType
from tests.test_audio_playback_properties import MockWebSocket


@pytest.fixture
def event_bus():
    """Create event bus for testing"""
    return EventBus(buffer_size=100)


@pytest.fixture
def playback_config():
    """Create playback configuration for testing"""
    return PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )


@pytest.fixture
async def playback_coordinator(event_bus, playback_config):
    """Create and start playback coordinator for testing"""
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    yield coordinator
    await coordinator.stop()


@pytest.mark.asyncio
async def test_concurrent_request_rejection(playback_coordinator, event_bus):
    """Test that concurrent requests are rejected"""
    # Register device
    mock_ws = MockWebSocket()
    device_id = "test_device"
    playback_coordinator.register_device(device_id, mock_ws)
    
    # Send first audio ready event
    audio_data = b"\x00\x01" * 5000
    req_id1 = "test_1"
    audio_event1 = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id1,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": device_id
        }
    )
    
    await event_bus.publish(audio_event1)
    await asyncio.sleep(0.2)
    
    # Verify first request is active
    assert playback_coordinator._is_playback_active(device_id)
    
    # Send second audio ready event (should be rejected)
    req_id2 = "test_2"
    audio_event2 = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id2,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": device_id
        }
    )
    
    await event_bus.publish(audio_event2)
    await asyncio.sleep(0.2)
    
    # Check events
    history = event_bus.get_history(limit=10)
    started_events = [
        e for e in history 
        if e.event_type == EventType.PLAYBACK_STARTED.value
    ]
    
    # Should only have 1 started event
    assert len(started_events) == 1
    assert started_events[0].req_id == req_id1


@pytest.mark.asyncio
async def test_playback_completion_handling(playback_coordinator, event_bus):
    """Test playback completion handling"""
    # Register device
    mock_ws = MockWebSocket()
    device_id = "test_device"
    playback_coordinator.register_device(device_id, mock_ws)
    
    # Send audio ready event
    audio_data = b"\x00\x01" * 5000
    req_id = "test_complete"
    audio_event = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": device_id
        }
    )
    
    await event_bus.publish(audio_event)
    await asyncio.sleep(0.2)
    
    # Verify playback is active
    assert playback_coordinator._is_playback_active(device_id)
    
    # Complete playback
    await playback_coordinator.on_playback_complete(device_id, req_id)
    
    # Verify playback is no longer active
    assert not playback_coordinator._is_playback_active(device_id)
    
    # Verify playback complete event was emitted
    history = event_bus.get_history(limit=10)
    complete_events = [
        e for e in history 
        if e.event_type == EventType.PLAYBACK_COMPLETE.value
    ]
    
    assert len(complete_events) > 0
    assert complete_events[0].req_id == req_id


@pytest.mark.asyncio
async def test_device_not_connected_error(playback_coordinator, event_bus):
    """Test error when device is not connected"""
    # Send audio ready event for non-existent device
    audio_data = b"\x00\x01" * 5000
    req_id = "test_no_device"
    audio_event = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": "non_existent_device"
        }
    )
    
    await event_bus.publish(audio_event)
    await asyncio.sleep(0.2)
    
    # Check for error event
    history = event_bus.get_history(limit=10)
    error_events = [
        e for e in history 
        if e.event_type == EventType.PLAYBACK_ERROR.value
    ]
    
    assert len(error_events) > 0
    assert "not connected" in error_events[0].data["error"].lower()


@pytest.mark.asyncio
async def test_device_registration(playback_coordinator):
    """Test device registration and unregistration"""
    mock_ws = MockWebSocket()
    device_id = "test_device"
    
    # Register device
    playback_coordinator.register_device(device_id, mock_ws)
    assert device_id in playback_coordinator.device_connections
    
    # Unregister device
    playback_coordinator.unregister_device(device_id)
    assert device_id not in playback_coordinator.device_connections


@pytest.mark.asyncio
async def test_coordinator_start_stop(event_bus, playback_config):
    """Test coordinator start and stop"""
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    
    # Initially not running
    assert not coordinator._running
    
    # Start coordinator
    await coordinator.start()
    assert coordinator._running
    
    # Stop coordinator
    await coordinator.stop()
    assert not coordinator._running


@pytest.mark.asyncio
async def test_coordinator_double_start(event_bus, playback_config):
    """Test that double start is handled gracefully"""
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    
    await coordinator.start()
    await coordinator.start()  # Should not raise error
    
    assert coordinator._running
    await coordinator.stop()


@pytest.mark.asyncio
async def test_get_stats(playback_coordinator):
    """Test statistics retrieval"""
    # Register device
    mock_ws = MockWebSocket()
    device_id = "test_device"
    playback_coordinator.register_device(device_id, mock_ws)
    
    stats = playback_coordinator.get_stats()
    
    assert "running" in stats
    assert "active_playback_count" in stats
    assert "connected_devices" in stats
    assert "active_playback" in stats
    assert stats["connected_devices"] == 1


@pytest.mark.asyncio
async def test_multiple_devices(playback_coordinator, event_bus):
    """Test handling multiple devices independently"""
    # Register two devices
    mock_ws1 = MockWebSocket()
    mock_ws2 = MockWebSocket()
    device_id1 = "device_1"
    device_id2 = "device_2"
    
    playback_coordinator.register_device(device_id1, mock_ws1)
    playback_coordinator.register_device(device_id2, mock_ws2)
    
    # Send audio to device 1
    audio_data = b"\x00\x01" * 5000
    req_id1 = "test_dev1"
    audio_event1 = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id1,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": device_id1
        }
    )
    
    await event_bus.publish(audio_event1)
    await asyncio.sleep(0.2)
    
    # Verify device 1 is playing
    assert playback_coordinator._is_playback_active(device_id1)
    assert not playback_coordinator._is_playback_active(device_id2)
    
    # Send audio to device 2 (should work independently)
    req_id2 = "test_dev2"
    audio_event2 = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id2,
        data={
            "audio_data": audio_data,
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 1.0,
            "device_id": device_id2
        }
    )
    
    await event_bus.publish(audio_event2)
    await asyncio.sleep(0.2)
    
    # Both devices should be playing
    assert playback_coordinator._is_playback_active(device_id1)
    assert playback_coordinator._is_playback_active(device_id2)
    
    # Verify both received audio
    assert len(mock_ws1.sent_messages) > 0
    assert len(mock_ws2.sent_messages) > 0


@pytest.mark.asyncio
async def test_empty_audio_data(playback_coordinator, event_bus):
    """Test handling of empty audio data"""
    # Register device
    mock_ws = MockWebSocket()
    device_id = "test_device"
    playback_coordinator.register_device(device_id, mock_ws)
    
    # Send empty audio
    req_id = "test_empty"
    audio_event = Event(
        event_type=EventType.AUDIO_READY.value,
        timestamp=time.time(),
        req_id=req_id,
        data={
            "audio_data": b"",
            "audio_format": "pcm",
            "sample_rate": 16000,
            "duration_seconds": 0.0,
            "device_id": device_id
        }
    )
    
    await event_bus.publish(audio_event)
    await asyncio.sleep(0.2)
    
    # Should handle gracefully (no chunks sent)
    audio_chunks = [
        msg for msg in mock_ws.sent_messages 
        if msg.get("type") == "audio_chunk"
    ]
    assert len(audio_chunks) == 0
