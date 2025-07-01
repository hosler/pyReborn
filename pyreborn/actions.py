"""
Player actions for PyReborn.
Encapsulates all player actions like movement, chat, appearance changes.
"""

from typing import Optional, TYPE_CHECKING
from .protocol.enums import PlayerProp, Direction
from .protocol.packets import (
    PlayerPropsPacket, ToAllPacket, BombAddPacket,
    ArrowAddPacket, FireSpyPacket, PrivateMessagePacket
)

if TYPE_CHECKING:
    from .client import RebornClient

class PlayerActions:
    """Handles all player action methods"""
    
    def __init__(self, client: 'RebornClient'):
        self.client = client
        
    # Movement
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None):
        """Move to position"""
        if direction is None:
            direction = self.client.local_player.direction
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_X, x)
        packet.add_property(PlayerProp.PLPROP_Y, y)
        packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
        self.client._send_packet(packet)
        
        # Update local state
        self.client.local_player.x = x
        self.client.local_player.y = y
        self.client.local_player.direction = direction
        
    # Chat
    def set_chat(self, message: str):
        """Set chat bubble"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURCHAT, message)
        self.client._send_packet(packet)
        self.client.local_player.chat = message
        
    def say(self, message: str):
        """Send chat message to all"""
        packet = ToAllPacket(message)
        self.client._send_packet(packet)
        
    def send_pm(self, player_id: int, message: str):
        """Send private message"""
        packet = PrivateMessagePacket(player_id, message)
        self.client._send_packet(packet)
        
    # Appearance
    def set_nickname(self, nickname: str):
        """Set nickname"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_NICKNAME, nickname)
        self.client._send_packet(packet)
        self.client.local_player.nickname = nickname
        
    def set_head_image(self, image: str):
        """Set head image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_HEADGIF, image)
        self.client._send_packet(packet)
        self.client.local_player.head_image = image
        
    def set_body_image(self, image: str):
        """Set body image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BODYIMG, image)
        self.client._send_packet(packet)
        self.client.local_player.body_image = image
        
    def set_colors(self, colors: list):
        """Set player colors"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_COLORS, colors)
        self.client._send_packet(packet)
        self.client.local_player.colors = colors
        
    def set_gani(self, gani: str):
        """Set animation (gani)"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_GANI, gani)
        self.client._send_packet(packet)
        self.client.local_player.gani = gani
        
    # Combat
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, power: int = 1):
        """Drop a bomb"""
        if x is None:
            x = self.client.local_player.x
        if y is None:
            y = self.client.local_player.y
        packet = BombAddPacket(x, y, power)
        self.client._send_packet(packet)
        
    def shoot_arrow(self):
        """Shoot an arrow"""
        packet = ArrowAddPacket()
        self.client._send_packet(packet)
        
    def fire_effect(self):
        """Fire effect"""
        packet = FireSpyPacket()
        self.client._send_packet(packet)
        
    # Items
    def set_arrows(self, count: int):
        """Set arrow count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_ARROWSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.arrows = count
        
    def set_bombs(self, count: int):
        """Set bomb count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BOMBSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.bombs = count
        
    def set_rupees(self, count: int):
        """Set rupee count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_RUPEESCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.rupees = count
        
    def set_hearts(self, current: float, maximum: Optional[float] = None):
        """Set hearts"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURPOWER, current)
        if maximum is not None:
            packet.add_property(PlayerProp.PLPROP_MAXPOWER, maximum)
        self.client._send_packet(packet)
        self.client.local_player.hearts = current
        if maximum is not None:
            self.client.local_player.max_hearts = maximum