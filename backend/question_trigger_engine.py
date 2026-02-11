# Question Trigger Engine for ESP32 Real-Time AI Assistant
import asyncio
import time
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from fuzzywuzzy import fuzz

from backend.event_bus import EventBus
from backend.models import Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class TriggerConfig:
    """Configuration for trigger detection"""
    english_triggers: List[str]
    chinese_triggers: List[str]
    cooldown_seconds: float = 3.0
    fuzzy_match_threshold: float = 0.85


@dataclass
class TriggerMatch:
    """Result of trigger phrase matching"""
    phrase: str
    confidence: float
    position: int
    question: str


class QuestionTriggerEngine:
    """
    Detects question phrases in ASR transcriptions and triggers image capture.
    
    Responsibilities:
    - Subscribe to ASR transcription events
    - Detect trigger phrases (English and Chinese)
    - Extract question context from transcriptions
    - Implement cooldown to prevent overlapping requests
    - Emit capture trigger events with question context
    """
    
    def __init__(self, event_bus: EventBus, config: TriggerConfig):
        """
        Initialize Question Trigger Engine.
        
        Args:
            event_bus: Event bus for pub/sub messaging
            config: Trigger configuration
        """
        self.event_bus = event_bus
        self.config = config
        self.last_trigger_time: Optional[float] = None
        self.active_request_id: Optional[str] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Combine all trigger phrases
        self.all_triggers = (
            self.config.english_triggers + 
            self.config.chinese_triggers
        )
        
        logger.info(
            f"QuestionTriggerEngine initialized with {len(self.all_triggers)} trigger phrases"
        )
    
    async def start(self):
        """Start the trigger engine and subscribe to ASR events"""
        if self._running:
            logger.warning("QuestionTriggerEngine already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._listen_for_transcriptions())
        logger.info("QuestionTriggerEngine started")
    
    async def stop(self):
        """Stop the trigger engine"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("QuestionTriggerEngine stopped")
    
    async def _listen_for_transcriptions(self):
        """Subscribe to ASR transcription events and process them"""
        try:
            async for event in self.event_bus.subscribe(EventType.ASR_FINAL.value):
                if not self._running:
                    break
                
                await self._on_transcription(event)
        except asyncio.CancelledError:
            logger.info("Transcription listener cancelled")
        except Exception as e:
            logger.error(f"Error in transcription listener: {e}")
    
    async def _on_transcription(self, event: Event):
        """
        Handle incoming transcription events.
        
        Args:
            event: ASR transcription event
        """
        text = event.data.get("text", "")
        if not text:
            return
        
        logger.debug(f"Processing transcription: {text}")
        
        # Check cooldown
        if self._is_cooldown_active():
            logger.debug("Cooldown active, ignoring transcription")
            return
        
        # Detect trigger phrase
        trigger_match = self._detect_trigger(text)
        if trigger_match:
            logger.info(
                f"Trigger detected: '{trigger_match.phrase}' "
                f"(confidence: {trigger_match.confidence:.2f})"
            )
            
            # Emit capture trigger event
            await self._emit_capture_trigger(
                question=trigger_match.question,
                device_id=event.data.get("device_id", "unknown"),
                req_id=event.req_id
            )
    
    def _detect_trigger(self, text: str) -> Optional[TriggerMatch]:
        """
        Detect trigger phrases in text using exact and fuzzy matching.
        
        Args:
            text: Transcribed text to search
            
        Returns:
            TriggerMatch if trigger found, None otherwise
        """
        text_lower = text.lower()
        
        for phrase in self.all_triggers:
            phrase_lower = phrase.lower()
            
            # Exact match
            if phrase_lower in text_lower:
                position = text_lower.index(phrase_lower)
                return TriggerMatch(
                    phrase=phrase,
                    confidence=1.0,
                    position=position,
                    question=text
                )
            
            # Fuzzy match
            ratio = fuzz.partial_ratio(phrase_lower, text_lower)
            confidence = ratio / 100.0
            
            if confidence >= self.config.fuzzy_match_threshold:
                return TriggerMatch(
                    phrase=phrase,
                    confidence=confidence,
                    position=0,
                    question=text
                )
        
        return None
    
    def _is_cooldown_active(self) -> bool:
        """
        Check if cooldown period is active.
        
        Returns:
            True if cooldown is active, False otherwise
        """
        if self.last_trigger_time is None:
            return False
        
        elapsed = time.time() - self.last_trigger_time
        return elapsed < self.config.cooldown_seconds
    
    async def _emit_capture_trigger(
        self, 
        question: str, 
        device_id: str,
        req_id: Optional[str] = None
    ):
        """
        Emit capture trigger event with question context.
        
        Args:
            question: User's question text
            device_id: Device ID
            req_id: Request ID (optional)
        """
        # Update cooldown timer
        self.last_trigger_time = time.time()
        
        # Generate request ID if not provided
        if not req_id:
            req_id = f"tts_{int(time.time() * 1000)}"
        
        self.active_request_id = req_id
        
        # Create and publish event
        event = Event(
            event_type=EventType.QUESTION_DETECTED.value,
            timestamp=time.time(),
            req_id=req_id,
            data={
                "question": question,
                "device_id": device_id,
                "trigger_time": self.last_trigger_time
            }
        )
        
        await self.event_bus.publish(event)
        logger.info(f"Capture trigger emitted: req_id={req_id}, question={question[:50]}...")
    
    def reset_cooldown(self):
        """Reset cooldown timer (for testing)"""
        self.last_trigger_time = None
        self.active_request_id = None
    
    def get_stats(self) -> Dict:
        """Get statistics about the trigger engine"""
        return {
            "running": self._running,
            "cooldown_active": self._is_cooldown_active(),
            "last_trigger_time": self.last_trigger_time,
            "active_request_id": self.active_request_id,
            "trigger_count": len(self.all_triggers)
        }
