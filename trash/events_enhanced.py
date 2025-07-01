"""
Enhanced event system that supports both enum and string events
"""

from typing import Callable, List, Dict, Any, Union
from .events import EventType, EventManager as BaseEventManager

class EventManager(BaseEventManager):
    """Enhanced EventManager that supports both EventType enums and string events"""
    
    def __init__(self):
        super().__init__()
        self._string_handlers: Dict[str, List[Callable]] = {}
        
    def subscribe(self, event_type: Union[EventType, str], handler: Callable):
        """Subscribe to an event (enum or string)"""
        if isinstance(event_type, str):
            if event_type not in self._string_handlers:
                self._string_handlers[event_type] = []
            self._string_handlers[event_type].append(handler)
        else:
            super().subscribe(event_type, handler)
            
    def unsubscribe(self, event_type: Union[EventType, str], handler: Callable):
        """Unsubscribe from an event (enum or string)"""
        if isinstance(event_type, str):
            if event_type in self._string_handlers:
                self._string_handlers[event_type].remove(handler)
        else:
            super().unsubscribe(event_type, handler)
            
    def emit(self, event_type: Union[EventType, str], data: Dict[str, Any] = None, **kwargs):
        """Emit an event to all subscribers"""
        # Handle both dict and kwargs
        if data is not None:
            event_data = data
        else:
            event_data = kwargs
            
        if isinstance(event_type, str):
            # String event
            if event_type in self._string_handlers:
                for handler in self._string_handlers[event_type]:
                    try:
                        handler(event_data)
                    except Exception as e:
                        print(f"Event handler error for '{event_type}': {e}")
        else:
            # Enum event - use parent's emit with kwargs
            super().emit(event_type, **event_data)
            
    def clear(self):
        """Clear all event subscriptions"""
        super().clear()
        self._string_handlers.clear()