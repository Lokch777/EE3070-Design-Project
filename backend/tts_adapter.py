# TTS Adapter for ESP32 Real-Time AI Assistant
import asyncio
import logging
from typing import Optional, Dict
from dataclasses import dataclass

from backend.event_bus import EventBus
from backend.models import Event, EventType
from backend.tts_client import TTSClient, TTSConfig, TTSError

logger = logging.getLogger(__name__)


@dataclass
class AudioData:
    """Audio data with metadata"""
    audio_bytes: bytes
    audio_format: str
    sample_rate: int
    duration_seconds: float


class TTSAdapter:
    """
    Text-to-Speech adapter for converting vision responses to audio.
    
    Responsibilities:
    - Subscribe to vision response events
    - Convert text to speech using TTS service
    - Implement retry logic for TTS failures
    - Emit audio-ready events with audio data
    - Handle error scenarios with fallback messages
    """
    
    def __init__(self, event_bus: EventBus, tts_client: TTSClient, config: TTSConfig):
        """
        Initialize TTS Adapter.
        
        Args:
            event_bus: Event bus for pub/sub messaging
            tts_client: TTS client for text-to-speech conversion
            config: TTS configuration
        """
        self.event_bus = event_bus
        self.tts_client = tts_client
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info("TTSAdapter initialized")
    
    async def start(self):
        """Start the TTS adapter and subscribe to vision response events"""
        if self._running:
            logger.warning("TTSAdapter already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._listen_for_vision_responses())
        logger.info("TTSAdapter started")
    
    async def stop(self):
        """Stop the TTS adapter"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TTSAdapter stopped")
    
    async def _listen_for_vision_responses(self):
        """Subscribe to vision response events and process them"""
        try:
            async for event in self.event_bus.subscribe(EventType.VISION_RESULT.value):
                if not self._running:
                    break
                
                await self._on_vision_response(event)
        except asyncio.CancelledError:
            logger.info("Vision response listener cancelled")
        except Exception as e:
            logger.error(f"Error in vision response listener: {e}")
    
    async def _on_vision_response(self, event: Event):
        """
        Handle vision response and convert to speech.
        
        Args:
            event: Vision response event
        """
        text = event.data.get("description", "")
        if not text:
            logger.warning(f"Empty description in vision response: {event.req_id}")
            return
        
        logger.info(f"Converting vision response to speech: req_id={event.req_id}")
        
        try:
            # Convert text to speech with retry
            audio_data = await self._convert_to_speech_with_retry(text)
            
            # Emit audio ready event
            await self._emit_audio_ready(
                audio_data=audio_data,
                request_id=event.req_id,
                device_id=event.data.get("device_id", "unknown")
            )
            
        except TTSError as e:
            logger.error(f"TTS conversion failed: {e}")
            await self._emit_error(e, event.req_id)
    
    async def _convert_to_speech_with_retry(self, text: str) -> AudioData:
        """
        Convert text to speech with retry logic.
        
        Args:
            text: Text to convert
            
        Returns:
            AudioData with audio bytes and metadata
            
        Raises:
            TTSError: If conversion fails after retries
        """
        last_error = None
        
        for attempt in range(self.config.timeout_seconds + 1):
            try:
                logger.debug(f"TTS conversion attempt {attempt + 1}")
                audio_bytes = await self._convert_to_speech(text)
                
                # Calculate duration (PCM16 at sample_rate)
                sample_count = len(audio_bytes) // 2  # 2 bytes per sample
                duration = sample_count / self.config.sample_rate
                
                return AudioData(
                    audio_bytes=audio_bytes,
                    audio_format=self.config.audio_format,
                    sample_rate=self.config.sample_rate,
                    duration_seconds=duration
                )
                
            except TTSError as e:
                last_error = e
                logger.warning(f"TTS attempt {attempt + 1} failed: {e}")
                
                if attempt < self.config.timeout_seconds:
                    await asyncio.sleep(0.5)  # Wait before retry
                else:
                    break
        
        # All retries failed
        raise TTSError(f"TTS conversion failed after retries: {last_error}")
    
    async def _convert_to_speech(self, text: str) -> bytes:
        """
        Convert text to speech audio.
        
        Args:
            text: Text to convert
            
        Returns:
            Audio data in configured format
            
        Raises:
            TTSError: If conversion fails
        """
        try:
            audio_data = await self.tts_client.convert_to_speech(text)
            logger.info(f"TTS conversion successful: {len(audio_data)} bytes")
            return audio_data
            
        except Exception as e:
            logger.error(f"TTS conversion error: {e}")
            raise TTSError(f"Conversion failed: {e}")
    
    async def _emit_audio_ready(
        self, 
        audio_data: AudioData, 
        request_id: str,
        device_id: str
    ):
        """
        Emit audio ready event.
        
        Args:
            audio_data: Audio data with metadata
            request_id: Request ID
            device_id: Device ID
        """
        event = Event(
            event_type=EventType.AUDIO_READY.value,
            timestamp=asyncio.get_event_loop().time(),
            req_id=request_id,
            data={
                "audio_data": audio_data.audio_bytes,
                "audio_format": audio_data.audio_format,
                "sample_rate": audio_data.sample_rate,
                "duration_seconds": audio_data.duration_seconds,
                "device_id": device_id
            }
        )
        
        await self.event_bus.publish(event)
        logger.info(
            f"Audio ready event emitted: req_id={request_id}, "
            f"duration={audio_data.duration_seconds:.2f}s"
        )
    
    async def _emit_error(self, error: Exception, request_id: str):
        """
        Emit TTS error event.
        
        Args:
            error: Error that occurred
            request_id: Request ID
        """
        event = Event(
            event_type=EventType.TTS_ERROR.value,
            timestamp=asyncio.get_event_loop().time(),
            req_id=request_id,
            data={
                "error": str(error),
                "error_type": type(error).__name__
            }
        )
        
        await self.event_bus.publish(event)
        logger.error(f"TTS error event emitted: req_id={request_id}, error={error}")
    
    def get_stats(self) -> Dict:
        """Get statistics about the TTS adapter"""
        return {
            "running": self._running,
            "config": {
                "voice": self.config.voice,
                "language": self.config.language,
                "audio_format": self.config.audio_format,
                "sample_rate": self.config.sample_rate
            }
        }
