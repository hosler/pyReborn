"""
Item-related actions for PyReborn client
"""

from typing import Optional
import logging
from ..protocol.packet_types.items import (
    ItemAddPacket, ItemDeletePacket, ItemTakePacket,
    OpenChestPacket, ThrowCarriedPacket
)
from ..protocol.enums import LevelItemType

logger = logging.getLogger(__name__)


class ItemActions:
    """Item-related player actions"""
    
    def __init__(self, client):
        self.client = client
        
    def pickup_item(self, x: float, y: float) -> bool:
        """Attempt to pick up an item at position
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            True if item pickup was requested
        """
        # Check if there's an item at this position
        current_level = self.client.local_player.level
        item = self.client.item_manager.get_item_at(current_level, x, y)
        
        if not item:
            logger.debug(f"No item found at ({x}, {y})")
            return False
            
        # Check if already picked up
        if self.client.item_manager.is_picked_up(current_level, x, y):
            logger.debug(f"Item at ({x}, {y}) already picked up")
            return False
            
        # Send pickup request
        packet = ItemDeletePacket()
        packet.x = x
        packet.y = y
        self.client._send_packet(packet)
        
        # Mark as picked up to avoid duplicate requests
        self.client.item_manager.mark_picked_up(current_level, x, y)
        
        logger.info(f"Requested pickup of {item.item_type.name} at ({x}, {y})")
        return True
        
    def drop_item(self, item_type: LevelItemType, x: Optional[float] = None, y: Optional[float] = None):
        """Drop an item at position
        
        Args:
            item_type: Type of item to drop
            x: X coordinate (defaults to player position)
            y: Y coordinate (defaults to player position)
        """
        if x is None:
            x = self.client.local_player.x
        if y is None:
            y = self.client.local_player.y
            
        packet = ItemAddPacket()
        packet.x = x
        packet.y = y
        packet.item_type = item_type.value
        self.client._send_packet(packet)
        
        logger.info(f"Dropped {item_type.name} at ({x}, {y})")
        
    def take_item(self, player_id: int, item_id: int):
        """Take an item from another player (v2.31+)
        
        Args:
            player_id: ID of player to take from
            item_id: ID of item to take
        """
        packet = ItemTakePacket()
        packet.player_id = player_id
        packet.item_id = item_id
        self.client._send_packet(packet)
        
        logger.info(f"Requested to take item {item_id} from player {player_id}")
        
    def open_chest(self, x: int, y: int) -> bool:
        """Open a chest at tile position
        
        Args:
            x: Tile X coordinate
            y: Tile Y coordinate
            
        Returns:
            True if chest open was requested
        """
        # Check if there's a chest at this position
        level = self.client.level_manager.get_current_level()
        if not level:
            return False
            
        # Check for chest in level data
        for chest in level.chests:
            if chest.x == x and chest.y == y:
                packet = OpenChestPacket()
                packet.x = x
                packet.y = y
                self.client._send_packet(packet)
                
                logger.info(f"Opened chest at ({x}, {y})")
                return True
                
        logger.debug(f"No chest found at ({x}, {y})")
        return False
        
    def throw_carried(self, power: float = 1.0):
        """Throw currently carried object
        
        Args:
            power: Throw power (0.0 to 1.0)
        """
        # Check if carrying something
        if not hasattr(self.client.local_player, 'carry_sprite') or not self.client.local_player.carry_sprite:
            logger.debug("Not carrying anything to throw")
            return
            
        packet = ThrowCarriedPacket()
        packet.power = max(0.0, min(1.0, power))
        self.client._send_packet(packet)
        
        logger.info(f"Threw carried object with power {packet.power}")
        
    def set_carry_sprite(self, sprite: str):
        """Set what the player is carrying
        
        Args:
            sprite: Sprite name (e.g. "bush", "pot", "bomb") or empty to clear
        """
        from ..protocol.enums import PlayerProp
        from ..protocol.packets import PlayerPropsPacket
        
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CARRYSPRITE, sprite)
        self.client._send_packet(packet)
        
        # Update local player
        self.client.local_player.carry_sprite = sprite
        
        logger.info(f"Set carry sprite to '{sprite}'")
        
    def pickup_nearby_items(self, radius: float = 1.5) -> int:
        """Pick up all items within radius of player
        
        Args:
            radius: Search radius
            
        Returns:
            Number of items picked up
        """
        px = self.client.local_player.x
        py = self.client.local_player.y
        level = self.client.local_player.level
        
        items = self.client.item_manager.get_items_in_level(level)
        picked_up = 0
        
        for item in items:
            dx = abs(item.x - px)
            dy = abs(item.y - py)
            if dx <= radius and dy <= radius:
                if self.pickup_item(item.x, item.y):
                    picked_up += 1
                    
        return picked_up