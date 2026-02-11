# Property-based tests for vision timeout and error handling
# Feature: esp32-realtime-ai-assistant-tts
import pytest
from hypothesis import given, strategies as st, settings
from backend.vision_adapter import QwenOmniAdapter, MockVisionAdapter
from backend.models import VisionResult
import asyncio
from unittest.mock import AsyncMock, patch
import httpx


@pytest.mark.asyncio
@settings(max_examples=50, deadline=15000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    prompt=st.text(min_size=5, max_size=100),
    timeout_seconds=st.integers(min_value=1, max_value=3),
)
async def test_property_8_vision_timeout_enforcement(req_id, prompt, timeout_seconds):
    """
    **Property 8: Vision timeout enforcement**
    
    *For any* vision processing request that exceeds 8 seconds, 
    the system SHALL timeout the request and generate a fallback error response.
    
    **Validates: Requirements 4.4**
    """
    # Create adapter with short timeout for testing
    adapter = QwenOmniAdapter(
        api_key="test_key",
        timeout_seconds=timeout_seconds
    )
    
    # Create minimal valid JPEG image
    image_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00' + b'\x00' * 100 + b'\xff\xd9'
    
    # Mock httpx client to simulate timeout
    async def mock_post_timeout(*args, **kwargs):
        # Simulate API call that takes longer than timeout
        await asyncio.sleep(timeout_seconds + 1)
        raise httpx.TimeoutException("Request timeout")
    
    with patch('httpx.AsyncClient.post', side_effect=mock_post_timeout):
        # Call analyze_image (should timeout)
        result = await adapter.analyze_image(image_bytes, prompt, req_id)
        
        # Verify timeout was enforced
        assert isinstance(result, VisionResult), "Should return VisionResult"
        assert result.error is not None, "Should have error on timeout"
        assert "timeout" in result.error.lower(), f"Error should mention timeout: {result.error}"
        
        # Verify fallback message is provided
        assert result.text is not None, "Should have fallback text"
        assert len(result.text) > 0, "Fallback text should not be empty"
        assert "couldn't analyze" in result.text.lower() or "try again" in result.text.lower(), \
            f"Fallback text should be user-friendly: {result.text}"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    prompt=st.text(min_size=5, max_size=100),
    status_code=st.sampled_from([400, 401, 403, 404, 500, 502, 503]),
)
async def test_property_9_vision_error_handling(req_id, prompt, status_code):
    """
    **Property 9: Vision error handling**
    
    *For any* vision model error response, the system SHALL generate a fallback response 
    indicating the system cannot process the image, rather than propagating the raw error.
    
    **Validates: Requirements 4.5**
    """
    adapter = QwenOmniAdapter(
        api_key="test_key",
        timeout_seconds=5
    )
    
    # Create minimal valid JPEG image
    image_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00' + b'\x00' * 100 + b'\xff\xd9'
    
    # Mock httpx client to simulate API error
    class MockResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = f"API Error {status_code}"
        
        def json(self):
            return {"error": f"Error {self.status_code}"}
    
    async def mock_post_error(*args, **kwargs):
        return MockResponse(status_code)
    
    with patch('httpx.AsyncClient.post', side_effect=mock_post_error):
        # Call analyze_image (should handle error)
        result = await adapter.analyze_image(image_bytes, prompt, req_id)
        
        # Verify error was handled
        assert isinstance(result, VisionResult), "Should return VisionResult"
        assert result.error is not None, "Should have error on API failure"
        
        # Verify fallback message is provided (not raw error)
        assert result.text is not None, "Should have fallback text"
        assert len(result.text) > 0, "Fallback text should not be empty"
        assert "couldn't analyze" in result.text.lower() or "try again" in result.text.lower(), \
            f"Fallback text should be user-friendly, not raw error: {result.text}"
        
        # Verify raw error is NOT exposed to user
        assert str(status_code) not in result.text, "Fallback text should not contain raw status code"
        assert "API Error" not in result.text, "Fallback text should not contain raw API error"


@pytest.mark.asyncio
@settings(max_examples=30, deadline=10000)
@given(
    req_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
    prompt=st.text(min_size=5, max_size=100),
    response_text=st.text(min_size=10, max_size=200),
)
async def test_property_vision_success_no_error(req_id, prompt, response_text):
    """
    Test that successful vision processing returns correct result without error.
    
    Verifies that:
    - Successful API calls return text response
    - No error is set on success
    - Response text is not a fallback message
    """
    adapter = QwenOmniAdapter(
        api_key="test_key",
        timeout_seconds=5
    )
    
    # Create minimal valid JPEG image
    image_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00' + b'\x00' * 100 + b'\xff\xd9'
    
    # Mock successful API response
    class MockResponse:
        status_code = 200
        
        def json(self):
            return {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"text": response_text}
                                ]
                            }
                        }
                    ]
                }
            }
    
    async def mock_post_success(*args, **kwargs):
        await asyncio.sleep(0.1)  # Simulate API delay
        return MockResponse()
    
    with patch('httpx.AsyncClient.post', side_effect=mock_post_success):
        # Call analyze_image (should succeed)
        result = await adapter.analyze_image(image_bytes, prompt, req_id)
        
        # Verify success
        assert isinstance(result, VisionResult), "Should return VisionResult"
        assert result.error is None, "Should not have error on success"
        assert result.text == response_text, "Should return actual response text"
        assert "couldn't analyze" not in result.text.lower(), "Should not return fallback message on success"
