"""
Event system for pyReborn
"""

from enum import Enum, auto
from typing import Callable, List, Dict, Any

class EventType(Enum):
    """Event types that can be subscribed to"""
    
    # Connection events
    CONNECTED = auto()
    DISCONNECTED = auto()
    LOGIN_SUCCESS = auto()
    LOGIN_FAILED = auto()
    
    # Player events
    PLAYER_PROPS_UPDATE = auto()
    OTHER_PLAYER_UPDATE = auto()
    PLAYER_ADDED = auto()
    PLAYER_REMOVED = auto()
    PLAYER_WARP = auto()
    PLAYER_UPDATE = auto()
    PLAYER_JOINED = auto()
    PLAYER_LEFT = auto()
    SELF_UPDATE = auto()
    STATS_UPDATE = auto()
    PLAYER_HURT = auto()
    PLAYER_KILLED = auto()
    
    # Level events
    LEVEL_ENTERED = auto()
    LEVEL_LEFT = auto()
    LEVEL_UPDATE = auto()
    TILES_UPDATED = auto()
    LEVEL_BOARD_LOADED = auto()
    LEVEL_SIGN_ADDED = auto()
    LEVEL_CHEST_ADDED = auto()
    LEVEL_LINK_ADDED = auto()
    LEVEL_CHANGE = auto()
    LEVEL_BOARD_UPDATE = auto()
    NPCS_UPDATE = auto()
    SIGNS_UPDATE = auto()
    LINKS_UPDATE = auto()
    
    # Chat events
    CHAT_MESSAGE = auto()
    PRIVATE_MESSAGE = auto()
    SERVER_MESSAGE = auto()
    GUILD_MESSAGE = auto()
    TOALL_MESSAGE = auto()
    
    # Combat events
    BOMB_ADDED = auto()
    BOMB_EXPLODED = auto()
    ARROW_SHOT = auto()
    PLAYER_HIT = auto()
    BOMB_PLACED = auto()
    ITEM_TAKEN = auto()
    
    # NPC events
    NPC_ADDED = auto()
    NPC_REMOVED = auto()
    NPC_UPDATE = auto()
    
    # Item events
    ITEM_ADDED = auto()
    ITEM_REMOVED = auto()
    CHEST_OPENED = auto()
    
    # Flag events
    FLAG_SET = auto()
    FLAG_DELETED = auto()
    
    # File events
    FILE_RECEIVED = auto()
    FILE_REQUEST_FAILED = auto()
    
    # Raw packet events (for advanced users)
    RAW_PACKET_RECEIVED = auto()
    RAW_PACKET_SENT = auto()
    PACKET_RECEIVED = auto()


class EventManager:
    """Manages event subscriptions and dispatching"""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}
        
    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe to an event"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Unsubscribe from an event"""
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)
            
    def emit(self, event_type: EventType, **kwargs):
        """Emit an event to all subscribers"""
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(**kwargs)
                except Exception as e:
                    # Log error but don't crash
                    print(f"Event handler error: {e}")
    
    def clear(self):
        """Clear all event subscriptions"""
        self._handlers.clear()