# Property-based tests for ESP32 Audio Buffer Management
# These tests simulate the ESP32 buffer behavior in Python
import pytest
from hypothesis import given, strategies as st, settings


class ESP32AudioBuffer:
    """Python simulation of ESP32 audio buffer"""
    
    def __init__(self, buffer_size=16384, min_threshold=8192):
        self.buffer_size = buffer_size
        self.min_threshold = min_threshold
        self.buffer = bytearray(buffer_size)
        self.write_pos = 0
        self.read_pos = 0
        self.available = 0
        self.is_playing = False
    
    def write(self, data):
        """Write data to buffer"""
        written = 0
        for byte in data:
            if self.available < self.buffer_size:
                self.buffer[self.write_pos] = byte
                self.write_pos = (self.write_pos + 1) % self.buffer_size
                self.available += 1
                written += 1
            else:
                break  # Buffer full
        return written
    
    def read(self, length):
        """Read data from buffer"""
        to_read = min(length, self.available)
        data = bytearray()
        
        for _ in range(to_read):
            data.append(self.buffer[self.read_pos])
            self.read_pos = (self.read_pos + 1) % self.buffer_size
        
        self.available -= to_read
        return bytes(data)
    
    def get_available(self):
        """Get available bytes in buffer"""
        return self.available
    
    def get_space(self):
        """Get free space in buffer"""
        return self.buffer_size - self.available
    
    def needs_more_data(self):
        """Check if buffer needs more data"""
        return self.available < self.min_threshold
    
    def start_playback(self):
        """Start playback if buffer has enough data"""
        if self.available >= self.min_threshold:
            self.is_playing = True
            return True
        return False
    
    def stop_playback(self):
        """Stop playback"""
        self.is_playing = False
    
    def clear(self):
        """Clear buffer"""
        self.write_pos = 0
        self.read_pos = 0
        self.available = 0
        self.is_playing = False


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192),
    (8192, 4096),
    (32768, 16384)
])
@given(
    write_size=st.integers(min_value=100, max_value=5000),
    read_size=st.integers(min_value=100, max_value=4096)
)
@settings(max_examples=100, deadline=None)
def test_property_buffer_request_on_low_buffer(buffer_size, min_threshold, write_size, read_size):
    """
    **Property 16: Buffer request on low buffer**
    
    For any ESP32 device, when the audio buffer level falls below the
    minimum threshold, the ESP32 SHALL request more audio data from
    the backend.
    
    **Validates: Requirements 9.2**
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    # Fill buffer above threshold
    initial_data = b"\x00\x01" * (min_threshold // 2 + 1000)
    buffer.write(initial_data)
    
    # Start playback
    assert buffer.start_playback(), "Should be able to start playback with sufficient data"
    
    # Initially, should not need more data
    assert not buffer.needs_more_data(), \
        f"Should not need more data when buffer has {buffer.get_available()} bytes " \
        f"(threshold: {min_threshold})"
    
    # Read data until buffer falls below threshold
    while buffer.get_available() >= min_threshold:
        buffer.read(read_size)
    
    # Now buffer should need more data
    assert buffer.needs_more_data(), \
        f"Should need more data when buffer has {buffer.get_available()} bytes " \
        f"(threshold: {min_threshold})"
    
    # Verify available is below threshold
    assert buffer.get_available() < min_threshold, \
        "Available bytes should be below threshold"


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192),
    (8192, 4096)
])
@given(chunk_size=st.integers(min_value=512, max_value=4096))
@settings(max_examples=50, deadline=None)
def test_property_buffer_threshold_detection(buffer_size, min_threshold, chunk_size):
    """
    Test that buffer correctly detects when it crosses the threshold.
    
    Verifies that needs_more_data() returns correct values based on
    buffer level.
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    # Empty buffer should need more data
    assert buffer.needs_more_data(), \
        "Empty buffer should need more data"
    
    # Fill buffer to just below threshold
    data = b"\x00\x01" * ((min_threshold - 100) // 2)
    buffer.write(data)
    
    # Should still need more data
    assert buffer.needs_more_data(), \
        f"Buffer with {buffer.get_available()} bytes should need more data " \
        f"(threshold: {min_threshold})"
    
    # Fill buffer to just above threshold
    data = b"\x00\x01" * 200
    buffer.write(data)
    
    # Should not need more data
    assert not buffer.needs_more_data(), \
        f"Buffer with {buffer.get_available()} bytes should not need more data " \
        f"(threshold: {min_threshold})"


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192)
])
@given(
    operations=st.lists(
        st.tuples(
            st.sampled_from(['write', 'read']),
            st.integers(min_value=100, max_value=2000)
        ),
        min_size=5,
        max_size=20
    )
)
@settings(max_examples=50, deadline=None)
def test_property_buffer_state_consistency(buffer_size, min_threshold, operations):
    """
    Test that buffer state remains consistent across operations.
    
    Verifies that available count is always accurate and threshold
    detection is consistent.
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    for op, size in operations:
        if op == 'write':
            data = b"\x00\x01" * (size // 2)
            written = buffer.write(data)
            
            # Verify write didn't exceed buffer size
            assert buffer.get_available() <= buffer_size, \
                "Available should never exceed buffer size"
            
        elif op == 'read':
            before_available = buffer.get_available()
            data = buffer.read(size)
            after_available = buffer.get_available()
            
            # Verify read reduced available correctly
            assert after_available == before_available - len(data), \
                "Available count should decrease by bytes read"
        
        # Verify threshold detection is consistent
        if buffer.get_available() < min_threshold:
            assert buffer.needs_more_data(), \
                "needs_more_data() should return True when below threshold"
        else:
            assert not buffer.needs_more_data(), \
                "needs_more_data() should return False when above threshold"
        
        # Verify available + space = buffer_size
        assert buffer.get_available() + buffer.get_space() == buffer_size, \
            "Available + space should always equal buffer size"



@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192),
    (8192, 4096),
    (32768, 16384)
])
@given(initial_data_size=st.integers(min_value=100, max_value=20000))
@settings(max_examples=100, deadline=None)
def test_property_buffer_prefill_before_playback(buffer_size, min_threshold, initial_data_size):
    """
    **Property 17: Buffer pre-fill before playback**
    
    For any audio playback initiation, the ESP32 SHALL ensure the audio
    buffer contains at least the minimum threshold of data before starting
    playback.
    
    **Validates: Requirements 9.3**
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    # Write initial data
    data = b"\x00\x01" * (initial_data_size // 2)
    buffer.write(data)
    
    # Try to start playback
    playback_started = buffer.start_playback()
    
    if initial_data_size >= min_threshold:
        # Should be able to start playback
        assert playback_started, \
            f"Should be able to start playback with {buffer.get_available()} bytes " \
            f"(threshold: {min_threshold})"
        assert buffer.is_playing, \
            "Playback should be active"
    else:
        # Should not be able to start playback
        assert not playback_started, \
            f"Should not start playback with only {buffer.get_available()} bytes " \
            f"(threshold: {min_threshold})"
        assert not buffer.is_playing, \
            "Playback should not be active"


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192)
])
@given(
    chunk_sizes=st.lists(
        st.integers(min_value=100, max_value=2000),
        min_size=1,
        max_size=10
    )
)
@settings(max_examples=50, deadline=None)
def test_property_incremental_buffer_fill(buffer_size, min_threshold, chunk_sizes):
    """
    Test that playback only starts after buffer reaches threshold.
    
    Verifies that multiple small writes eventually allow playback to start.
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    total_written = 0
    playback_started = False
    
    for chunk_size in chunk_sizes:
        # Write chunk
        data = b"\x00\x01" * (chunk_size // 2)
        written = buffer.write(data)
        total_written += written
        
        # Try to start playback
        if not playback_started:
            playback_started = buffer.start_playback()
        
        # Verify playback state matches buffer level
        if buffer.get_available() >= min_threshold:
            # Should be able to start playback
            assert buffer.start_playback() or buffer.is_playing, \
                f"Should be able to start playback with {buffer.get_available()} bytes"
        else:
            # Should not be playing yet
            if not playback_started:
                assert not buffer.is_playing, \
                    f"Should not be playing with only {buffer.get_available()} bytes"



@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192),
    (8192, 4096)
])
@given(
    audio_size=st.integers(min_value=10000, max_value=30000),
    read_chunk_size=st.integers(min_value=512, max_value=4096)
)
@settings(max_examples=100, deadline=None)
def test_property_memory_cleanup_after_playback(buffer_size, min_threshold, audio_size, read_chunk_size):
    """
    **Property 18: Memory cleanup after playback**
    
    For any completed audio playback, the ESP32 SHALL release all audio
    buffers to free memory for subsequent requests.
    
    **Validates: Requirements 11.2**
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    # Fill buffer with audio data
    audio_data = b"\x00\x01" * (audio_size // 2)
    written = buffer.write(audio_data)
    
    # Start playback
    assert buffer.start_playback(), "Should be able to start playback"
    
    # Verify buffer has data
    initial_available = buffer.get_available()
    assert initial_available > 0, "Buffer should have data"
    
    # Simulate playback (read all data)
    while buffer.get_available() > 0:
        buffer.read(read_chunk_size)
    
    # Stop playback
    buffer.stop_playback()
    
    # Clear buffer (simulating memory cleanup)
    buffer.clear()
    
    # Verify buffer is completely cleared
    assert buffer.get_available() == 0, \
        "Buffer should be empty after cleanup"
    assert buffer.get_space() == buffer_size, \
        "All space should be available after cleanup"
    assert buffer.write_pos == 0, \
        "Write position should be reset"
    assert buffer.read_pos == 0, \
        "Read position should be reset"
    assert not buffer.is_playing, \
        "Playback should be stopped"
    
    # Verify buffer can be reused
    new_data = b"\x00\x01" * 5000
    written = buffer.write(new_data)
    assert written == len(new_data), \
        "Should be able to write to cleared buffer"
    assert buffer.get_available() == len(new_data), \
        "Available should match written data"


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192)
])
@given(playback_count=st.integers(min_value=2, max_value=5))
@settings(max_examples=30, deadline=None)
def test_property_multiple_playback_cycles(buffer_size, min_threshold, playback_count):
    """
    Test that buffer can handle multiple playback cycles with cleanup.
    
    Verifies that memory cleanup allows subsequent playbacks to work correctly.
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    for cycle in range(playback_count):
        # Fill buffer
        audio_data = b"\x00\x01" * 5000
        written = buffer.write(audio_data)
        
        # Start playback
        assert buffer.start_playback(), \
            f"Should be able to start playback in cycle {cycle + 1}"
        
        # Read all data
        while buffer.get_available() > 0:
            buffer.read(2048)
        
        # Stop and cleanup
        buffer.stop_playback()
        buffer.clear()
        
        # Verify cleanup
        assert buffer.get_available() == 0, \
            f"Buffer should be empty after cycle {cycle + 1}"
        assert not buffer.is_playing, \
            f"Playback should be stopped after cycle {cycle + 1}"


@pytest.mark.parametrize("buffer_size,min_threshold", [
    (16384, 8192)
])
def test_property_cleanup_releases_memory(buffer_size, min_threshold):
    """
    Test that cleanup actually releases memory.
    
    Verifies that after cleanup, the full buffer capacity is available.
    """
    buffer = ESP32AudioBuffer(buffer_size=buffer_size, min_threshold=min_threshold)
    
    # Fill buffer completely
    max_data = b"\x00\x01" * (buffer_size // 2)
    written = buffer.write(max_data)
    
    # Verify buffer is full or nearly full
    assert buffer.get_available() > buffer_size * 0.9, \
        "Buffer should be nearly full"
    
    # Clear buffer
    buffer.clear()
    
    # Verify all memory is released
    assert buffer.get_space() == buffer_size, \
        "All buffer space should be available after cleanup"
    
    # Verify we can fill buffer again
    written2 = buffer.write(max_data)
    assert written2 == written, \
        "Should be able to write same amount after cleanup"
