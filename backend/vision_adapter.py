# Vision Model Adapter for multimodal image analysis
import asyncio
import base64
import logging
from abc import ABC, abstractmethod

import httpx

from backend.models import VisionResult

logger = logging.getLogger(__name__)


class VisionLLMAdapter(ABC):
    """Abstract base class for vision model adapters."""

    @abstractmethod
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str,
    ) -> VisionResult:
        raise NotImplementedError


class QwenOmniAdapter(VisionLLMAdapter):
    """Adapter for Qwen vision model (OpenAI-compatible /chat/completions)."""

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-vl-flash-2026-01-22",
        endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        timeout_seconds: int = 8,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

        if endpoint and not endpoint.endswith("/chat/completions"):
            self.endpoint = f"{endpoint.rstrip('/')}/chat/completions"
        else:
            self.endpoint = endpoint

        logger.info(
            "QwenOmniAdapter initialized with model: %s, endpoint: %s, timeout: %ss",
            self.model,
            self.endpoint,
            timeout_seconds,
        )

    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str,
    ) -> VisionResult:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        question = (prompt or "").strip()
        if len(question) > 500:
            question = question[:500]

        full_prompt = (
            f"使用者問題：{question}\n"
            "請用繁體中文，2句、40字內，只描述明顯物件。"
            "不要推測，不要建議。"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {"type": "text", "text": full_prompt},
                    ],
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.1,
        }

        try:
            logger.info(
                "Calling vision API with %ss timeout for req_id=%s",
                self.timeout_seconds,
                req_id,
            )
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint, headers=headers, json=payload)

            if response.status_code != 200:
                error_msg = f"API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return VisionResult(text="視覺分析失敗，請重試。", confidence=None, error=error_msg)

            result = response.json()
            choices = result.get("choices", [])
            if not choices:
                error_msg = "No choices in vision response"
                logger.error(error_msg)
                return VisionResult(text="視覺分析失敗，請重試。", confidence=None, error=error_msg)

            text_content = choices[0].get("message", {}).get("content", "")
            if not text_content:
                error_msg = "No text content in vision response"
                logger.error(error_msg)
                return VisionResult(text="視覺分析失敗，請重試。", confidence=None, error=error_msg)

            logger.info("Vision analysis successful for req_id=%s", req_id)
            return VisionResult(text=text_content, confidence=None, error=None)

        except asyncio.TimeoutError:
            error_msg = f"Vision API timeout ({self.timeout_seconds}s exceeded)"
            logger.error("%s for req_id=%s", error_msg, req_id)
            return VisionResult(text="視覺分析逾時，請重試。", confidence=None, error=error_msg)
        except Exception as e:
            error_msg = f"Vision API error: {e}"
            logger.error("%s for req_id=%s", error_msg, req_id)
            return VisionResult(text="視覺分析失敗，請重試。", confidence=None, error=error_msg)


class MockVisionAdapter(VisionLLMAdapter):
    """Mock adapter for testing without real API."""

    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str,
    ) -> VisionResult:
        await asyncio.sleep(0.5)
        return VisionResult(text="前方有一個物件。", confidence=0.95, error=None)
