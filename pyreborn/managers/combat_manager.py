"""
Combat management system for PyReborn
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class DamageEvent:
    """Represents a damage event"""
    attacker_id: int
    target_id: int
    damage: float
    timestamp: float
    weapon: Optional[str] = None


@dataclass
class HitBox:
    """Represents a hit detection area"""
    x: float
    y: float
    width: float
    height: float
    
    def contains(self, px: float, py: float) -> bool:
        """Check if point is in hitbox"""
        return (self.x <= px <= self.x + self.width and 
                self.y <= py <= self.y + self.height)
                
    def intersects(self, other: 'HitBox') -> bool:
        """Check if two hitboxes intersect"""
        return not (self.x > other.x + other.width or
                   self.x + self.width < other.x or
                   self.y > other.y + other.height or
                   self.y + self.height < other.y)


class CombatManager:
    """Manages combat and damage systems"""
    
    def __init__(self):
        # Player health tracking
        self._player_health: Dict[int, float] = {}
        self._player_max_health: Dict[int, float] = {}
        
        # Damage history
        self._damage_events: List[DamageEvent] = []
        
        # Invulnerability tracking
        self._invulnerable: Dict[int, float] = {}  # player_id -> end_time
        
        # Active hitboxes
        self._hitboxes: Dict[str, Tuple[HitBox, float]] = {}  # id -> (hitbox, expire_time)
        
        # Hit confirmations
        self._pending_hits: Set[Tuple[int, int]] = set()  # (attacker, target) pairs
        
    def set_player_health(self, player_id: int, health: float, max_health: Optional[float] = None):
        """Set player's health"""
        self._player_health[player_id] = health
        if max_health is not None:
            self._player_max_health[player_id] = max_health
        logger.debug(f"Set player {player_id} health to {health}/{max_health or self._player_max_health.get(player_id, 3)}")
        
    def get_player_health(self, player_id: int) -> Tuple[float, float]:
        """Get player's current and max health"""
        current = self._player_health.get(player_id, 3.0)
        maximum = self._player_max_health.get(player_id, 3.0)
        return current, maximum
        
    def apply_damage(self, attacker_id: int, target_id: int, damage: float, weapon: Optional[str] = None) -> bool:
        """Apply damage to a player, returns True if successful"""
        # Check invulnerability
        if self.is_invulnerable(target_id):
            logger.debug(f"Player {target_id} is invulnerable")
            return False
            
        # Apply damage
        current_health = self._player_health.get(target_id, 3.0)
        new_health = max(0, current_health - damage)
        self._player_health[target_id] = new_health
        
        # Record event
        event = DamageEvent(attacker_id, target_id, damage, time.time(), weapon)
        self._damage_events.append(event)
        
        # Set invulnerability (0.5 seconds)
        self.set_invulnerable(target_id, 0.5)
        
        logger.info(f"Player {attacker_id} dealt {damage} damage to {target_id} (health: {current_health} -> {new_health})")
        return True
        
    def heal_player(self, player_id: int, amount: float):
        """Heal a player"""
        current = self._player_health.get(player_id, 3.0)
        maximum = self._player_max_health.get(player_id, 3.0)
        new_health = min(maximum, current + amount)
        self._player_health[player_id] = new_health
        logger.debug(f"Healed player {player_id} for {amount} (health: {current} -> {new_health})")
        
    def is_dead(self, player_id: int) -> bool:
        """Check if player is dead"""
        return self._player_health.get(player_id, 3.0) <= 0
        
    def set_invulnerable(self, player_id: int, duration: float):
        """Make player invulnerable for duration seconds"""
        self._invulnerable[player_id] = time.time() + duration
        
    def is_invulnerable(self, player_id: int) -> bool:
        """Check if player is invulnerable"""
        return time.time() < self._invulnerable.get(player_id, 0)
        
    def create_hitbox(self, hitbox_id: str, x: float, y: float, width: float, height: float, duration: float = 0.1):
        """Create a hitbox that expires after duration"""
        hitbox = HitBox(x, y, width, height)
        expire_time = time.time() + duration
        self._hitboxes[hitbox_id] = (hitbox, expire_time)
        logger.debug(f"Created hitbox {hitbox_id} at ({x}, {y}) size ({width}, {height})")
        
    def check_hit(self, x: float, y: float, width: float = 1.0, height: float = 1.5) -> List[int]:
        """Check what players are hit by an area, returns list of player IDs"""
        # This would need access to player positions
        # For now, return empty list - actual implementation would check collisions
        return []
        
    def cleanup_expired(self):
        """Remove expired hitboxes and old damage events"""
        current_time = time.time()
        
        # Remove expired hitboxes
        expired = [hid for hid, (_, expire) in self._hitboxes.items() if expire < current_time]
        for hid in expired:
            del self._hitboxes[hid]
            
        # Remove old damage events (keep last 100)
        if len(self._damage_events) > 100:
            self._damage_events = self._damage_events[-100:]
            
    def get_recent_damage_events(self, seconds: float = 5.0) -> List[DamageEvent]:
        """Get damage events from the last N seconds"""
        cutoff = time.time() - seconds
        return [e for e in self._damage_events if e.timestamp > cutoff]
        
    def add_pending_hit(self, attacker_id: int, target_id: int):
        """Add a pending hit confirmation"""
        self._pending_hits.add((attacker_id, target_id))
        
    def confirm_hit(self, attacker_id: int, target_id: int) -> bool:
        """Confirm a pending hit"""
        pair = (attacker_id, target_id)
        if pair in self._pending_hits:
            self._pending_hits.remove(pair)
            return True
        return False
        
    def reset_player(self, player_id: int):
        """Reset player's combat state"""
        self._player_health[player_id] = 3.0
        self._player_max_health[player_id] = 3.0
        if player_id in self._invulnerable:
            del self._invulnerable[player_id]