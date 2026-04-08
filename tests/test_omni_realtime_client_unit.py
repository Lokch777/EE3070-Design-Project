import base64

import pytest

from backend.event_bus import EventBus
from backend.omni_realtime_client import OmniRealtimeClient


def _make_client() -> OmniRealtimeClient:
    return OmniRealtimeClient(
        api_key="test-key",
        model="qwen3.5-omni-plus-realtime",
        event_bus=EventBus(),
        realtime_endpoint="wss://example.com/realtime",
        http_endpoint="https://example.com/v1",
        timeout_seconds=1.0,
    )


def test_chat_endpoint_suffix_added():
    client = _make_client()
    assert client.http_endpoint.endswith("/chat/completions")


def test_extract_text_handles_string_and_list():
    text_str = OmniRealtimeClient._extract_text(
        {"choices": [{"message": {"content": "hello"}}]}
    )
    text_list = OmniRealtimeClient._extract_text(
        {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
    )
    assert text_str == "hello"
    assert text_list == "a b"


def test_extract_audio_decodes_base64_payload():
    payload = base64.b64encode(b"abc").decode("utf-8")
    data = OmniRealtimeClient._extract_audio(
        {"choices": [{"message": {"audio": {"data": payload}}}]}
    )
    assert data == b"abc"


@pytest.mark.asyncio
async def test_analyze_image_and_synthesize_success(monkeypatch):
    client = _make_client()

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [
                    {
                        "message": {
                            "content": "前方有桌子。",
                            "audio": {"data": base64.b64encode(b"pcm").decode("utf-8")},
                        }
                    }
                ]
            }

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr("backend.omni_realtime_client.httpx.AsyncClient", _AsyncClient)
    result = await client.analyze_image_and_synthesize(b"\x01\x02", "請描述", "req-1")
    assert result.error is None
    assert result.text
    assert result.audio_data == b"pcm"


@pytest.mark.asyncio
async def test_analyze_image_and_synthesize_http_error(monkeypatch):
    client = _make_client()

    class _Resp:
        status_code = 500
        text = "boom"

        @staticmethod
        def json():
            return {}

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr("backend.omni_realtime_client.httpx.AsyncClient", _AsyncClient)
    result = await client.analyze_image_and_synthesize(b"\x01\x02", "請描述", "req-2")
    assert result.error is not None
    assert result.audio_data == b""
