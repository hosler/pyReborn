#!/usr/bin/env python3
"""
Legacy RebornClient Compatibility Layer

This provides a RebornClient class that wraps ModularRebornClient for backward compatibility.
This allows us to remove the dependency on the old client while maintaining API compatibility.
"""

import warnings
from typing import Optional, Dict, Any, List, Callable
from ..core.simple_consolidated_client import RebornClient
from ..core.events import EventType


class LegacyRebornClient:
    """
    Legacy RebornClient interface for backward compatibility.
    
    This is a wrapper around RebornClient that provides the old API.
    New code should use RebornClient directly.
    """
    
    def __init__(self, host: str, port: int = 14900, version: str = "2.19"):
        """Initialize legacy client with RebornClient backend"""
        warnings.warn(
            "LegacyRebornClient is deprecated. Please use RebornClient for new projects.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Create modern client
        self._client = RebornClient(host=host, port=port, version=version)
        
        # Legacy attributes
        self.host = host
        self.port = port
        self.version = version
        self.connected = False
        self.logged_in = False
        self.account = None
        self.nickname = None
        
        # Setup event forwarding
        self._setup_event_forwarding()
        
    def _setup_event_forwarding(self):
        """Setup event forwarding from modern client"""
        self._client.events.subscribe(EventType.CONNECTED, self._on_connected)
        self._client.events.subscribe(EventType.DISCONNECTED, self._on_disconnected)
        self._client.events.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)
        self._client.events.subscribe(EventType.LOGIN_FAILED, self._on_login_failed)
    
    def _on_connected(self, event):
        self.connected = True
        
    def _on_disconnected(self, event):
        self.connected = False
        self.logged_in = False
        
    def _on_login_success(self, event):
        self.logged_in = True
        
    def _on_login_failed(self, event):
        self.logged_in = False
    
    # Connection methods
    
    def connect(self) -> bool:
        """Connect to server"""
        result = self._client.connect()
        self.connected = result
        return result
    
    def disconnect(self):
        """Disconnect from server"""
        self._client.disconnect()
        self.connected = False
        self.logged_in = False
    
    def login(self, account: str, password: str) -> bool:
        """Login to server"""
        self.account = account
        result = self._client.login(account, password)
        if result:
            self.logged_in = True
            self.nickname = account  # Default nickname
        return result
    
    def is_connected(self) -> bool:
        """Check if connected"""
        return self._client.is_connected()
    
    def is_logged_in(self) -> bool:
        """Check if logged in"""
        return self._client.is_logged_in()
    
    # Player access
    
    @property
    def local_player(self):
        """Get local player"""
        return self._client.get_local_player()
    
    def get_player(self, player_id: int):
        """Get player by ID"""
        # This would need to be implemented based on how the old client worked
        level_mgr = self._client.get_manager('level')
        if level_mgr and hasattr(level_mgr, 'get_current_level'):
            level = level_mgr.get_current_level()
            if level and hasattr(level, 'players'):
                return level.players.get(player_id)
        return None
    
    # Actions (delegate to modern client)
    
    def move(self, x: float, y: float, direction=None):
        """Move player"""
        self._client.move(x, y, direction)
    
    def say(self, message: str):
        """Send chat message"""
        self._client.say(message)
    
    def send_pm(self, player: str, message: str):
        """Send private message"""
        if hasattr(self._client, 'send_pm'):
            self._client.send_pm(player, message)
        elif hasattr(self._client, 'actions'):
            self._client.actions.send_pm(player, message)
    
    def set_nickname(self, nickname: str):
        """Set nickname"""
        self.nickname = nickname
        self._client.set_nickname(nickname)
    
    def set_chat(self, chat: str):
        """Set chat bubble"""
        self._client.set_chat(chat)
    
    def set_head(self, head: str):
        """Set head image"""
        self._client.set_head(head)
    
    def set_body(self, body: str):
        """Set body image"""
        self._client.set_body(body)
    
    # Manager access (legacy style)
    
    @property
    def level_manager(self):
        """Get level manager"""
        return self._client.get_manager('level')
    
    @property
    def item_manager(self):
        """Get item manager"""
        return self._client.get_manager('item')
    
    @property
    def gmap_manager(self):
        """Get GMAP manager"""
        return self._client.get_manager('gmap')
    
    @property
    def combat_manager(self):
        """Get combat manager"""
        return self._client.get_manager('combat')
    
    @property
    def npc_manager(self):
        """Get NPC manager"""
        return self._client.get_manager('npc')
    
    # Event system (legacy style)
    
    def on(self, event_name: str, handler: Callable):
        """Subscribe to event (legacy style)"""
        # Map string events to EventType
        event_map = {
            'connected': EventType.CONNECTED,
            'disconnected': EventType.DISCONNECTED,
            'login_success': EventType.LOGIN_SUCCESS,
            'login_failed': EventType.LOGIN_FAILED,
            'player_update': EventType.PLAYER_UPDATE,
            'level_change': EventType.LEVEL_TRANSITION,
            'chat_message': EventType.CHAT_MESSAGE,
            'private_message': EventType.PRIVATE_MESSAGE,
        }
        
        event_type = event_map.get(event_name.lower())
        if event_type:
            self._client.events.subscribe(event_type, handler)
        else:
            # For unknown events, try direct subscription
            self._client.events.subscribe(event_name, handler)
    
    def off(self, event_name: str, handler: Callable):
        """Unsubscribe from event (legacy style)"""
        # Would need to implement unsubscribe in event system
        pass
    
    # File operations
    
    def request_file(self, filename: str) -> bool:
        """Request file from server"""
        return self._client.request_file(filename)
    
    # Warp operations
    
    def warp_to_level(self, level_name: str, x: float, y: float):
        """Warp to level"""
        if hasattr(self._client, 'actions'):
            self._client.actions.warp_to_level(level_name, x, y)
    
    # Properties (legacy style)
    
    @property
    def current_level(self):
        """Get current level name"""
        player = self.local_player
        if player:
            return player.level
        return None
    
    @property
    def x(self):
        """Get player X position"""
        player = self.local_player
        return player.x if player else 0
    
    @property
    def y(self):
        """Get player Y position"""
        player = self.local_player
        return player.y if player else 0
    
    @property
    def hearts(self):
        """Get player hearts"""
        player = self.local_player
        return player.hearts if player else 0
    
    @property
    def rupees(self):
        """Get player rupees"""
        player = self.local_player
        return player.rupees if player else 0
    
    # String representation
    
    def __repr__(self):
        return f"RebornClient(host='{self.host}', port={self.port}, connected={self.connected})"