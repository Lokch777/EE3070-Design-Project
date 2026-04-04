# Configuration management for ESP32 ASR Capture Vision MVP
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Unified Omni Configuration (preferred)
    omni_model: str = Field(default="qwen3.5-omni-flash-realtime", env="OMNI_MODEL")
    omni_api_key: Optional[str] = Field(default=None, env="OMNI_API_KEY")
    
    # ASR Service
    asr_model: str = Field(default="qwen3.5-omni-flash-realtime", env="ASR_MODEL")
    asr_api_key: Optional[str] = Field(default=None, env="ASR_API_KEY")
    asr_endpoint: str = Field(
        default="wss://dashscope.aliyuncs.com/api/v1/services/audio/asr",
        env="ASR_ENDPOINT"
    )
    
    # Vision Model
    vision_api_key: Optional[str] = Field(default=None, env="VISION_API_KEY")
    vision_model: str = Field(default="qwen3.5-omni-flash-realtime", env="VISION_MODEL")
    vision_endpoint: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        env="VISION_ENDPOINT"
    )
    
    # TTS Service
    tts_model: str = Field(default="qwen3.5-omni-flash-realtime", env="TTS_MODEL")
    tts_api_key: Optional[str] = Field(default=None, env="TTS_API_KEY")
    tts_endpoint: str = Field(
        default="wss://dashscope.aliyuncs.com/api/v1/services/audio/tts",
        env="TTS_ENDPOINT"
    )
    tts_voice: str = Field(default="Kiki", env="TTS_VOICE")
    tts_language: str = Field(default="zh", env="TTS_LANGUAGE")
    tts_speed: float = Field(default=1.0, env="TTS_SPEED")
    tts_pitch: float = Field(default=1.0, env="TTS_PITCH")
    tts_audio_format: str = Field(default="pcm", env="TTS_AUDIO_FORMAT")
    tts_sample_rate: int = Field(default=16000, env="TTS_SAMPLE_RATE")
    tts_timeout_seconds: float = Field(default=5.0, env="TTS_TIMEOUT_SECONDS")
    tts_retry_attempts: int = Field(default=1, env="TTS_RETRY_ATTEMPTS")
    tts_fallback_max_chars: int = Field(default=12, env="TTS_FALLBACK_MAX_CHARS")
    
    # Server Configuration
    server_host: str = Field(default="0.0.0.0", env="SERVER_HOST")
    server_port: int = Field(default=8000, env="SERVER_PORT")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # System Parameters
    max_concurrent_requests: int = Field(default=1, env="MAX_CONCURRENT_REQUESTS")
    cooldown_seconds: int = Field(default=3, env="COOLDOWN_SECONDS")
    capture_timeout_seconds: int = Field(default=5, env="CAPTURE_TIMEOUT_SECONDS")
    vision_timeout_seconds: int = Field(default=15, env="VISION_TIMEOUT_SECONDS")
    event_buffer_size: int = Field(default=100, env="EVENT_BUFFER_SIZE")
    
    # Trigger Configuration
    trigger_english_phrases: str = Field(
        default="describe the view,what do I see,what's in front of me,tell me what you see",
        env="TRIGGER_ENGLISH_PHRASES"
    )
    trigger_chinese_phrases: str = Field(
        default="描述一下景象,我看到什麼,前面是什麼,告訴我你看到什麼",
        env="TRIGGER_CHINESE_PHRASES"
    )
    trigger_fuzzy_threshold: float = Field(default=0.85, env="TRIGGER_FUZZY_THRESHOLD")
    
    # Audio Playback Configuration
    audio_chunk_size: int = Field(default=4096, env="AUDIO_CHUNK_SIZE")
    audio_buffer_size: int = Field(default=16384, env="AUDIO_BUFFER_SIZE")
    audio_stream_timeout: float = Field(default=10.0, env="AUDIO_STREAM_TIMEOUT")
    audio_chunk_pacing_seconds: float = Field(default=0.02, env="AUDIO_CHUNK_PACING_SECONDS")
    audio_realtime_pacing_factor: float = Field(default=0.9, env="AUDIO_REALTIME_PACING_FACTOR")
    
    # AWS EC2 Configuration
    public_url: Optional[str] = Field(default=None, env="PUBLIC_URL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def load_settings() -> Settings:
    """Load and validate settings"""
    try:
        settings = Settings()
        logger.info("Configuration loaded successfully")
        return settings
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise


def validate_api_keys(settings: Settings) -> bool:
    """Validate that required API keys are present"""

    if settings.omni_api_key and settings.omni_api_key != "your_omni_api_key_here":
        logger.info("OMNI_API_KEY is configured and will be used for ASR/Vision/TTS")
        return True

    if not settings.asr_api_key or settings.asr_api_key == "your_dashscope_api_key_here":
        logger.error("ASR_API_KEY is not configured")
        return False

    if not settings.vision_api_key or settings.vision_api_key == "your_vision_api_key_here":
        logger.error("VISION_API_KEY is not configured")
        return False

    if not settings.tts_api_key or settings.tts_api_key == "your_tts_api_key_here":
        logger.error("TTS_API_KEY is not configured")
        return False
    
    logger.info("API keys validated successfully")
    return True
