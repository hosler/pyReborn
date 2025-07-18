"""
Event system for pyReborn
"""

from enum import Enum, auto
from typing import Callable, List, Dict, Any, Union

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
    
    # New GServer-V2 events
    TRIGGER_ACTION = auto()
    GROUP_CHANGED = auto()
    LEVELGROUP_CHANGED = auto()
    BOARD_DATA_TEXT = auto()
    GHOST_TEXT = auto()
    GHOST_ICON = auto()
    MINIMAP_UPDATE = auto()
    SERVER_WARP = auto()
    CLIENT_FREEZE = auto()
    LEVEL_BOARD_COMPLETE = auto()  # Full board data assembled from text
    
    # Extended events for new features
    ITEM_SPAWNED = auto()
    OBJECT_THROWN = auto()
    PLAYER_PUSHED = auto()
    EXPLOSION = auto()
    HIT_CONFIRMED = auto()
    NPC_UPDATED = auto()
    NPC_ACTION = auto()
    NPC_MOVED = auto()
    TRIGGER_RESPONSE = auto()


class EventManager:
    """Manages event subscriptions and dispatching
    
    Supports both EventType enums and string events for flexibility.
    """
    
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._string_handlers: Dict[str, List[Callable]] = {}
        
    def subscribe(self, event_type: Union[EventType, str], handler: Callable):
        """Subscribe to an event (enum or string)"""
        if isinstance(event_type, str):
            if event_type not in self._string_handlers:
                self._string_handlers[event_type] = []
            self._string_handlers[event_type].append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
        
    def unsubscribe(self, event_type: Union[EventType, str], handler: Callable):
        """Unsubscribe from an event (enum or string)"""
        if isinstance(event_type, str):
            if event_type in self._string_handlers:
                self._string_handlers[event_type].remove(handler)
        else:
            if event_type in self._handlers:
                self._handlers[event_type].remove(handler)
            
    def emit(self, event_type: Union[EventType, str], data: Dict[str, Any] = None, **kwargs):
        """Emit an event to all subscribers
        
        Can be called with either:
        - emit(event_type, key=value, key2=value2)
        - emit(event_type, {"key": value, "key2": value2})
        """
        # Handle both dict and kwargs
        if data is not None:
            # Ensure data is a dict
            if not isinstance(data, dict):
                print(f"WARNING: emit() called with non-dict data for {event_type}: {type(data)}")
                # Try to recover - if it's bytes, assume it's file data
                if isinstance(data, bytes):
                    # This is likely a file event - wrap it properly
                    event_data = {"filename": "unknown", "data": data}
                    print(f"  Recovered by wrapping bytes as file data")
                else:
                    event_data = {}
            else:
                event_data = data
        else:
            event_data = kwargs
            
        if isinstance(event_type, str):
            if event_type in self._string_handlers:
                for handler in self._string_handlers[event_type]:
                    try:
                        handler(event_data)
                    except Exception as e:
                        print(f"Event handler error for '{event_type}': {e}")
        else:
            if event_type in self._handlers:
                for handler in self._handlers[event_type]:
                    try:
                        handler(**event_data)
                    except Exception as e:
                        print(f"Event handler error for {event_type}: {e}")
    
    def clear(self):
        """Clear all event subscriptions"""
        self._handlers.clear()
        self._string_handlers.clear()