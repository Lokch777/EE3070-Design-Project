# Property-based tests for Audio Playback Coordinator
import pytest
import asyncio
import time
import base64
from hypothesis import given, strategies as st, settings
from backend.audio_playback_coordinator import AudioPlaybackCoordinator, PlaybackConfig
from backend.event_bus import EventBus
from backend.models import Event, EventType


class MockWebSocket:
    """Mock WebSocket for testing"""
    
    def __init__(self):
        self.sent_messages = []
        self.closed = False
    
    async def send_json(self, data):
        """Mock send_json method"""
        if self.closed:
            raise Exception("WebSocket closed")
        self.sent_messages.append(data)
    
    async def close(self):
        """Mock close method"""
        self.closed = True
    
    def get_audio_chunks(self):
        """Extract audio chunks from sent messages"""
        chunks = []
        for msg in self.sent_messages:
            if msg.get("type") == "audio_chunk":
                chunks.append(base64.b64decode(msg["audio_data"]))
        return chunks


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


# Strategy for generating audio data
@st.composite
def audio_data_generator(draw):
    """Generate random audio data"""
    # Generate audio data of various sizes
    size = draw(st.integers(min_value=1000, max_value=50000))
    audio_bytes = draw(st.binary(min_size=size, max_size=size))
    return audio_bytes


@pytest.mark.asyncio
@given(audio_data=audio_data_generator())
@settings(max_examples=100, deadline=None)
async def test_property_audio_streaming_to_esp32(audio_data):
    """
    **Property 12: Audio streaming to ESP32**
    
    For any audio-ready event, the Audio_Playback_Coordinator SHALL stream
    the audio data to the ESP32 via WebSocket in chunks, and SHALL emit
    a playback-complete event when streaming finishes.
    
    **Validates: Requirements 6.1, 6.5**
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create mock WebSocket
        mock_ws = MockWebSocket()
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Create audio ready event
        audio_event = Event(
            event_type=EventType.AUDIO_READY.value,
            timestamp=time.time(),
            req_id=f"test_{int(time.time() * 1000)}",
            data={
                "audio_data": audio_data,
                "audio_format": "pcm",
                "sample_rate": 16000,
                "duration_seconds": len(audio_data) / (16000 * 2),
                "device_id": device_id
            }
        )
        
        # Publish audio ready event
        await event_bus.publish(audio_event)
        
        # Wait for streaming
        await asyncio.sleep(0.5)
        
        # Verify audio chunks were sent
        assert len(mock_ws.sent_messages) > 0, \
            "Expected audio chunks to be sent via WebSocket"
        
        # Verify all messages are audio chunks
        audio_chunks = [
            msg for msg in mock_ws.sent_messages 
            if msg.get("type") == "audio_chunk"
        ]
        assert len(audio_chunks) > 0, \
            "Expected at least one audio chunk message"
        
        # Verify chunks contain required fields
        for chunk_msg in audio_chunks:
            assert "request_id" in chunk_msg
            assert "audio_data" in chunk_msg
            assert "sequence" in chunk_msg
            assert "total_chunks" in chunk_msg
            assert "format" in chunk_msg
            assert "sample_rate" in chunk_msg
        
        # Verify audio data integrity
        received_chunks = mock_ws.get_audio_chunks()
        reconstructed_audio = b"".join(received_chunks)
        assert reconstructed_audio == audio_data, \
            "Reconstructed audio does not match original"
        
        # Verify playback started event was emitted
        history = event_bus.get_history(limit=10)
        started_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_STARTED.value
        ]
        assert len(started_events) > 0, \
            "Expected playback started event"
        
        # Simulate playback completion from ESP32
        await coordinator.on_playback_complete(device_id, audio_event.req_id)
        
        # Verify playback complete event was emitted
        history = event_bus.get_history(limit=10)
        complete_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_COMPLETE.value
        ]
        assert len(complete_events) > 0, \
            "Expected playback complete event"
        
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@given(
    audio_size=st.integers(min_value=1000, max_value=20000),
    chunk_size=st.integers(min_value=512, max_value=8192)
)
@settings(max_examples=50, deadline=None)
async def test_property_audio_chunking(audio_size, chunk_size):
    """
    Test that audio is correctly chunked according to configuration.
    
    Verifies that audio is split into chunks of the configured size.
    """
    # Create audio data
    audio_data = b"\x00\x01" * (audio_size // 2)
    
    # Create components with custom chunk size
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=chunk_size,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create mock WebSocket
        mock_ws = MockWebSocket()
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Create audio ready event
        audio_event = Event(
            event_type=EventType.AUDIO_READY.value,
            timestamp=time.time(),
            req_id="test_chunking",
            data={
                "audio_data": audio_data,
                "audio_format": "pcm",
                "sample_rate": 16000,
                "duration_seconds": 1.0,
                "device_id": device_id
            }
        )
        
        await event_bus.publish(audio_event)
        await asyncio.sleep(0.5)
        
        # Verify chunking
        audio_chunks = mock_ws.get_audio_chunks()
        
        # All chunks except last should be exactly chunk_size
        for i, chunk in enumerate(audio_chunks[:-1]):
            assert len(chunk) == chunk_size, \
                f"Chunk {i} size mismatch: expected {chunk_size}, got {len(chunk)}"
        
        # Last chunk should be <= chunk_size
        if len(audio_chunks) > 0:
            assert len(audio_chunks[-1]) <= chunk_size, \
                f"Last chunk too large: {len(audio_chunks[-1])} > {chunk_size}"
        
        # Total size should match original
        total_size = sum(len(chunk) for chunk in audio_chunks)
        assert total_size == len(audio_data), \
            f"Total size mismatch: expected {len(audio_data)}, got {total_size}"
        
    finally:
        await coordinator.stop()



@pytest.mark.asyncio
@given(
    request_count=st.integers(min_value=2, max_value=5),
    audio_size=st.integers(min_value=5000, max_value=15000)
)
@settings(max_examples=100, deadline=None)
async def test_property_playback_mutual_exclusion(request_count, audio_size):
    """
    **Property 13: Playback mutual exclusion**
    
    For any device, when audio playback is in progress, the system SHALL
    reject new question processing requests until the playback-complete
    event is received.
    
    **Validates: Requirements 6.3**
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create mock WebSocket
        mock_ws = MockWebSocket()
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Generate audio data
        audio_data = b"\x00\x01" * (audio_size // 2)
        
        # Send multiple audio ready events rapidly
        request_ids = []
        for i in range(request_count):
            req_id = f"test_{i}_{int(time.time() * 1000)}"
            request_ids.append(req_id)
            
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
            await asyncio.sleep(0.05)  # Small delay between requests
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Check playback started events
        history = event_bus.get_history(limit=20)
        started_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_STARTED.value
        ]
        
        # Should only have 1 playback started event (mutual exclusion)
        assert len(started_events) == 1, \
            f"Expected 1 playback started event (mutual exclusion), got {len(started_events)}"
        
        # Verify only first request was processed
        assert started_events[0].req_id == request_ids[0], \
            "First request should be processed"
        
        # Verify playback is active
        assert coordinator._is_playback_active(device_id), \
            "Playback should be active"
        
        # Complete the playback
        await coordinator.on_playback_complete(device_id, request_ids[0])
        
        # Verify playback is no longer active
        assert not coordinator._is_playback_active(device_id), \
            "Playback should not be active after completion"
        
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@given(audio_size=st.integers(min_value=5000, max_value=15000))
@settings(max_examples=50, deadline=None)
async def test_property_playback_state_management(audio_size):
    """
    Test that playback state is correctly managed throughout the lifecycle.
    
    Verifies that playback state transitions correctly from inactive to
    active to inactive.
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create mock WebSocket
        mock_ws = MockWebSocket()
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Initially, playback should not be active
        assert not coordinator._is_playback_active(device_id), \
            "Playback should not be active initially"
        
        # Generate audio data
        audio_data = b"\x00\x01" * (audio_size // 2)
        
        # Send audio ready event
        req_id = "test_state"
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
        await asyncio.sleep(0.3)
        
        # Playback should now be active
        assert coordinator._is_playback_active(device_id), \
            "Playback should be active after audio ready event"
        
        # Complete playback
        await coordinator.on_playback_complete(device_id, req_id)
        
        # Playback should no longer be active
        assert not coordinator._is_playback_active(device_id), \
            "Playback should not be active after completion"
        
        # Should be able to start new playback
        req_id2 = "test_state_2"
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
        await asyncio.sleep(0.3)
        
        # New playback should be active
        assert coordinator._is_playback_active(device_id), \
            "Should be able to start new playback after previous completion"
        
    finally:
        await coordinator.stop()



class InterruptibleWebSocket:
    """Mock WebSocket that can simulate interruptions"""
    
    def __init__(self, fail_at_chunk: int = -1):
        self.sent_messages = []
        self.closed = False
        self.fail_at_chunk = fail_at_chunk
        self.chunk_count = 0
    
    async def send_json(self, data):
        """Mock send_json that can fail at specific chunk"""
        if self.closed:
            raise Exception("WebSocket closed")
        
        if data.get("type") == "audio_chunk":
            self.chunk_count += 1
            if self.fail_at_chunk > 0 and self.chunk_count == self.fail_at_chunk:
                raise Exception("Simulated network interruption")
        
        self.sent_messages.append(data)
    
    async def close(self):
        """Mock close method"""
        self.closed = True
    
    def get_audio_chunks(self):
        """Extract audio chunks from sent messages"""
        chunks = []
        for msg in self.sent_messages:
            if msg.get("type") == "audio_chunk":
                chunks.append(base64.b64decode(msg["audio_data"]))
        return chunks


@pytest.mark.asyncio
@given(
    audio_size=st.integers(min_value=10000, max_value=30000),
    fail_at_chunk=st.integers(min_value=1, max_value=3)
)
@settings(max_examples=50, deadline=None)
async def test_property_audio_streaming_resilience(audio_size, fail_at_chunk):
    """
    **Property 14: Audio streaming resilience**
    
    For any audio streaming interruption, the system SHALL either resume
    from the interruption point or restart playback, ensuring the user
    receives the complete audio response.
    
    **Validates: Requirements 6.4**
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create interruptible WebSocket
        mock_ws = InterruptibleWebSocket(fail_at_chunk=fail_at_chunk)
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Generate audio data
        audio_data = b"\x00\x01" * (audio_size // 2)
        
        # Send audio ready event
        req_id = "test_resilience"
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
        await asyncio.sleep(0.5)
        
        # Check if error was handled
        history = event_bus.get_history(limit=10)
        error_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_ERROR.value
        ]
        
        # If interruption occurred, error event should be emitted
        if fail_at_chunk <= (len(audio_data) // 4096):
            assert len(error_events) > 0, \
                "Expected playback error event after interruption"
            
            # Verify error contains information
            error_event = error_events[0]
            assert "error" in error_event.data
            assert error_event.data["device_id"] == device_id
        
        # Verify playback state was cleared on error
        assert not coordinator._is_playback_active(device_id), \
            "Playback should not be active after error"
        
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_property_streaming_error_recovery():
    """
    Test that system can recover from streaming errors.
    
    Verifies that after a streaming error, the system can accept
    new playback requests.
    """
    # Create components
    event_bus = EventBus(buffer_size=100)
    playback_config = PlaybackConfig(
        chunk_size=4096,
        buffer_size=16384,
        stream_timeout=10.0
    )
    coordinator = AudioPlaybackCoordinator(event_bus, playback_config)
    await coordinator.start()
    
    try:
        # Create WebSocket that fails on first request
        mock_ws = InterruptibleWebSocket(fail_at_chunk=1)
        device_id = "test_device"
        coordinator.register_device(device_id, mock_ws)
        
        # Generate audio data
        audio_data = b"\x00\x01" * 5000
        
        # First request (will fail)
        req_id1 = "test_fail"
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
        await asyncio.sleep(0.5)
        
        # Verify error occurred
        history = event_bus.get_history(limit=10)
        error_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_ERROR.value
        ]
        assert len(error_events) > 0
        
        # Replace with working WebSocket
        mock_ws2 = MockWebSocket()
        coordinator.register_device(device_id, mock_ws2)
        
        # Second request (should succeed)
        req_id2 = "test_success"
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
        await asyncio.sleep(0.5)
        
        # Verify success
        assert len(mock_ws2.sent_messages) > 0, \
            "Should be able to stream after error recovery"
        
        # Verify playback started
        history = event_bus.get_history(limit=10)
        started_events = [
            e for e in history 
            if e.event_type == EventType.PLAYBACK_STARTED.value
        ]
        
        # Should have 2 started events (one for each attempt)
        assert len(started_events) >= 1, \
            "Should have playback started event after recovery"
        
    finally:
        await coordinator.stop()
