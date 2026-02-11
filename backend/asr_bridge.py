# ASR Bridge for Qwen3-ASR-Flash-Realtime
import asyncio
import websockets
import json
import logging
import time
from typing import Optional, AsyncIterator
from backend.models import Event, EventType
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)


class ASRBridge:
    """
    Bridge between ESP32 audio stream and Qwen3-ASR-Flash-Realtime service.
    Handles audio forwarding, transcription reception, and reconnection.
    """
    
    def __init__(self, api_key: str, endpoint: str, event_bus: EventBus):
        self.api_key = api_key
        self.endpoint = endpoint
        self.event_bus = event_bus
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 5  # seconds
        
    async def connect(self) -> bool:
        """Connect to ASR service"""
        try:
            logger.info(f"Connecting to ASR service: {self.endpoint}")
            
            # Connect to WebSocket
            self.ws = await websockets.connect(
                self.endpoint,
                extra_headers={
                    "Authorization": f"Bearer {self.api_key}"
                }
            )
            
            # Send initialization message
            init_message = {
                "header": {
                    "action": "start",
                    "streaming": "duplex"
                },
                "payload": {
                    "format": "pcm",
                    "sample_rate": 16000,
                    "enable_intermediate_result": True,
                    "enable_punctuation_prediction": True,
                    "enable_inverse_text_normalization": True
                }
            }
            
            await self.ws.send(json.dumps(init_message))
            
            # Wait for acknowledgment
            response = await self.ws.recv()
            result = json.loads(response)
            
            if result.get("header", {}).get("status") == 20000000:
                self.connected = True
                self.reconnect_attempts = 0
                logger.info("ASR service connected successfully")
                return True
            else:
                logger.error(f"ASR connection failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to ASR service: {e}")
            return False
    
    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to ASR service"""
        if not self.connected or not self.ws:
            logger.warning("ASR not connected, cannot send audio")
            return
        
        try:
            # Send binary audio data
            await self.ws.send(audio_chunk)
        except Exception as e:
            logger.error(f"Failed to send audio to ASR: {e}")
            self.connected = False
    
    async def receive_transcription(self) -> AsyncIterator[Event]:
        """Receive transcription results from ASR service"""
        if not self.connected or not self.ws:
            logger.error("ASR not connected")
            return
        
        try:
            async for message in self.ws:
                try:
                    result = json.loads(message)
                    
                    # Parse transcription result
                    payload = result.get("payload", {})
                    text = payload.get("result", "")
                    is_final = payload.get("status") == 2
                    
                    if text:
                        event_type = EventType.ASR_FINAL if is_final else EventType.ASR_PARTIAL
                        event = Event(
                            event_type=event_type.value,
                            timestamp=time.time(),
                            data={"text": text}
                        )
                        
                        # Publish to event bus
                        await self.event_bus.publish(event)
                        yield event
                        
                except json.JSONDecodeError:
                    logger.error("Invalid JSON from ASR service")
                except Exception as e:
                    logger.error(f"Error processing ASR result: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("ASR connection closed")
            self.connected = False
        except Exception as e:
            logger.error(f"Error receiving from ASR: {e}")
            self.connected = False
    
    async def reconnect(self) -> bool:
        """Attempt to reconnect to ASR service"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return False
        
        self.reconnect_attempts += 1
        logger.info(f"Reconnecting to ASR (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()
    
    async def close(self) -> None:
        """Close ASR connection"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.error(f"Error closing ASR connection: {e}")
        
        self.connected = False
        logger.info("ASR connection closed")
    
    def validate_audio_format(self, audio_data: bytes) -> bool:
        """
        Validate audio format (PCM16 mono 16kHz).
        Basic validation based on chunk size.
        """
        # Expected chunk size for 100ms at 16kHz mono PCM16: 3200 bytes
        expected_size = 3200
        tolerance = 200  # Allow some variation
        
        if abs(len(audio_data) - expected_size) > tolerance:
            logger.warning(f"Audio chunk size unexpected: {len(audio_data)} bytes (expected ~{expected_size})")
            return False
        
        return True
