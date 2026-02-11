# Configuration management for ESP32 ASR Capture Vision MVP
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # ASR Service
    asr_api_key: str = Field(..., env="ASR_API_KEY")
    asr_endpoint: str = Field(
        default="wss://dashscope.aliyuncs.com/api/v1/services/audio/asr",
        env="ASR_ENDPOINT"
    )
    
    # Vision Model
    vision_api_key: str = Field(..., env="VISION_API_KEY")
    vision_model: str = Field(default="qwen-vl-plus", env="VISION_MODEL")
    vision_endpoint: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        env="VISION_ENDPOINT"
    )
    
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
    if not settings.asr_api_key or settings.asr_api_key == "your_dashscope_api_key_here":
        logger.error("ASR_API_KEY is not configured")
        return False
    
    if not settings.vision_api_key or settings.vision_api_key == "your_vision_api_key_here":
        logger.error("VISION_API_KEY is not configured")
        return False
    
    logger.info("API keys validated successfully")
    return True
