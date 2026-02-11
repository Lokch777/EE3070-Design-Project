# Trigger Engine for keyword detection
import time
import uuid
import asyncio
import logging
from typing import Optional
from backend.models import Event, EventType, RequestContext, RequestState
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)


class TriggerEngine:
    """
    Detects trigger keywords in ASR text and generates CAPTURE requests.
    Implements cooldown mechanism to prevent duplicate triggers.
    """
    
    def __init__(self, event_bus: EventBus, cooldown_seconds: int = 3):
        self.event_bus = event_bus
        self.cooldown_seconds = cooldown_seconds
        self.last_trigger_time: Optional[float] = None
        self.active_request: Optional[RequestContext] = None
        
        # Trigger keywords (case-insensitive)
        self.trigger_keywords = [
            "識別物品",
            "認下呢個係咩",
            "幫我認",
            "睇下呢個",
            "辨識物品",
            "這是什麼",
            "这是什么"
        ]
        
        logger.info(f"TriggerEngine initialized with {len(self.trigger_keywords)} keywords")
    
    def check_trigger(self, text: str) -> Optional[Event]:
        """
        Check if text contains trigger keywords.
        
        Args:
            text: ASR final text to check
            
        Returns:
            Trigger event if triggered, None otherwise
        """
        # Normalize text
        text_lower = text.lower().strip()
        
        # Check cooldown
        if self.is_in_cooldown():
            logger.debug(f"In cooldown, ignoring text: {text}")
            return None
        
        # Check if there's already an active request
        if self.active_request and self.active_request.state != RequestState.DONE.value:
            logger.debug(f"Active request in progress, ignoring text: {text}")
            return None
        
        # Check for trigger keywords
        matched_keyword = None
        for keyword in self.trigger_keywords:
            if keyword.lower() in text_lower:
                matched_keyword = keyword
                break
        
        if not matched_keyword:
            return None
        
        # Generate trigger event
        req_id = str(uuid.uuid4())
        self.last_trigger_time = time.time()
        
        # Create request context
        self.active_request = RequestContext(
            req_id=req_id,
            trigger_text=text,
            trigger_time=self.last_trigger_time,
            state=RequestState.TRIGGERED.value
        )
        
        logger.info(f"Trigger detected! req_id={req_id}, keyword='{matched_keyword}'")
        
        # Create trigger event
        event = Event(
            event_type=EventType.TRIGGER_FIRED.value,
            timestamp=self.last_trigger_time,
            req_id=req_id,
            data={
                "trigger_text": text,
                "matched_keyword": matched_keyword
            }
        )
        
        return event
    
    def is_in_cooldown(self) -> bool:
        """Check if trigger is in cooldown period"""
        if self.last_trigger_time is None:
            return False
        
        elapsed = time.time() - self.last_trigger_time
        return elapsed < self.cooldown_seconds
    
    def reset_cooldown(self) -> None:
        """Reset cooldown timer"""
        self.last_trigger_time = None
        logger.debug("Cooldown reset")
    
    def get_active_request(self) -> Optional[RequestContext]:
        """Get current active request context"""
        return self.active_request
    
    def update_request_state(self, req_id: str, state: str) -> None:
        """Update request state"""
        if self.active_request and self.active_request.req_id == req_id:
            self.active_request.state = state
            logger.debug(f"Request {req_id} state updated to {state}")
    
    def complete_request(self, req_id: str) -> None:
        """Mark request as complete and reset"""
        if self.active_request and self.active_request.req_id == req_id:
            self.active_request.state = RequestState.DONE.value
            logger.info(f"Request {req_id} completed")
            
            # Start cooldown
            self.last_trigger_time = time.time()
