# Unit tests for data models
import pytest
import time
from backend.models import (
    Event, EventType, RequestContext, ConnectionState,
    RequestState, ConnectionType, VisionResult
)


def test_event_creation():
    """Test Event dataclass creation"""
    event = Event(
        event_type=EventType.ASR_FINAL.value,
        timestamp=time.time(),
        req_id="test-123",
        data={"text": "測試文字"}
    )
    
    assert event.event_type == EventType.ASR_FINAL.value
    assert event.req_id == "test-123"
    assert event.data["text"] == "測試文字"


def test_event_to_dict():
    """Test Event serialization to dictionary"""
    timestamp = time.time()
    event = Event(
        event_type=EventType.TRIGGER_FIRED.value,
        timestamp=timestamp,
        req_id="test-456",
        data={"trigger_text": "識別物品"}
    )
    
    event_dict = event.to_dict()
    assert event_dict["event_type"] == EventType.TRIGGER_FIRED.value
    assert event_dict["timestamp"] == timestamp
    assert event_dict["req_id"] == "test-456"
    assert event_dict["data"]["trigger_text"] == "識別物品"


def test_request_context_creation():
    """Test RequestContext dataclass creation"""
    ctx = RequestContext(
        req_id="req-789",
        trigger_text="請你幫我識別物品",
        trigger_time=time.time(),
        state=RequestState.TRIGGERED.value
    )
    
    assert ctx.req_id == "req-789"
    assert ctx.trigger_text == "請你幫我識別物品"
    assert ctx.state == RequestState.TRIGGERED.value
    assert ctx.image_bytes is None
    assert ctx.vision_result is None


def test_connection_state_creation():
    """Test ConnectionState dataclass creation"""
    now = time.time()
    conn = ConnectionState(
        conn_id="conn-001",
        conn_type=ConnectionType.ESP32_AUDIO.value,
        connected_at=now,
        last_heartbeat=now,
        metadata={"device_id": "esp32-001"}
    )
    
    assert conn.conn_id == "conn-001"
    assert conn.conn_type == ConnectionType.ESP32_AUDIO.value
    assert conn.metadata["device_id"] == "esp32-001"


def test_vision_result_creation():
    """Test VisionResult dataclass creation"""
    result = VisionResult(
        text="這是一個紅色的蘋果",
        confidence=0.95,
        error=None
    )
    
    assert result.text == "這是一個紅色的蘋果"
    assert result.confidence == 0.95
    assert result.error is None


def test_vision_result_with_error():
    """Test VisionResult with error"""
    result = VisionResult(
        text="",
        confidence=None,
        error="API timeout"
    )
    
    assert result.text == ""
    assert result.confidence is None
    assert result.error == "API timeout"
