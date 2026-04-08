import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx
import websockets

from backend.event_bus import EventBus
from backend.models import Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class OmniRealtimeResult:
    text: str
    audio_data: bytes
    sample_rate: int
    audio_format: str
    error: Optional[str] = None


class OmniRealtimeClient:
    """
    Unified realtime client for audio transcription and multimodal response generation.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        event_bus: EventBus,
        realtime_endpoint: str,
        http_endpoint: str,
        timeout_seconds: float = 10.0,
        tts_voice: str = "Kiki",
        tts_sample_rate: int = 16000,
        tts_audio_format: str = "pcm",
    ):
        self.api_key = api_key
        self.model = model
        self.event_bus = event_bus
        self.realtime_endpoint = realtime_endpoint
        self.http_endpoint = self._ensure_chat_completions_endpoint(http_endpoint)
        self.timeout_seconds = timeout_seconds
        self.tts_voice = tts_voice
        self.tts_sample_rate = tts_sample_rate
        self.tts_audio_format = tts_audio_format

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.task_id = ""
        self.current_device_id = "default"
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 1

    @staticmethod
    def _ensure_chat_completions_endpoint(endpoint: str) -> str:
        if endpoint.endswith("/chat/completions"):
            return endpoint
        return f"{endpoint.rstrip('/')}/chat/completions"

    @staticmethod
    def _extract_text(result: dict) -> str:
        choices = result.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    txt = item.get("text")
                    if isinstance(txt, str) and txt:
                        chunks.append(txt)
            return " ".join(chunks).strip()
        return ""

    @staticmethod
    def _extract_audio(result: dict) -> bytes:
        choices = result.get("choices") or []
        if not choices:
            return b""
        message = choices[0].get("message") or {}
        audio = message.get("audio") or {}
        data = audio.get("data")
        if isinstance(data, str) and data:
            try:
                return base64.b64decode(data)
            except Exception:
                return b""
        return b""

    async def connect(self) -> bool:
        try:
            self.ws = await websockets.connect(
                self.realtime_endpoint,
                extra_headers={"Authorization": f"Bearer {self.api_key}"},
            )
            self.task_id = uuid.uuid4().hex
            init_message = {
                "header": {"action": "run-task", "task_id": self.task_id, "streaming": "duplex"},
                "payload": {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self.model,
                    "input": {"format": "pcm", "sample_rate": 16000},
                    "parameters": {
                        "language_hints": ["en", "zh"],
                        "enable_intermediate_result": True,
                        "enable_punctuation_prediction": True,
                        "enable_inverse_text_normalization": True,
                    },
                },
            }
            await self.ws.send(json.dumps(init_message))
            response = json.loads(await self.ws.recv())
            event_name = (response.get("header") or {}).get("event")
            self.connected = event_name == "task-started"
            if self.connected:
                self.reconnect_attempts = 0
            return self.connected
        except Exception as e:
            logger.error("Failed to connect Omni realtime session: %s", e)
            self.connected = False
            return False

    async def send_audio_chunk(self, audio_chunk: bytes, device_id: str = "default") -> None:
        if not self.connected or not self.ws:
            return
        try:
            self.current_device_id = device_id or "default"
            await self.ws.send(audio_chunk)
        except Exception as e:
            logger.error("Failed sending audio chunk to Omni session: %s", e)
            self.connected = False

    async def receive_transcription(self) -> AsyncIterator[Event]:
        if not self.connected or not self.ws:
            return
        try:
            async for message in self.ws:
                result = json.loads(message)
                header = result.get("header") or {}
                event_name = header.get("event", "")
                if event_name not in {"task-generated", "result-generated"}:
                    if event_name == "task-failed":
                        self.connected = False
                        break
                    continue

                payload = result.get("payload") or {}
                output = payload.get("output") or {}
                sentence = output.get("sentence") or {}
                text = ""
                if isinstance(sentence, dict):
                    text = sentence.get("text") or ""
                if not text:
                    text = output.get("text") or ""
                if not isinstance(text, str) or not text:
                    continue

                sentence_end = bool(sentence.get("sentence_end")) if isinstance(sentence, dict) else False
                event = Event(
                    event_type=EventType.ASR_FINAL.value if sentence_end else EventType.ASR_PARTIAL.value,
                    timestamp=time.time(),
                    data={"text": text, "device_id": self.current_device_id},
                )
                await self.event_bus.publish(event)
                if sentence_end:
                    yield event
        except Exception as e:
            logger.error("Omni transcription receive error: %s", e)
            self.connected = False

    async def reconnect(self) -> bool:
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            return False
        self.reconnect_attempts += 1
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()

    async def close(self) -> None:
        try:
            if self.ws and self.connected:
                await self.ws.send(
                    json.dumps(
                        {
                            "header": {"action": "finish-task", "task_id": self.task_id, "streaming": "duplex"},
                            "payload": {"input": {}},
                        }
                    )
                )
                await asyncio.sleep(0.1)
                await self.ws.close()
        except Exception:
            pass
        finally:
            self.connected = False
            self.ws = None

    def validate_audio_format(self, audio_data: bytes) -> bool:
        if not audio_data:
            return False
        # Input stream is PCM16 mono; require even-byte frames and non-trivial chunk size.
        if len(audio_data) < 320:
            return False
        if len(audio_data) % 2 != 0:
            return False
        return True

    async def analyze_image_and_synthesize(self, image_bytes: bytes, prompt: str, req_id: str) -> OmniRealtimeResult:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        request_prompt = (prompt or "").strip() or "請描述我眼前最明顯的物件。"
        payload = {
            "model": self.model,
            "modalities": ["text", "audio"],
            "audio": {
                "voice": self.tts_voice,
                "format": self.tts_audio_format,
                "sample_rate": self.tts_sample_rate,
            },
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": request_prompt},
                    ],
                }
            ],
            "max_tokens": 80,
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.http_endpoint, headers=headers, json=payload)
            if response.status_code != 200:
                error = f"Omni API error: {response.status_code} - {response.text}"
                logger.error("req_id=%s %s", req_id, error)
                return OmniRealtimeResult(
                    text="模型回應失敗，請重試。",
                    audio_data=b"",
                    sample_rate=self.tts_sample_rate,
                    audio_format=self.tts_audio_format,
                    error=error,
                )
            result = response.json()
            text = self._extract_text(result) or "目前無法辨識，請再試一次。"
            audio_data = self._extract_audio(result)
            return OmniRealtimeResult(
                text=text,
                audio_data=audio_data,
                sample_rate=self.tts_sample_rate,
                audio_format=self.tts_audio_format,
                error=None,
            )
        except Exception as e:
            error = f"Omni request failed: {e}"
            logger.error("req_id=%s %s", req_id, error)
            return OmniRealtimeResult(
                text="模型回應失敗，請重試。",
                audio_data=b"",
                sample_rate=self.tts_sample_rate,
                audio_format=self.tts_audio_format,
                error=error,
            )
