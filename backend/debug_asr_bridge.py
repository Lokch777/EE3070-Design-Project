import asyncio
import websockets
import json
import logging
import time
import uuid
import wave
from typing import Optional, AsyncIterator
from backend.models import Event, EventType
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)

class ASRBridge:
    def __init__(self, api_key: str, endpoint: str, event_bus: EventBus, model_id: str = "qwen3-asr-flash-realtime-2026-02-10"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.event_bus = event_bus
        self.model_id = model_id
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 5
        self.current_device_id = "default"
        self.task_id = ""
        
        # 開啟測試錄音 (如果不需要可以將這段註解掉)
        self.debug_wav = wave.open("debug_esp32_audio.wav", "wb")
        self.debug_wav.setnchannels(1)
        self.debug_wav.setsampwidth(2)
        self.debug_wav.setframerate(16000)
        
    async def connect(self) -> bool:
        try:
            logger.info(f"Connecting to ASR service using model: {self.model_id}")
            self.ws = await websockets.connect(self.endpoint, extra_headers={"Authorization": f"Bearer {self.api_key}"})
            self.task_id = uuid.uuid4().hex
            
            init_message = {
                "header": {"action": "run-task", "task_id": self.task_id, "streaming": "duplex"},
                "payload": {
                    "task_group": "audio", "task": "asr", "function": "recognition", "model": self.model_id,
                    "input": {"format": "pcm", "sample_rate": 16000},
                    "parameters": {
                        "language_hints": ["en"], # 確保鎖定英文
                        "enable_intermediate_result": True,
                        "enable_punctuation_prediction": True,
                        "enable_inverse_text_normalization": True
                    }
                }
            }
            await self.ws.send(json.dumps(init_message))
            response = await self.ws.recv()
            result = json.loads(response)
            
            if result.get("header", {}).get("event") == "task-started":
                self.connected = True
                self.reconnect_attempts = 0
                logger.info(f"ASR connected successfully! Task ID: {self.task_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to connect to ASR service: {e}")
            return False
    
    async def send_audio(self, audio_chunk: bytes, device_id: str = "default") -> None:
        if not self.connected or not self.ws: return
        try:
            self.current_device_id = device_id or "default"
            if hasattr(self, 'debug_wav') and self.debug_wav:
                self.debug_wav.writeframes(audio_chunk)
            await self.ws.send(audio_chunk)
        except Exception as e:
            logger.error(f"Failed to send audio to ASR: {e}")
            self.connected = False
    
    async def receive_transcription(self) -> AsyncIterator[Event]:
        if not self.connected or not self.ws: return
        try:
            async for message in self.ws:
                try:
                    result = json.loads(message)
                    header = result.get("header", {})
                    if header.get("event") in ["task-generated", "result-generated"]:
                        text = result.get("payload", {}).get("output", {}).get("sentence", {}).get("text", "")
                        if text:
                            event = Event(
                                event_type=EventType.ASR_FINAL.value,
                                timestamp=time.time(),
                                data={"text": text, "device_id": self.current_device_id}
                            )
                            await self.event_bus.publish(event)
                            yield event
                    elif header.get("event") == "task-failed":
                        logger.error(f"ASR Task Failed: {result}")
                        self.connected = False
                        break
                except Exception as e:
                    logger.error(f"Error processing ASR result: {e}")
        except Exception as e:
            self.connected = False
    
    async def reconnect(self) -> bool:
        if self.reconnect_attempts >= self.max_reconnect_attempts: return False
        self.reconnect_attempts += 1
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()
    
    async def close(self) -> None:
        if hasattr(self, 'debug_wav') and self.debug_wav:
            self.debug_wav.close()
            self.debug_wav = None
            logger.info("✅ 測試音檔 debug_esp32_audio.wav 已儲存！")

        if self.ws and self.connected:
            try:
                await self.ws.send(json.dumps({"header": {"action": "finish-task", "task_id": self.task_id, "streaming": "duplex"}, "payload": {"input": {}}}))
                await asyncio.sleep(0.1)
                await self.ws.close()
            except: pass
        self.connected = False
        
    def validate_audio_format(self, audio_data: bytes) -> bool:
        # 🚀 終極放行：只要裡面有聲音資料，就通通送給阿里雲！
        # 徹底解決因為封包大小稍微不對，導致聲音缺一角(對講機斷訊)的問題
        if len(audio_data) > 0:
            return True
        return False
