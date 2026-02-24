# TTS Client for Qwen TTS Service
import asyncio
import websockets
import json
import logging
from typing import Optional, AsyncIterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TTSConfig:
    """Configuration for TTS service"""
    api_key: str
    endpoint: str
    voice: str = "zhifeng_emo"
    language: str = "zh-CN"
    speed: float = 1.0
    pitch: float = 1.0
    audio_format: str = "pcm"
    sample_rate: int = 16000
    timeout_seconds: float = 5.0


class TTSError(Exception):
    """TTS service error"""
    pass


class TTSClient:
    """Client for Qwen TTS service via WebSocket"""
    
    def __init__(self, config: TTSConfig):
        self.config = config
        self.ws = None
    
    async def connect(self):
        """Connect to TTS service"""
        try:
            headers = {
                "Authorization": f"Bearer {self.config.api_key}"
            }
            self.ws = await websockets.connect(
                self.config.endpoint,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10
            )
            logger.info("Connected to TTS service")
        except Exception as e:
            logger.error(f"Failed to connect to TTS service: {e}")
            raise TTSError(f"Connection failed: {e}")
    
    async def disconnect(self):
        """Disconnect from TTS service"""
        if self.ws:
            await self.ws.close()
            self.ws = None
            logger.info("Disconnected from TTS service")
    
    async def convert_to_speech(self, text: str) -> bytes:
        """
        Convert text to speech audio.
        
        Args:
            text: Text to convert to speech
            
        Returns:
            Audio data in PCM16 format
            
        Raises:
            TTSError: If conversion fails
        """
        if not self.ws:
            await self.connect()
        
        try:
            # Send TTS request
            request = {
                "header": {
                    "action": "run-task",
                    "streaming": "duplex",
                    "task_id": f"tts_{asyncio.get_event_loop().time()}"
                },
                "payload": {
                    "model": "cosyvoice-v1",
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "parameters": {
                        "voice": self.config.voice,
                        "format": self.config.audio_format,
                        "sample_rate": self.config.sample_rate,
                        "volume": 50,
                        "speech_rate": int(self.config.speed * 100),
                        "pitch_rate": int(self.config.pitch * 100)
                    },
                    "input": {
                        "text": text
                    }
                }
            }
            
            await self.ws.send(json.dumps(request))
            logger.debug(f"Sent TTS request for text: {text[:50]}...")
            
            # Collect audio chunks
            audio_chunks = []
            timeout = self.config.timeout_seconds
            
            try:
                async with asyncio.timeout(timeout):
                    async for message in self.ws:
                        if isinstance(message, bytes):
                            # Binary audio data
                            audio_chunks.append(message)
                        else:
                            # JSON response
                            response = json.loads(message)
                            
                            # Check for errors
                            if response.get("header", {}).get("status") == "error":
                                error_msg = response.get("header", {}).get("message", "Unknown error")
                                raise TTSError(f"TTS service error: {error_msg}")
                            
                            # Check if complete
                            if response.get("header", {}).get("event") == "task-finished":
                                logger.debug("TTS conversion complete")
                                break
            
            except asyncio.TimeoutError:
                raise TTSError(f"TTS conversion timeout after {timeout} seconds")
            
            if not audio_chunks:
                raise TTSError("No audio data received from TTS service")
            
            # Combine audio chunks
            audio_data = b"".join(audio_chunks)
            logger.info(f"TTS conversion successful: {len(audio_data)} bytes")
            
            return audio_data
            
        except TTSError:
            raise
        except Exception as e:
            logger.error(f"TTS conversion failed: {e}")
            raise TTSError(f"Conversion failed: {e}")
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


class MockTTSClient:
    """Mock TTS client for testing without API key"""
    
    def __init__(self, config: TTSConfig):
        self.config = config
        logger.info("Using MockTTSClient (no API key configured)")
    
    async def connect(self):
        logger.info("MockTTSClient: Connected (simulated)")
    
    async def disconnect(self):
        logger.info("MockTTSClient: Disconnected (simulated)")
    
    async def convert_to_speech(self, text: str) -> bytes:
        """Generate mock audio data"""
        logger.info(f"MockTTSClient: Converting text to speech: {text[:50]}...")
        
        # Simulate processing delay
        await asyncio.sleep(0.5)
        
        # Generate mock PCM16 audio (silence)
        # 1 second of silence at 16kHz, 16-bit mono
        sample_count = self.config.sample_rate * 1
        audio_data = b"\x00\x00" * sample_count
        
        logger.info(f"MockTTSClient: Generated {len(audio_data)} bytes of mock audio")
        return audio_data
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
