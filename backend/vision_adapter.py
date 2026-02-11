# Vision Model Adapter for multimodal image analysis
import base64
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
import httpx
from backend.models import VisionResult

logger = logging.getLogger(__name__)


class VisionLLMAdapter(ABC):
    """Abstract base class for vision model adapters"""
    
    @abstractmethod
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str
    ) -> VisionResult:
        """
        Analyze image with vision model.
        
        Args:
            image_bytes: JPEG image data
            prompt: Text prompt/question about the image
            req_id: Request ID for tracking
            
        Returns:
            VisionResult with text response
        """
        pass


class QwenOmniAdapter(VisionLLMAdapter):
    """Adapter for Qwen Omni Flash vision model"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "qwen-vl-plus",
        endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        timeout_seconds: int = 8
    ):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = 0  # No retries for vision (requirement 4.4)
        self.retry_delay = 5
        
        logger.info(f"QwenOmniAdapter initialized with model: {model}, timeout: {timeout_seconds}s")
    
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str
    ) -> VisionResult:
        """
        Analyze image using Qwen Omni Flash API with 8-second timeout.
        Returns fallback error message on timeout or API error.
        """
        
        # Encode image to base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Compose full prompt
        full_prompt = f"{prompt}\n請描述圖片中的物品。"
        
        # Prepare request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/jpeg;base64,{image_b64}"
                            },
                            {
                                "text": full_prompt
                            }
                        ]
                    }
                ]
            }
        }
        
        try:
            logger.info(f"Calling vision API with {self.timeout_seconds}s timeout")
            
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Extract text from response
                    output = result.get("output", {})
                    choices = output.get("choices", [])
                    
                    if choices:
                        message = choices[0].get("message", {})
                        content = message.get("content", [])
                        
                        # Find text content
                        text_content = ""
                        for item in content:
                            if isinstance(item, dict) and item.get("text"):
                                text_content = item["text"]
                                break
                        
                        if text_content:
                            logger.info(f"Vision analysis successful for req_id={req_id}")
                            return VisionResult(
                                text=text_content,
                                confidence=None,
                                error=None
                            )
                    
                    # No valid response - return fallback
                    error_msg = "No valid response from vision model"
                    logger.error(error_msg)
                    return VisionResult(
                        text="I couldn't analyze the image, please try again",
                        confidence=None,
                        error=error_msg
                    )
                
                else:
                    error_msg = f"API error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return VisionResult(
                        text="I couldn't analyze the image, please try again",
                        confidence=None,
                        error=error_msg
                    )
            
        except asyncio.TimeoutError:
            error_msg = f"Vision API timeout ({self.timeout_seconds}s exceeded)"
            logger.error(f"{error_msg} for req_id={req_id}")
            return VisionResult(
                text="I couldn't analyze the image, please try again",
                confidence=None,
                error=error_msg
            )
        
        except Exception as e:
            error_msg = f"Vision API error: {str(e)}"
            logger.error(f"{error_msg} for req_id={req_id}")
            return VisionResult(
                text="I couldn't analyze the image, please try again",
                confidence=None,
                error=error_msg
            )


class MockVisionAdapter(VisionLLMAdapter):
    """Mock adapter for testing without real API"""
    
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        req_id: str
    ) -> VisionResult:
        """Return mock response"""
        await asyncio.sleep(0.5)  # Simulate API delay
        
        return VisionResult(
            text="這是一個測試物品（模擬回應）",
            confidence=0.95,
            error=None
        )
