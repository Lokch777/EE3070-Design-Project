# Unit tests for TTS Client
import pytest
import asyncio
from backend.tts_client import TTSClient, TTSConfig, TTSError, MockTTSClient


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


@pytest.mark.asyncio
async def test_mock_tts_client_connect(mock_tts_client):
    """Test mock TTS client connection"""
    await mock_tts_client.connect()
    # Should not raise any errors


@pytest.mark.asyncio
async def test_mock_tts_client_convert_to_speech(mock_tts_client):
    """Test mock TTS client text-to-speech conversion"""
    text = "Hello, this is a test message"
    audio_data = await mock_tts_client.convert_to_speech(text)
    
    # Verify audio data is generated
    assert audio_data is not None
    assert len(audio_data) > 0
    assert isinstance(audio_data, bytes)
    
    # Verify audio format (1 second at 16kHz, 16-bit mono = 32000 bytes)
    expected_size = mock_tts_client.config.sample_rate * 2  # 2 bytes per sample
    assert len(audio_data) == expected_size


@pytest.mark.asyncio
async def test_mock_tts_client_context_manager(mock_tts_client):
    """Test mock TTS client as context manager"""
    async with mock_tts_client as client:
        audio_data = await client.convert_to_speech("Test message")
        assert len(audio_data) > 0


@pytest.mark.asyncio
async def test_mock_tts_client_chinese_text(mock_tts_client):
    """Test mock TTS client with Chinese text"""
    text = "你好，这是一个测试消息"
    audio_data = await mock_tts_client.convert_to_speech(text)
    
    assert audio_data is not None
    assert len(audio_data) > 0


@pytest.mark.asyncio
async def test_mock_tts_client_long_text(mock_tts_client):
    """Test mock TTS client with long text"""
    text = "This is a very long text message. " * 20
    audio_data = await mock_tts_client.convert_to_speech(text)
    
    assert audio_data is not None
    assert len(audio_data) > 0


@pytest.mark.asyncio
async def test_mock_tts_client_empty_text(mock_tts_client):
    """Test mock TTS client with empty text"""
    text = ""
    audio_data = await mock_tts_client.convert_to_speech(text)
    
    # Should still generate audio (silence)
    assert audio_data is not None
    assert len(audio_data) > 0


def test_tts_config_defaults():
    """Test TTS configuration default values"""
    config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com"
    )
    
    assert config.voice == "zhifeng_emo"
    assert config.language == "zh-CN"
    assert config.speed == 1.0
    assert config.pitch == 1.0
    assert config.audio_format == "pcm"
    assert config.sample_rate == 16000
    assert config.timeout_seconds == 5.0


def test_tts_config_custom_values():
    """Test TTS configuration with custom values"""
    config = TTSConfig(
        api_key="test_key",
        endpoint="wss://test.example.com",
        voice="custom_voice",
        language="en-US",
        speed=1.5,
        pitch=0.8,
        audio_format="mp3",
        sample_rate=24000,
        timeout_seconds=10.0
    )
    
    assert config.voice == "custom_voice"
    assert config.language == "en-US"
    assert config.speed == 1.5
    assert config.pitch == 0.8
    assert config.audio_format == "mp3"
    assert config.sample_rate == 24000
    assert config.timeout_seconds == 10.0
