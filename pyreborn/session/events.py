"""
Event System - Consolidated event management

Provides event types and event manager for the consolidated architecture.
This replaces the old scattered event handling with a unified system.
"""

from enum import Enum
import logging
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Event:
    """Simple event data structure"""
    event_type: 'EventType'
    data: Optional[Dict[str, Any]] = None


class EventType(Enum):
    """Event types for the PyReborn client"""
    
    # Connection events
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_LOST = "connection_lost" 
    CONNECTION_ERROR = "connection_error"
    CONNECTED = "connected"  # Alias for CONNECTION_ESTABLISHED
    DISCONNECTED = "disconnected"  # Alias for CONNECTION_LOST
    CONNECTION_FAILED = "connection_failed"
    RAW_PACKET_SENT = "raw_packet_sent"
    RAW_PACKET_RECEIVED = "raw_packet_received"
    PACKET_RECEIVED = "packet_received"
    STRUCTURED_PACKET_RECEIVED = "structured_packet_received"
    INCOMING_PACKET_STRUCTURED = "incoming_packet_structured"
    
    # Authentication events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    
    # Player events
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    PLAYER_MOVED = "player_moved"
    PLAYER_PROPS_UPDATE = "player_props_update"
    PLAYER_PROPERTIES_RECEIVED = "player_properties_received"
    OTHER_PLAYER_UPDATE = "other_player_update"
    
    # Level events
    LEVEL_LOADED = "level_loaded"
    LEVEL_CHANGED = "level_changed"
    LEVEL_WARP = "level_warp"
    
    # Communication events
    PLAYER_CHAT = "player_chat"
    CHAT_MESSAGE = "player_chat"  # Alias for compatibility
    PRIVATE_MESSAGE = "private_message"
    SERVER_MESSAGE = "server_message"
    
    # Combat events
    WEAPON_FIRED = "weapon_fired"
    PLAYER_HIT = "player_hit"
    EXPLOSION = "explosion"
    
    # Item events
    ITEM_ADDED = "item_added"
    ITEM_REMOVED = "item_removed"
    CHEST_OPENED = "chest_opened"
    
    # File events
    FILE_DOWNLOADED = "file_downloaded"
    FILE_UP_TO_DATE = "file_up_to_date"
    FILE_DOWNLOAD_STARTED = "file_download_started"
    FILE_DOWNLOAD_PROGRESS = "file_download_progress"
    FILE_DOWNLOAD_FAILED = "file_download_failed"
    
    # NPC events
    NPC_SPAWNED = "npc_spawned"
    NPC_REMOVED = "npc_removed"
    NPC_MOVED = "npc_moved"
    NPC_SERVER_STATUS = "npc_server_status"
    
    # System events
    ERROR_OCCURRED = "error_occurred"
    WARNING_ISSUED = "warning_issued"
    DEBUG_INFO = "debug_info"
    SERVER_SIGNATURE = "server_signature"
    FLAG_SET = "flag_set"
    LEVEL_MODTIME = "level_modtime"
    WORLD_TIME_UPDATE = "world_time_update"
    STAFF_GUILDS_UPDATE = "staff_guilds_update"
    ACTIVE_LEVEL_SET = "active_level_set"
    PROCESS_LIST_UPDATE = "process_list_update"


class EventManager:
    """Manages event subscriptions and dispatching"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.listeners: Dict[EventType, List[Callable]] = defaultdict(list)
        self.event_count: Dict[EventType, int] = defaultdict(int)
        
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to an event type"""
        self.listeners[event_type].append(callback)
        self.logger.debug(f"Subscribed to {event_type.value}")
        
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from an event type"""
        if callback in self.listeners[event_type]:
            self.listeners[event_type].remove(callback)
            self.logger.debug(f"Unsubscribed from {event_type.value}")
            
    def emit(self, event_type: EventType, data: Any = None):
        """Emit an event to all subscribers"""
        self.event_count[event_type] += 1
        
        for callback in self.listeners[event_type]:
            try:
                callback(data)
            except Exception as e:
                self.logger.error(f"Error in event callback for {event_type.value}: {e}")
                
    def get_event_stats(self) -> Dict[str, int]:
        """Get event statistics"""
        return {event_type.value: count for event_type, count in self.event_count.items()}
        
    def clear_all_listeners(self):
        """Clear all event listeners"""
        self.listeners.clear()
        self.logger.debug("All event listeners cleared")
        
    def process_queue(self):
        """Process any pending events - compatibility method"""
        # This is a compatibility method for clients that expect a queue-based system
        # Our event system is immediate, so this is a no-op
        pass