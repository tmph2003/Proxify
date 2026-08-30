from typing import Callable, Dict, List, Any
import logging

logger = logging.getLogger("proxify.events")

class EventBus:
    """Simple synchronous Event Bus (Observer Pattern)."""
    
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, listener: Callable):
        """Register a listener for an event type."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(listener)

    def publish(self, event_type: str, **kwargs: Any):
        """Publish an event to all registered listeners."""
        if event_type not in self._listeners:
            return
            
        for listener in self._listeners[event_type]:
            try:
                listener(**kwargs)
            except Exception as e:
                logger.error(f"[EventBus] Error in listener {listener.__name__} for {event_type}: {e}", exc_info=True)

# Singleton event bus instance for the proxy
bus = EventBus()
