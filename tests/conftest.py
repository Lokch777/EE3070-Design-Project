# Pytest configuration and fixtures for ESP32 ASR Capture Vision MVP
import pytest
import asyncio
from typing import Generator


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings():
    """Mock settings for testing"""
    from backend.config import Settings
    return Settings(
        asr_api_key="test_asr_key",
        vision_api_key="test_vision_key",
        server_host="127.0.0.1",
        server_port=8000,
        log_level="DEBUG"
    )
