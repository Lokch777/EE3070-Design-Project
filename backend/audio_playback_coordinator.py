# Audio Playback Coordinator for ESP32 Real-Time AI Assistant
import asyncio
import base64
import json
import logging
from typing import Optional, Dict
from dataclasses import dataclass
from fastapi import WebSocket

from backend.event_bus import EventBus
from backend.models import Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class PlaybackConfig:
    """Configuration for audio playback"""
    chunk_size: int = 4096  # Bytes per WebSocket message
    buffer_size: int = 16384  # ESP32 buffer size
    stream_timeout: float = 10.0


class AudioPlaybackCoordinator:
    """
    Audio playback coordinator for streaming audio to ESP32.
    
    Responsibilities:
    - Subscribe to audio-ready events
    - Stream audio chunks to ESP32 via WebSocket
    - Manage playback state (prevent concurrent playback)
    - Handle playback completion events from ESP32
    - Implement streaming resilience (resume/restart on interruption)
    """
    
    def __init__(self, event_bus: EventBus, config: PlaybackConfig):
        """
        Initialize Audio Playback Coordinator.
        
        Args:
            event_bus: Event bus for pub/sub messaging
            config: Playback configuration
        """
        self.event_bus = event_bus
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Track active playback per device
        self.active_playback: Dict[str, str] = {}  # device_id -> request_id
        
        # Store WebSocket connections per device
        self.device_connections: Dict[str, WebSocket] = {}
        
        logger.info("AudioPlaybackCoordinator initialized")
    
    async def start(self):
        """Start the playback coordinator and subscribe to audio ready events"""
        if self._running:
            logger.warning("AudioPlaybackCoordinator already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._listen_for_audio_ready())
        logger.info("AudioPlaybackCoordinator started")
    
    async def stop(self):
        """Stop the playback coordinator"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AudioPlaybackCoordinator stopped")
    
    def register_device(self, device_id: str, websocket: WebSocket):
        """
        Register a device WebSocket connection.
        
        Args:
            device_id: Device identifier
            websocket: WebSocket connection
        """
        self.device_connections[device_id] = websocket
        logger.info(f"Device registered: {device_id}")
    
    def unregister_device(self, device_id: str):
        """
        Unregister a device WebSocket connection.
        
        Args:
            device_id: Device identifier
        """
        if device_id in self.device_connections:
            del self.device_connections[device_id]
        if device_id in self.active_playback:
            del self.active_playback[device_id]
        logger.info(f"Device unregistered: {device_id}")
    
    async def _listen_for_audio_ready(self):
        """Subscribe to audio ready events and process them"""
        try:
            async for event in self.event_bus.subscribe(EventType.AUDIO_READY.value):
                if not self._running:
                    break
                
                await self._on_audio_ready(event)
        except asyncio.CancelledError:
            logger.info("Audio ready listener cancelled")
        except Exception as e:
            logger.error(f"Error in audio ready listener: {e}")
    
    async def _on_audio_ready(self, event: Event):
        """
        Handle audio ready event and begin streaming.
        
        Args:
            event: Audio ready event
        """
        device_id = event.data.get("device_id", "unknown")
        request_id = event.req_id
        
        logger.info(f"Audio ready for device {device_id}, req_id={request_id}")
        
        # Check if playback is already active for this device
        if self._is_playback_active(device_id):
            logger.warning(
                f"Playback already active for device {device_id}, "
                f"ignoring new request {request_id}"
            )
            return
        
        # Check if device is connected
        if device_id not in self.device_connections:
            logger.error(f"Device {device_id} not connected, cannot stream audio")
            await self._emit_playback_error(device_id, request_id, "Device not connected")
            return
        
        # Stream audio to device
        try:
            await self._stream_audio(
                audio_data=event.data.get("audio_data", b""),
                device_id=device_id,
                request_id=request_id,
                audio_format=event.data.get("audio_format", "pcm"),
                sample_rate=event.data.get("sample_rate", 16000)
            )
        except Exception as e:
            logger.error(f"Audio streaming failed: {e}")
            await self._emit_playback_error(device_id, request_id, str(e))
    
    async def _stream_audio(
        self,
        audio_data: bytes,
        device_id: str,
        request_id: str,
        audio_format: str,
        sample_rate: int
    ):
        """
        Stream audio chunks to ESP32 via WebSocket.
        
        Args:
            audio_data: Audio data to stream
            device_id: Device identifier
            request_id: Request identifier
            audio_format: Audio format (pcm, mp3)
            sample_rate: Sample rate in Hz
        """
        websocket = self.device_connections.get(device_id)
        if not websocket:
            raise Exception(f"Device {device_id} not connected")
        
        # Mark playback as active
        self.active_playback[device_id] = request_id
        
        # Emit playback started event
        await self._emit_playback_started(device_id, request_id)
        
        try:
            # Calculate total chunks
            total_chunks = (len(audio_data) + self.config.chunk_size - 1) // self.config.chunk_size
            
            logger.info(
                f"Streaming {len(audio_data)} bytes in {total_chunks} chunks "
                f"to device {device_id}"
            )
            
            # Stream chunks
            for i in range(0, len(audio_data), self.config.chunk_size):
                chunk = audio_data[i:i + self.config.chunk_size]
                sequence = i // self.config.chunk_size
                
                # Create WebSocket message
                message = {
                    "type": "audio_chunk",
                    "request_id": request_id,
                    "audio_data": base64.b64encode(chunk).decode(),
                    "sequence": sequence,
                    "total_chunks": total_chunks,
                    "format": audio_format,
                    "sample_rate": sample_rate
                }
                
                # Send chunk
                try:
                    await asyncio.wait_for(
                        websocket.send_json(message),
                        timeout=self.config.stream_timeout
                    )
                    logger.debug(f"Sent chunk {sequence + 1}/{total_chunks}")
                    
                    # Small delay to prevent overwhelming ESP32
                    await asyncio.sleep(0.01)
                    
                except asyncio.TimeoutError:
                    raise Exception(f"Timeout sending chunk {sequence}")
                except Exception as e:
                    raise Exception(f"Failed to send chunk {sequence}: {e}")
            
            logger.info(f"Audio streaming complete for request {request_id}")
            
            # Note: Playback complete event will be sent by ESP32
            # when it finishes playing the audio
            
        except Exception as e:
            logger.error(f"Audio streaming error: {e}")
            # Clear active playback on error
            if device_id in self.active_playback:
                del self.active_playback[device_id]
            raise
    
    async def on_playback_complete(self, device_id: str, request_id: str):
        """
        Handle playback completion from ESP32.
        
        Args:
            device_id: Device identifier
            request_id: Request identifier
        """
        logger.info(f"Playback complete: device={device_id}, req_id={request_id}")
        
        # Clear active playback
        if device_id in self.active_playback:
            del self.active_playback[device_id]
        
        # Emit playback complete event
        await self._emit_playback_complete(device_id, request_id)
    
    def _is_playback_active(self, device_id: str) -> bool:
        """
        Check if audio playback is currently active for a device.
        
        Args:
            device_id: Device identifier
            
        Returns:
            True if playback is active, False otherwise
        """
        return device_id in self.active_playback
    
    async def _emit_playback_started(self, device_id: str, request_id: str):
        """
        Emit playback started event.
        
        Args:
            device_id: Device identifier
            request_id: Request identifier
        """
        event = Event(
            event_type=EventType.PLAYBACK_STARTED.value,
            timestamp=asyncio.get_event_loop().time(),
            req_id=request_id,
            data={
                "device_id": device_id
            }
        )
        
        await self.event_bus.publish(event)
        logger.info(f"Playback started event emitted: req_id={request_id}")
    
    async def _emit_playback_complete(self, device_id: str, request_id: str):
        """
        Emit playback complete event.
        
        Args:
            device_id: Device identifier
            request_id: Request identifier
        """
        event = Event(
            event_type=EventType.PLAYBACK_COMPLETE.value,
            timestamp=asyncio.get_event_loop().time(),
            req_id=request_id,
            data={
                "device_id": device_id
            }
        )
        
        await self.event_bus.publish(event)
        logger.info(f"Playback complete event emitted: req_id={request_id}")
    
    async def _emit_playback_error(self, device_id: str, request_id: str, error: str):
        """
        Emit playback error event.
        
        Args:
            device_id: Device identifier
            request_id: Request identifier
            error: Error message
        """
        event = Event(
            event_type=EventType.PLAYBACK_ERROR.value,
            timestamp=asyncio.get_event_loop().time(),
            req_id=request_id,
            data={
                "device_id": device_id,
                "error": error
            }
        )
        
        await self.event_bus.publish(event)
        logger.error(f"Playback error event emitted: req_id={request_id}, error={error}")
    
    def get_stats(self) -> Dict:
        """Get statistics about the playback coordinator"""
        return {
            "running": self._running,
            "active_playback_count": len(self.active_playback),
            "connected_devices": len(self.device_connections),
            "active_playback": dict(self.active_playback)
        }
