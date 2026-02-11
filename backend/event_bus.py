# Event Bus for ESP32 ASR Capture Vision MVP
import asyncio
import time
from collections import deque
from typing import Dict, List, Optional, AsyncIterator, Set
from backend.models import Event, EventType
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """
    Event bus for pub/sub messaging between components.
    Maintains a ring buffer of recent events for history queries.
    """
    
    def __init__(self, buffer_size: int = 100):
        """
        Initialize event bus.
        
        Args:
            buffer_size: Maximum number of events to keep in history (default: 100)
        """
        self.buffer_size = buffer_size
        self.history: deque = deque(maxlen=buffer_size)
        self.subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        logger.info(f"EventBus initialized with buffer size {buffer_size}")
    
    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers and add to history.
        
        Args:
            event: Event to publish
        """
        async with self._lock:
            # Add to history (ring buffer automatically removes oldest)
            self.history.append(event)
            logger.debug(f"Event published: {event.event_type} (req_id: {event.req_id})")
        
        # Notify subscribers
        event_type = event.event_type
        if event_type in self.subscribers:
            disconnected_queues = []
            for queue in self.subscribers[event_type]:
                try:
                    await queue.put(event)
                except Exception as e:
                    logger.error(f"Failed to deliver event to subscriber: {e}")
                    disconnected_queues.append(queue)
            
            # Clean up disconnected subscribers
            for queue in disconnected_queues:
                self.subscribers[event_type].discard(queue)
        
        # Also notify wildcard subscribers (subscribed to all events)
        if "*" in self.subscribers:
            for queue in self.subscribers["*"]:
                try:
                    await queue.put(event)
                except Exception as e:
                    logger.error(f"Failed to deliver event to wildcard subscriber: {e}")
    
    async def subscribe(self, event_type: str = "*") -> AsyncIterator[Event]:
        """
        Subscribe to events of a specific type.
        
        Args:
            event_type: Type of events to subscribe to, or "*" for all events
            
        Yields:
            Events as they are published
        """
        queue: asyncio.Queue = asyncio.Queue()
        
        # Register subscriber
        if event_type not in self.subscribers:
            self.subscribers[event_type] = set()
        self.subscribers[event_type].add(queue)
        
        logger.info(f"New subscriber for event type: {event_type}")
        
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            # Unsubscribe on cleanup
            if event_type in self.subscribers:
                self.subscribers[event_type].discard(queue)
                logger.info(f"Subscriber unsubscribed from: {event_type}")
    
    def get_history(self, limit: Optional[int] = None, event_type: Optional[str] = None) -> List[Event]:
        """
        Get recent events from history.
        
        Args:
            limit: Maximum number of events to return (default: all)
            event_type: Filter by event type (default: all types)
            
        Returns:
            List of events in reverse chronological order (newest first)
        """
        events = list(self.history)
        
        # Filter by event type if specified
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Reverse to get newest first
        events.reverse()
        
        # Apply limit
        if limit:
            events = events[:limit]
        
        logger.debug(f"History query: {len(events)} events returned")
        return events
    
    def clear_history(self) -> None:
        """Clear all events from history."""
        self.history.clear()
        logger.info("Event history cleared")
    
    def get_stats(self) -> Dict:
        """Get statistics about the event bus."""
        return {
            "history_size": len(self.history),
            "buffer_size": self.buffer_size,
            "subscriber_count": sum(len(subs) for subs in self.subscribers.values()),
            "event_types": list(self.subscribers.keys())
        }
