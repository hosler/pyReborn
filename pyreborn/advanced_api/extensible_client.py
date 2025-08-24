#!/usr/bin/env python3
"""
Extensible Client with Virtual Methods
======================================

Provides an extensible client base class with virtual methods for packet handling,
inspired by industry-standard virtual method patterns.

This allows users to create custom client subclasses that override specific
packet handling methods, providing a clean inheritance-based approach.

Example usage:
    class MyGameClient(ExtensibleClient):
        def on_player_chat(self, player_id: int, message: str):
            print(f"Player {player_id}: {message}")
            
        def on_player_moved(self, player):
            print(f"Player moved to {player.x}, {player.y}")
            
        def on_level_changed(self, level_name: str):
            print(f"Entered level: {level_name}")
    
    client = MyGameClient("localhost", 14900)
    client.connect()
    client.login("username", "password")
"""

import logging
from typing import Optional, Dict, Any, List
import time

from ..client import Client
from ..protocol.packet_enums import IncomingPackets, OutgoingPackets
from ..models import Player, Level

logger = logging.getLogger(__name__)


class ExtensibleClient(Client):
    """
    Extensible client with virtual methods for packet handling.
    
    This class provides virtual methods that can be overridden in subclasses
    to customize packet handling behavior. It follows the same pattern as
    standard extensible client patterns.
    """
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037"):
        """
        Initialize extensible client.
        
        Args:
            host: Server hostname or IP address
            port: Server port number
            version: Protocol version to use
        """
        super().__init__(host, port, version)
        
        # Set up packet routing once connected
        self._packet_routing_setup = False
    
    def connect(self) -> bool:
        """
        Connect to server and set up packet routing.
        
        Returns:
            True if connected successfully
        """
        result = super().connect()
        if result and not self._packet_routing_setup:
            self._setup_packet_routing()
            self._packet_routing_setup = True
        return result
    
    def _setup_packet_routing(self):
        """Set up routing from packet processor to virtual methods"""
        # This would integrate with the client's packet processor
        # For now, this is a placeholder for future integration
        logger.debug("Setting up packet routing for extensible client")
    
    # Virtual methods for packet handling (can be overridden in subclasses)
    
    def on_player_props(self, player: Player) -> None:
        """
        Called when player properties are received.
        
        Args:
            player: Player object with updated properties
        """
        pass
    
    def on_other_player_props(self, player: Player) -> None:
        """
        Called when other player properties are received.
        
        Args:
            player: Other player object with properties
        """
        pass
    
    def on_player_chat(self, player_id: int, message: str) -> None:
        """
        Called when a chat message is received.
        
        Args:
            player_id: ID of the player who sent the message
            message: Chat message content
        """
        pass
    
    def on_private_message(self, player_id: int, message: str) -> None:
        """
        Called when a private message is received.
        
        Args:
            player_id: ID of the player who sent the message
            message: Private message content
        """
        pass
    
    def on_player_moved(self, player: Player) -> None:
        """
        Called when a player moves.
        
        Args:
            player: Player object with updated position
        """
        pass
    
    def on_player_warped(self, player: Player, level_name: str) -> None:
        """
        Called when a player warps to a different location.
        
        Args:
            player: Player object
            level_name: Name of the destination level
        """
        pass
    
    def on_level_changed(self, level_name: str, level: Optional[Level] = None) -> None:
        """
        Called when the current level changes.
        
        Args:
            level_name: Name of the new level
            level: Level object if available
        """
        pass
    
    def on_level_loaded(self, level: Level) -> None:
        """
        Called when level data is fully loaded.
        
        Args:
            level: Loaded level object
        """
        pass
    
    def on_npc_added(self, npc_id: int, x: float, y: float, npc_data: Dict[str, Any]) -> None:
        """
        Called when an NPC is added to the level.
        
        Args:
            npc_id: NPC identifier
            x: X coordinate
            y: Y coordinate  
            npc_data: NPC properties and data
        """
        pass
    
    def on_npc_moved(self, npc_id: int, x: float, y: float) -> None:
        """
        Called when an NPC moves.
        
        Args:
            npc_id: NPC identifier
            x: New X coordinate
            y: New Y coordinate
        """
        pass
    
    def on_npc_removed(self, npc_id: int) -> None:
        """
        Called when an NPC is removed from the level.
        
        Args:
            npc_id: NPC identifier
        """
        pass
    
    def on_item_added(self, x: float, y: float, item_type: str) -> None:
        """
        Called when an item is added to the level.
        
        Args:
            x: X coordinate
            y: Y coordinate
            item_type: Type of item
        """
        pass
    
    def on_item_removed(self, x: float, y: float) -> None:
        """
        Called when an item is removed from the level.
        
        Args:
            x: X coordinate
            y: Y coordinate
        """
        pass
    
    def on_bomb_exploded(self, x: float, y: float, power: int) -> None:
        """
        Called when a bomb explodes.
        
        Args:
            x: X coordinate of explosion
            y: Y coordinate of explosion
            power: Explosion power
        """
        pass
    
    def on_player_hurt(self, player_id: int, damage: float, x: float, y: float) -> None:
        """
        Called when a player is hurt.
        
        Args:
            player_id: ID of hurt player
            damage: Amount of damage
            x: X coordinate where damage occurred
            y: Y coordinate where damage occurred
        """
        pass
    
    def on_weapon_fired(self, player_id: int, x: float, y: float, direction: int) -> None:
        """
        Called when a weapon is fired.
        
        Args:
            player_id: ID of player who fired
            x: X coordinate
            y: Y coordinate
            direction: Direction of shot
        """
        pass
    
    def on_server_message(self, message: str) -> None:
        """
        Called when a server message is received.
        
        Args:
            message: Server message content
        """
        pass
    
    def on_admin_message(self, message: str) -> None:
        """
        Called when an admin message is received.
        
        Args:
            message: Admin message content
        """
        pass
    
    def on_file_received(self, filename: str, data: bytes) -> None:
        """
        Called when a file is received from the server.
        
        Args:
            filename: Name of received file
            data: File data
        """
        pass
    
    def on_disconnected(self, reason: str = "") -> None:
        """
        Called when the client is disconnected.
        
        Args:
            reason: Reason for disconnection (if available)
        """
        pass
    
    def on_connected(self) -> None:
        """Called when the client successfully connects."""
        pass
    
    def on_logged_in(self, player: Player) -> None:
        """
        Called when login is successful.
        
        Args:
            player: Local player object
        """
        pass
    
    def on_gmap_entered(self, gmap_name: str, segment_x: int, segment_y: int) -> None:
        """
        Called when entering a GMAP world.
        
        Args:
            gmap_name: Name of the GMAP
            segment_x: GMAP segment X coordinate
            segment_y: GMAP segment Y coordinate
        """
        pass
    
    def on_gmap_exited(self, gmap_name: str) -> None:
        """
        Called when exiting a GMAP world.
        
        Args:
            gmap_name: Name of the GMAP that was exited
        """
        pass
    
    # Utility methods for subclasses
    
    def broadcast_to_level(self, message: str) -> bool:
        """
        Broadcast a message to all players in the current level.
        
        Args:
            message: Message to broadcast
            
        Returns:
            True if message was sent successfully
        """
        return self.say(message)
    
    def get_nearby_players(self, radius: float = 5.0) -> List[Player]:
        """
        Get players within a certain radius.
        
        Args:
            radius: Search radius in tiles
            
        Returns:
            List of nearby players
        """
        # This would need to be implemented based on the client's player tracking
        return []
    
    def get_level_npcs(self) -> List[Dict[str, Any]]:
        """
        Get all NPCs in the current level.
        
        Returns:
            List of NPC data dictionaries
        """
        # This would need to be implemented based on the client's NPC tracking
        return []
    
    def get_level_items(self) -> List[Dict[str, Any]]:
        """
        Get all items in the current level.
        
        Returns:
            List of item data dictionaries
        """
        # This would need to be implemented based on the client's item tracking
        return []


__all__ = [
    'ExtensibleClient',
    'DecoratedClient'
]