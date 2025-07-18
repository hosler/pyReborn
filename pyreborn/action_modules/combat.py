"""
Combat-related actions for PyReborn client
"""

from typing import List, Optional
import logging
from ..protocol.packet_types.combat import (
    HurtPlayerPacket, HitObjectsPacket, ExplosionPacket, BaddyHurtPacket
)

logger = logging.getLogger(__name__)


class CombatActions:
    """Combat-related player actions"""
    
    def __init__(self, client):
        self.client = client
        
    def hurt_player(self, player_id: int, damage: float = 0.5, x: Optional[float] = None, y: Optional[float] = None):
        """Deal damage to another player
        
        Args:
            player_id: Target player ID
            damage: Amount of damage
            x: X position of hit (defaults to target position)
            y: Y position of hit (defaults to target position)
        """
        # Get target position if not specified
        if x is None or y is None:
            target = self.client.players.get(player_id)
            if target:
                x = target.x
                y = target.y
            else:
                x = self.client.local_player.x
                y = self.client.local_player.y
                
        packet = HurtPlayerPacket()
        packet.target_id = player_id
        packet.damage = damage
        packet.x = x
        packet.y = y
        self.client._send_packet(packet)
        
        # Track pending hit
        self.client.combat_manager.add_pending_hit(self.client.local_player.id, player_id)
        
        logger.info(f"Attacked player {player_id} for {damage} damage")
        
    def check_hit(self, x: float, y: float, width: float = 2.0, height: float = 2.0, power: float = 1.0) -> List[int]:
        """Check what objects/players are hit in an area
        
        Args:
            x: Center X position
            y: Center Y position  
            width: Hit area width
            height: Hit area height
            power: Hit power
            
        Returns:
            List of hit object/player IDs
        """
        # Find objects in hit area
        hit_objects = []
        
        # Check players
        for player_id, player in self.client.players.items():
            px = player.x
            py = player.y
            
            # Simple box collision
            if (x - width/2 <= px <= x + width/2 and
                y - height/2 <= py <= y + height/2):
                hit_objects.append(player_id)
                
        # Send hit detection packet
        if hit_objects:
            packet = HitObjectsPacket(x, y, width, height, power)
            self.client._send_packet(packet)
            
            logger.info(f"Hit detection at ({x}, {y}): {len(hit_objects)} objects")
            
        return hit_objects
        
    def create_explosion(self, x: float, y: float, power: float = 1.0, radius: float = 3.0):
        """Create an explosion at position
        
        Args:
            x: X position
            y: Y position
            power: Explosion power
            radius: Explosion radius
        """
        packet = ExplosionPacket()
        packet.x = x
        packet.y = y
        packet.power = power
        packet.radius = radius
        self.client._send_packet(packet)
        
        logger.info(f"Created explosion at ({x}, {y}) with power {power} and radius {radius}")
        
    def hurt_baddy(self, baddy_id: int, damage: float = 1.0):
        """Hurt a baddy/enemy
        
        Args:
            baddy_id: Baddy ID
            damage: Damage amount
        """
        packet = BaddyHurtPacket()
        packet.baddy_id = baddy_id
        packet.damage = damage
        self.client._send_packet(packet)
        
        logger.info(f"Attacked baddy {baddy_id} for {damage} damage")
        
    def sword_attack(self, reach: float = 2.0) -> List[int]:
        """Perform a sword attack in front of player
        
        Args:
            reach: Attack reach
            
        Returns:
            List of hit object IDs
        """
        # Calculate attack position based on direction
        from ..protocol.enums import Direction
        
        x = self.client.local_player.x
        y = self.client.local_player.y
        direction = self.client.local_player.direction
        
        # Offset based on direction
        if direction == Direction.UP:
            y -= reach / 2
        elif direction == Direction.DOWN:
            y += reach / 2
        elif direction == Direction.LEFT:
            x -= reach / 2
        elif direction == Direction.RIGHT:
            x += reach / 2
            
        # Check hit with sword power
        sword_power = getattr(self.client.local_player, 'sword_power', 1)
        return self.check_hit(x, y, reach, reach, sword_power)
        
    def arrow_attack(self, target_x: float, target_y: float, power: float = 1.0) -> List[int]:
        """Shoot arrow at target position
        
        Args:
            target_x: Target X
            target_y: Target Y
            power: Arrow power
            
        Returns:
            List of hit object IDs
        """
        # Calculate arrow path and check hits along the way
        start_x = self.client.local_player.x
        start_y = self.client.local_player.y
        
        # Simple linear path check
        steps = 10
        hit_objects = []
        
        for i in range(1, steps + 1):
            t = i / steps
            check_x = start_x + (target_x - start_x) * t
            check_y = start_y + (target_y - start_y) * t
            
            hits = self.check_hit(check_x, check_y, 0.5, 0.5, power)
            hit_objects.extend(hits)
            
            if hits:  # Stop at first hit
                break
                
        return list(set(hit_objects))  # Remove duplicates
        
    def get_player_health(self, player_id: Optional[int] = None) -> tuple[float, float]:
        """Get player's health
        
        Args:
            player_id: Player ID (None for local player)
            
        Returns:
            Tuple of (current_health, max_health)
        """
        if player_id is None:
            player_id = self.client.local_player.id
            
        return self.client.combat_manager.get_player_health(player_id)
        
    def is_invulnerable(self, player_id: Optional[int] = None) -> bool:
        """Check if player is invulnerable
        
        Args:
            player_id: Player ID (None for local player)
            
        Returns:
            True if invulnerable
        """
        if player_id is None:
            player_id = self.client.local_player.id
            
        return self.client.combat_manager.is_invulnerable(player_id)