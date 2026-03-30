# ASR Bridge for FunASR / Paraformer (DashScope Inference Protocol)
import asyncio
import websockets
import json
import logging
import time
import uuid
from typing import Optional, AsyncIterator
from backend.models import Event, EventType
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)

class ASRBridge:
    """
    Bridge between ESP32 audio stream and Alibaba DashScope ASR service.
    Handles audio forwarding, transcription reception, and reconnection.
    """
    
    def __init__(self, api_key: str, endpoint: str, event_bus: EventBus, model_id: str = "qwen3-asr-flash-realtime-2026-02-10"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.event_bus = event_bus
        self.model_id = model_id
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 5  # seconds
        self.current_device_id = "default"
        self.task_id = ""
        
    async def connect(self) -> bool:
        """Connect to ASR service using DashScope Inference Protocol"""
        try:
            logger.info(f"Connecting to ASR service: {self.endpoint} using model: {self.model_id}")
            
            # Connect to WebSocket
            self.ws = await websockets.connect(
                self.endpoint,
                extra_headers={
                    "Authorization": f"Bearer {self.api_key}"
                }
            )
            
            # Generate a unique task_id for this connection session
            self.task_id = uuid.uuid4().hex
            
            # DashScope /api-ws/v1/inference strict protocol structure
            init_message = {
                "header": {
                    "action": "run-task",
                    "task_id": self.task_id,
                    "streaming": "duplex"
                },
                "payload": {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self.model_id,
                    "input": {
                        "format": "pcm",
                        "sample_rate": 16000
                    },
                    "parameters": {
                        "language_hints": ["en"],
                        "enable_intermediate_result": True,
                        "enable_punctuation_prediction": True,
                        "enable_inverse_text_normalization": True
                    }
                }
            }
            
            await self.ws.send(json.dumps(init_message))
            
            # Wait for acknowledgment
            response = await self.ws.recv()
            result = json.loads(response)
            
            # Check for success event: "task-started"
            event_status = result.get("header", {}).get("event")
            
            if event_status == "task-started":
                self.connected = True
                self.reconnect_attempts = 0
                logger.info(f"ASR service ({self.model_id}) connected successfully! Task ID: {self.task_id}")
                return True
            else:
                logger.error(f"ASR connection failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to ASR service: {e}")
            return False
    
    async def send_audio(self, audio_chunk: bytes, device_id: str = "default") -> None:
        """Send audio chunk to ASR service"""
        if not self.connected or not self.ws:
            return
        
        try:
            self.current_device_id = device_id or "default"
            # Send binary audio data directly
            await self.ws.send(audio_chunk)
        except Exception as e:
            logger.error(f"Failed to send audio to ASR: {e}")
            self.connected = False
    
    async def receive_transcription(self) -> AsyncIterator[Event]:
        """Receive transcription results from ASR service"""
        if not self.connected or not self.ws:
            return
        
        try:
            async for message in self.ws:
                try:
                    result = json.loads(message)
                    header = result.get("header", {})
                    payload = result.get("payload", {})
                    event_type_str = header.get("event")
                    
                    # Process text generation events
                    if event_type_str in ["task-generated", "result-generated"]:
                        output = payload.get("output", {})
                        sentence = output.get("sentence", {})
                        text = sentence.get("text", "")
                        
                        if text:
                            # 為了確保系統穩定觸發，只要有文字返回，我們就將其打包發送至事件匯流排
                            # 對於喚醒詞測試，我們可以先全部視為 ASR_FINAL
                            event = Event(
                                event_type=EventType.ASR_FINAL.value,
                                timestamp=time.time(),
                                data={
                                    "text": text,
                                    "device_id": self.current_device_id
                                }
                            )
                            
                            await self.event_bus.publish(event)
                            yield event
                            
                    elif event_type_str == "task-failed":
                        logger.error(f"ASR Task Failed mid-stream: {result}")
                        self.connected = False
                        break
                        
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
        """Close ASR connection gracefully"""
        if self.ws and self.connected:
            try:
                # Send finish-task signal
                finish_msg = {
                    "header": {
                        "action": "finish-task",
                        "task_id": self.task_id,
                        "streaming": "duplex"
                    },
                    "payload": {"input": {}}
                }
                await self.ws.send(json.dumps(finish_msg))
                await asyncio.sleep(0.1)
                await self.ws.close()
            except Exception as e:
                logger.error(f"Error closing ASR connection: {e}")
        
        self.connected = False
        logger.info("ASR connection closed")
        
    def validate_audio_format(self, audio_data: bytes) -> bool:
        expected_size = 3200
        tolerance = 200 
        
        if abs(len(audio_data) - expected_size) > tolerance:
            return False
        return True
