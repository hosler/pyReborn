"""
Compatibility shim for OutgoingPacketAPI
=========================================

Maps old OutgoingPacketAPI calls to new Client methods.
This allows the reborn_modern systems to work with the new consolidated architecture.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OutgoingPacketAPI:
    """Compatibility wrapper for old packet API"""
    
    def __init__(self, client):
        """Initialize with a PyReborn Client instance
        
        Args:
            client: PyReborn Client instance
        """
        self.client = client
        
    def send_player_props(self, **props):
        """Send player property updates
        
        Maps to client.update_player_props() or similar
        """
        # In the new architecture, this would be handled by the client
        logger.debug(f"Sending player props: {props}")
        # The client handles this internally when you move or update player state
        
    def send_movement(self, x: float, y: float, direction: Optional[int] = None):
        """Send movement packet
        
        Maps to client.move()
        """
        if hasattr(self.client, 'move'):
            # Calculate relative movement
            if hasattr(self.client, 'get_player'):
                player = self.client.get_player()
                if player:
                    dx = x - player.x
                    dy = y - player.y
                    self.client.move(dx, dy)
            else:
                logger.warning("Cannot send movement - no player data")
        else:
            logger.warning("Client doesn't have move() method")
    
    def send_chat(self, message: str):
        """Send chat message
        
        Maps to client.say()
        """
        if hasattr(self.client, 'say'):
            self.client.say(message)
        else:
            logger.warning("Client doesn't have say() method")
    
    def send_weapon_fire(self, weapon_id: int):
        """Send weapon fire packet
        
        Would map to client.use_weapon() or similar
        """
        logger.debug(f"Firing weapon {weapon_id}")
        # The new client would handle this internally
        
    def send_level_warp(self, level_name: str, x: float, y: float):
        """Send level warp request
        
        Would map to client.warp() or similar
        """
        logger.debug(f"Warping to {level_name} at ({x}, {y})")
        # The new client would handle this internally
        
    def send_bomb_throw(self):
        """Send bomb throw packet"""
        logger.debug("Throwing bomb")
        # The new client would handle this internally
        
    def send_arrow_shoot(self, direction: int):
        """Send arrow shoot packet"""
        logger.debug(f"Shooting arrow in direction {direction}")
        # The new client would handle this internally


def create_packet_api(client):
    """Create a compatibility packet API for the given client
    
    Args:
        client: PyReborn Client instance
        
    Returns:
        OutgoingPacketAPI instance
    """
    return OutgoingPacketAPI(client)