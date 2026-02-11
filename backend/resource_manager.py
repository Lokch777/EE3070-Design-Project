# Resource management and concurrency control for ESP32 Real-Time AI Assistant
import logging
import time
import asyncio
from typing import Optional, Dict
from dataclasses import dataclass
from backend.models import Event, EventType
from backend.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class RequestLock:
    """Request lock information"""
    req_id: str
    device_id: str
    acquired_at: float
    state: str  # "processing", "playback", "complete"


class ResourceManager:
    """
    Manages system resources and enforces concurrency limits.
    Ensures only one request is processed at a time per device.
    """
    
    def __init__(self, event_bus: EventBus, max_concurrent_requests: int = 1):
        self.event_bus = event_bus
        self.max_concurrent_requests = max_concurrent_requests
        self.active_requests: Dict[str, RequestLock] = {}  # device_id -> RequestLock
        self.request_queue: Dict[str, list] = {}  # device_id -> list of pending requests
        
        logger.info(f"ResourceManager initialized with max_concurrent_requests={max_concurrent_requests}")
    
    async def acquire_request_lock(self, req_id: str, device_id: str) -> bool:
        """
        Attempt to acquire request lock for device.
        
        Args:
            req_id: Request ID
            device_id: Device ID
            
        Returns:
            True if lock acquired, False if rejected
        """
        # Check if device already has an active request
        if device_id in self.active_requests:
            active_lock = self.active_requests[device_id]
            logger.warning(
                f"Request rejected: device {device_id} already processing req_id={active_lock.req_id}, "
                f"new req_id={req_id}"
            )
            
            # Publish rejection event
            rejection_event = Event(
                event_type="request.rejected",
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "device_id": device_id,
                    "reason": "concurrent_request_limit",
                    "active_req_id": active_lock.req_id,
                    "message": "System is busy processing another request"
                }
            )
            await self.event_bus.publish(rejection_event)
            
            return False
        
        # Acquire lock
        lock = RequestLock(
            req_id=req_id,
            device_id=device_id,
            acquired_at=time.time(),
            state="processing"
        )
        self.active_requests[device_id] = lock
        
        logger.info(f"Request lock acquired: req_id={req_id}, device_id={device_id}")
        
        # Publish lock acquired event
        lock_event = Event(
            event_type="request.lock_acquired",
            timestamp=time.time(),
            req_id=req_id,
            data={
                "device_id": device_id
            }
        )
        await self.event_bus.publish(lock_event)
        
        return True
    
    async def release_request_lock(self, req_id: str, device_id: str) -> None:
        """
        Release request lock for device.
        
        Args:
            req_id: Request ID
            device_id: Device ID
        """
        if device_id not in self.active_requests:
            logger.warning(f"No active lock for device {device_id}, req_id={req_id}")
            return
        
        active_lock = self.active_requests[device_id]
        
        if active_lock.req_id != req_id:
            logger.warning(
                f"Lock mismatch: expected req_id={active_lock.req_id}, got req_id={req_id}"
            )
            return
        
        # Release lock
        del self.active_requests[device_id]
        
        duration = time.time() - active_lock.acquired_at
        logger.info(f"Request lock released: req_id={req_id}, device_id={device_id}, duration={duration:.2f}s")
        
        # Publish lock released event
        release_event = Event(
            event_type="request.lock_released",
            timestamp=time.time(),
            req_id=req_id,
            data={
                "device_id": device_id,
                "duration_seconds": duration
            }
        )
        await self.event_bus.publish(release_event)
    
    def is_device_busy(self, device_id: str) -> bool:
        """
        Check if device is currently processing a request.
        
        Args:
            device_id: Device ID
            
        Returns:
            True if device is busy, False otherwise
        """
        return device_id in self.active_requests
    
    def get_active_request(self, device_id: str) -> Optional[RequestLock]:
        """
        Get active request lock for device.
        
        Args:
            device_id: Device ID
            
        Returns:
            RequestLock if active, None otherwise
        """
        return self.active_requests.get(device_id)
    
    async def update_request_state(self, req_id: str, device_id: str, state: str) -> None:
        """
        Update state of active request.
        
        Args:
            req_id: Request ID
            device_id: Device ID
            state: New state ("processing", "playback", "complete")
        """
        if device_id not in self.active_requests:
            logger.warning(f"No active lock for device {device_id}, req_id={req_id}")
            return
        
        active_lock = self.active_requests[device_id]
        
        if active_lock.req_id != req_id:
            logger.warning(
                f"Lock mismatch: expected req_id={active_lock.req_id}, got req_id={req_id}"
            )
            return
        
        active_lock.state = state
        logger.debug(f"Request state updated: req_id={req_id}, state={state}")


class MemoryMonitor:
    """
    Monitors ESP32 memory usage and enforces memory limits.
    """
    
    def __init__(self, event_bus: EventBus, low_memory_threshold: float = 0.8):
        self.event_bus = event_bus
        self.low_memory_threshold = low_memory_threshold
        self.device_memory: Dict[str, float] = {}  # device_id -> memory usage (0.0-1.0)
        
        logger.info(f"MemoryMonitor initialized with threshold={low_memory_threshold}")
    
    def update_memory_usage(self, device_id: str, memory_usage: float) -> None:
        """
        Update memory usage for device.
        
        Args:
            device_id: Device ID
            memory_usage: Memory usage as fraction (0.0-1.0)
        """
        self.device_memory[device_id] = memory_usage
        
        if memory_usage >= self.low_memory_threshold:
            logger.warning(f"Low memory on device {device_id}: {memory_usage*100:.1f}%")
    
    async def check_memory_available(self, device_id: str, req_id: str) -> bool:
        """
        Check if device has sufficient memory for new request.
        
        Args:
            device_id: Device ID
            req_id: Request ID
            
        Returns:
            True if memory available, False if low memory
        """
        memory_usage = self.device_memory.get(device_id, 0.0)
        
        if memory_usage >= self.low_memory_threshold:
            logger.error(
                f"Memory check failed for device {device_id}: {memory_usage*100:.1f}% used, "
                f"threshold={self.low_memory_threshold*100:.1f}%"
            )
            
            # Publish low memory event
            memory_event = Event(
                event_type="memory.low",
                timestamp=time.time(),
                req_id=req_id,
                data={
                    "device_id": device_id,
                    "memory_usage": memory_usage,
                    "threshold": self.low_memory_threshold,
                    "message": "Memory low, please wait"
                }
            )
            await self.event_bus.publish(memory_event)
            
            return False
        
        return True
    
    def get_memory_usage(self, device_id: str) -> float:
        """
        Get current memory usage for device.
        
        Args:
            device_id: Device ID
            
        Returns:
            Memory usage as fraction (0.0-1.0)
        """
        return self.device_memory.get(device_id, 0.0)
