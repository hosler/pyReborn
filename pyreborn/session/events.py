"""
Simplified Events - Basic event system without complex patterns
"""

from enum import Enum
from typing import Dict, List, Callable, Any

class EventType(Enum):
    """Basic event types"""
    CHAT_MESSAGE = "chat_message"
    PLAYER_MOVED = "player_moved"
    LEVEL_CHANGED = "level_changed"
    PACKET_RECEIVED = "packet_received"
    CONNECTION_LOST = "connection_lost"
    CONNECTED = "connected"
    CONNECTION_FAILED = "connection_failed"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    DISCONNECTED = "disconnected"
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHENTICATION_FAILED = "authentication_failed"
    RAW_PACKET_RECEIVED = "raw_packet_received"
    PLAYER_PROPERTIES_RECEIVED = "player_properties_received"
    STRUCTURED_PACKET_RECEIVED = "structured_packet_received"
    INCOMING_PACKET_STRUCTURED = "incoming_packet_structured"
    
class EventManager:
    """Simple event manager - no complex patterns"""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}
    
    def subscribe(self, event_type: EventType, handler: Callable):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def emit(self, event_type: EventType, data: Any = None):
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(data)
                except Exception:
                    pass  # Ignore handler errors