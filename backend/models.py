# Core data models for ESP32 ASR Capture Vision MVP
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class EventType(str, Enum):
    """Event types for the system"""
    ASR_PARTIAL = "asr_partial"
    ASR_FINAL = "asr_final"
    TRIGGER_FIRED = "trigger_fired"
    CAPTURE_REQUESTED = "capture_requested"
    CAPTURE_RECEIVED = "capture_received"
    VISION_STARTED = "vision_started"
    VISION_RESULT = "vision_result"
    ERROR = "error"


class ConnectionType(str, Enum):
    """WebSocket connection types"""
    ESP32_AUDIO = "esp32_audio"
    ESP32_CTRL = "esp32_ctrl"
    ESP32_CAMERA = "esp32_camera"
    WEB_UI = "web_ui"


class RequestState(str, Enum):
    """Request processing states"""
    LISTENING = "LISTENING"
    TRIGGERED = "TRIGGERED"
    CAPTURING = "CAPTURING"
    WAITING_IMAGE = "WAITING_IMAGE"
    VISION_RUNNING = "VISION_RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"
    COOLDOWN = "COOLDOWN"


class ErrorType(str, Enum):
    """Error types for error handling"""
    # Connection errors
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_TIMEOUT = "connection_timeout"
    WEBSOCKET_CLOSED = "websocket_closed"
    
    # ASR errors
    ASR_CONNECTION_FAILED = "asr_connection_failed"
    ASR_AUTH_FAILED = "asr_auth_failed"
    ASR_TIMEOUT = "asr_timeout"
    
    # Capture errors
    CAPTURE_TIMEOUT = "capture_timeout"
    CAPTURE_FAILED = "capture_failed"
    INVALID_IMAGE = "invalid_image"
    IMAGE_TOO_LARGE = "image_too_large"
    
    # Vision errors
    VISION_TIMEOUT = "vision_timeout"
    VISION_API_ERROR = "vision_api_error"
    VISION_AUTH_FAILED = "vision_auth_failed"
    
    # System errors
    INVALID_REQ_ID = "invalid_req_id"
    INVALID_FORMAT = "invalid_format"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INTERNAL_ERROR = "internal_error"


@dataclass
class Event:
    """Event data structure"""
    event_type: str
    timestamp: float
    req_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "req_id": self.req_id,
            "data": self.data
        }


@dataclass
class RequestContext:
    """Context for a single trigger->capture->vision request"""
    req_id: str
    trigger_text: str
    trigger_time: float
    capture_time: Optional[float] = None
    image_bytes: Optional[bytes] = None
    vision_result: Optional[str] = None
    state: str = RequestState.TRIGGERED.value
    error: Optional[str] = None


@dataclass
class ConnectionState:
    """WebSocket connection state tracking"""
    conn_id: str
    conn_type: str
    connected_at: float
    last_heartbeat: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionResult:
    """Result from vision model analysis"""
    text: str
    confidence: Optional[float] = None
    error: Optional[str] = None
