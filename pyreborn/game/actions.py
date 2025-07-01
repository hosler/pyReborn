"""
High-level game actions that use the client to perform operations.
"""
from typing import Optional, List, Tuple
import logging

from ..protocol.enums import PlayerToServer
from ..protocol.packets import PacketBuilder

logger = logging.getLogger(__name__)


class GameActions:
    """
    High-level game actions that abstract away packet details.
    """
    
    def __init__(self, client):
        self.client = client
        self.state = client.state
        
    def move(self, x: float, y: float, direction: Optional[int] = None) -> None:
        """
        Move the player to a position.
        
        Args:
            x: X coordinate (in tiles)
            y: Y coordinate (in tiles)  
            direction: Optional direction (0=up, 1=left, 2=down, 3=right)
        """
        if not self.state.connected:
            logger.warning("Cannot move: not connected")
            return
            
        # Update local state immediately for responsiveness
        if self.state.local_player:
            self.state.local_player.x = x
            self.state.local_player.y = y
            if direction is not None:
                self.state.local_player.dir = direction
                
        # Send movement packet
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PLI_PLAYERPROPS.value)
        packet.add_byte(3 if direction is not None else 2)  # Number of properties
        
        # X position
        packet.add_byte(1)  # PLPROP_X
        packet.add_byte(int(x * 2))  # X in half-tiles
        
        # Y position
        packet.add_byte(2)  # PLPROP_Y  
        packet.add_byte(int(y * 2))  # Y in half-tiles
        
        # Direction if provided
        if direction is not None:
            packet.add_byte(3)  # PLPROP_DIR
            packet.add_byte(direction)
            
        self.client.send_packet(packet)
        
    def say(self, message: str) -> None:
        """Send a chat message."""
        if not self.state.connected:
            logger.warning("Cannot say: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PLI_TOALL.value)
        packet.add_string(message)
        self.client.send_packet(packet)
        
    def set_nickname(self, nickname: str) -> None:
        """Change player nickname."""
        if not self.state.connected:
            logger.warning("Cannot set nickname: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PLI_PLAYERPROPS.value)
        packet.add_byte(1)  # Number of properties
        packet.add_byte(0)  # PLPROP_NICKNAME
        packet.add_string(nickname)
        self.client.send_packet(packet)
        
    def drop_bomb(self) -> None:
        """Drop a bomb at current position."""
        if not self.state.connected:
            logger.warning("Cannot drop bomb: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PLI_BOMBADD.value)
        self.client.send_packet(packet)
        
    def shoot_arrow(self, direction: Optional[int] = None) -> None:
        """
        Shoot an arrow.
        
        Args:
            direction: Direction to shoot (uses player direction if None)
        """
        if not self.state.connected:
            logger.warning("Cannot shoot arrow: not connected")
            return
            
        if direction is None and self.state.local_player:
            direction = self.state.local_player.dir
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.SHOOT)
        if direction is not None:
            packet.add_byte(direction)
        self.client.send_packet(packet)
        
    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.5) -> None:
        """
        Warp to a different level.
        
        Args:
            level_name: Name of the level (e.g. "onlinestartlocal.nw")
            x: X coordinate in the new level
            y: Y coordinate in the new level
        """
        if not self.state.connected:
            logger.warning("Cannot warp: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PLAYER_WARP)
        packet.add_string(f"{level_name},{x},{y}")
        self.client.send_packet(packet)
        
    def private_message(self, player_name: str, message: str) -> None:
        """Send a private message to another player."""
        if not self.state.connected:
            logger.warning("Cannot send PM: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.PRIVATE_MESSAGE)
        packet.add_string(f"{player_name}:{message}")
        self.client.send_packet(packet)
        
    def set_flag(self, flag_name: str, value: str) -> None:
        """Set a server flag."""
        if not self.state.connected:
            logger.warning("Cannot set flag: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.SET_FLAG)
        packet.add_string(f"{flag_name}={value}")
        self.client.send_packet(packet)
        
    def equip_weapon(self, weapon_name: str) -> None:
        """Equip a weapon."""
        if not self.state.connected:
            logger.warning("Cannot equip weapon: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.WEAPON_SELECT)
        packet.add_string(weapon_name)
        self.client.send_packet(packet)
        
    def guild_say(self, message: str) -> None:
        """Send a message to guild chat."""
        if not self.state.connected:
            logger.warning("Cannot guild say: not connected")
            return
            
        packet = PacketBuilder()
        packet.add_byte(PlayerToServer.GUILD_CHAT)
        packet.add_string(message)
        self.client.send_packet(packet)