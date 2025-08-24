"""
Combat System
=============

Handles sword combat, damage, and combat effects.
"""

import pygame
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from pyreborn import Client
from .packet_api_compat import OutgoingPacketAPI


logger = logging.getLogger(__name__)


class WeaponType(Enum):
    """Types of weapons"""
    NONE = 0
    SWORD = 1
    BOW = 2
    BOMB = 3


@dataclass
class AttackState:
    """State of an ongoing attack"""
    entity_id: int
    weapon_type: WeaponType
    direction: int  # 0=Up, 1=Left, 2=Down, 3=Right
    start_time: float
    duration: float
    damage: int
    hit_entities: set  # Entities already hit by this attack


class CombatSystem:
    """Manages combat mechanics and sword swinging"""
    
    def __init__(self, client: Client, packet_api: OutgoingPacketAPI):
        """Initialize combat system
        
        Args:
            client: PyReborn client for game data
            packet_api: API for sending packets
        """
        self.client = client
        self.packet_api = packet_api
        
        # Attack states
        self.active_attacks: Dict[int, AttackState] = {}
        
        # Combat constants
        self.SWORD_DAMAGE = 1
        self.SWORD_RANGE = 2.0  # tiles
        self.SWORD_ARC = 90  # degrees
        self.SWORD_DURATION = 0.3  # seconds
        
        # Cooldowns
        self.attack_cooldowns: Dict[int, float] = {}
        self.ATTACK_COOLDOWN = 0.5  # seconds between attacks
        
        # Visual effects (for rendering)
        self.sword_swings: List[dict] = []  # Visual sword swing effects
        
        logger.info("Combat system initialized")
    
    def perform_attack(self, entity_id: int, direction: int, weapon_type: WeaponType = WeaponType.SWORD):
        """Perform an attack
        
        Args:
            entity_id: Entity performing the attack
            direction: Direction of attack (0=Up, 1=Left, 2=Down, 3=Right)
            weapon_type: Type of weapon
        """
        current_time = time.time()
        
        # Check cooldown
        if entity_id in self.attack_cooldowns:
            if current_time - self.attack_cooldowns[entity_id] < self.ATTACK_COOLDOWN:
                logger.debug(f"Attack on cooldown for entity {entity_id}")
                return
        
        # Create attack state
        attack = AttackState(
            entity_id=entity_id,
            weapon_type=weapon_type,
            direction=direction,
            start_time=current_time,
            duration=self.SWORD_DURATION,
            damage=self.SWORD_DAMAGE,
            hit_entities=set()
        )
        
        self.active_attacks[entity_id] = attack
        self.attack_cooldowns[entity_id] = current_time
        
        # Send attack packet for local player
        if entity_id == -1:  # Local player (entity -1)
            self._send_sword_attack(direction)
        
        # Add visual effect
        self._add_sword_swing_effect(entity_id, direction)
        
        # Check for object hits if we have interaction system
        if hasattr(self.client, 'interaction_system'):
            position = self._get_entity_position(entity_id)
            if position:
                x, y = position
                self.client.interaction_system.check_sword_hits(x, y, self.SWORD_RANGE, direction)
        
        logger.info(f"Entity {entity_id} performed {weapon_type.name} attack in direction {direction}")
    
    def _send_sword_attack(self, direction: int):
        """Send sword attack packet to server
        
        Args:
            direction: Direction of attack
        """
        try:
            # Send sword swing animation sprite
            # Attack sprites typically start at sprite 8
            attack_sprite = 8 + direction
            
            # Send the attack sprite
            self.packet_api.set_player_properties(sprite=attack_sprite)
            
            # Also send sword usage packet if available
            if hasattr(self.packet_api, 'use_sword'):
                self.packet_api.use_sword(direction)
            
            logger.debug(f"Sent sword attack: direction={direction}, sprite={attack_sprite}")
            
        except Exception as e:
            logger.error(f"Failed to send sword attack: {e}")
    
    def _add_sword_swing_effect(self, entity_id: int, direction: int):
        """Add visual sword swing effect
        
        Args:
            entity_id: Entity swinging sword
            direction: Direction of swing
        """
        # Get entity position
        position = self._get_entity_position(entity_id)
        if not position:
            return
        
        x, y = position
        
        # Calculate sword swing area based on direction
        if direction == 0:  # Up
            effect_x = x
            effect_y = y - 1
            effect_width = 1
            effect_height = self.SWORD_RANGE
        elif direction == 1:  # Left
            effect_x = x - self.SWORD_RANGE
            effect_y = y
            effect_width = self.SWORD_RANGE
            effect_height = 1
        elif direction == 2:  # Down
            effect_x = x
            effect_y = y + 1
            effect_width = 1
            effect_height = self.SWORD_RANGE
        else:  # Right
            effect_x = x + 1
            effect_y = y
            effect_width = self.SWORD_RANGE
            effect_height = 1
        
        # Add effect
        self.sword_swings.append({
            'x': effect_x,
            'y': effect_y,
            'width': effect_width,
            'height': effect_height,
            'start_time': time.time(),
            'duration': self.SWORD_DURATION,
            'direction': direction
        })
    
    def update(self, dt: float):
        """Update combat system
        
        Args:
            dt: Delta time in seconds
        """
        current_time = time.time()
        
        # Update active attacks
        completed_attacks = []
        for entity_id, attack in list(self.active_attacks.items()):
            # Check if attack expired
            if current_time - attack.start_time >= attack.duration:
                completed_attacks.append(entity_id)
                continue
            
            # Check for hits (only once per frame per attack)
            self._check_attack_hits(attack)
        
        # Remove completed attacks
        for entity_id in completed_attacks:
            del self.active_attacks[entity_id]
        
        # Update visual effects
        self.sword_swings = [
            effect for effect in self.sword_swings
            if current_time - effect['start_time'] < effect['duration']
        ]
    
    def _check_attack_hits(self, attack: AttackState):
        """Check if attack hits any entities
        
        Args:
            attack: Attack state to check
        """
        # Get attacker position
        attacker_pos = self._get_entity_position(attack.entity_id)
        if not attacker_pos:
            return
        
        ax, ay = attacker_pos
        
        # Get all nearby entities
        session_manager = self.client.get_manager('session')
        if not session_manager:
            return
        
        all_players = session_manager.get_all_players()
        
        for player_id, player in all_players.items():
            # Skip self and already hit entities
            if player_id == attack.entity_id or player_id in attack.hit_entities:
                continue
            
            # Check if in range
            dx = player.x - ax
            dy = player.y - ay
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance > self.SWORD_RANGE:
                continue
            
            # Check if in arc (simplified - just check if in front)
            in_arc = False
            if attack.direction == 0 and dy < 0:  # Up
                in_arc = True
            elif attack.direction == 1 and dx < 0:  # Left
                in_arc = True
            elif attack.direction == 2 and dy > 0:  # Down
                in_arc = True
            elif attack.direction == 3 and dx > 0:  # Right
                in_arc = True
            
            if in_arc:
                # Hit detected!
                attack.hit_entities.add(player_id)
                self._on_hit(attack.entity_id, player_id, attack.damage)
    
    def _on_hit(self, attacker_id: int, target_id: int, damage: int):
        """Handle hit detection
        
        Args:
            attacker_id: Entity that performed the attack
            target_id: Entity that was hit
            damage: Damage amount
        """
        logger.info(f"Hit! {attacker_id} hit {target_id} for {damage} damage")
        
        # Send damage packet if this is local player's attack
        if attacker_id == 0:
            # Send hurt packet or damage notification
            # This depends on server implementation
            pass
        
        # Add hit effect (for visual feedback)
        # This would be rendered by the rendering system
    
    def _get_entity_position(self, entity_id: int) -> Optional[Tuple[float, float]]:
        """Get entity position
        
        Args:
            entity_id: Entity ID
            
        Returns:
            (x, y) position or None
        """
        if entity_id == -1:
            # Local player
            session_manager = self.client.get_manager('session')
            if session_manager:
                player = session_manager.get_player()
                if player:
                    return (player.x, player.y)
        else:
            # Other player
            session_manager = self.client.get_manager('session')
            if session_manager:
                all_players = session_manager.get_all_players()
                if entity_id in all_players:
                    player = all_players[entity_id]
                    return (player.x, player.y)
        
        return None
    
    def get_sword_effects(self) -> List[dict]:
        """Get active sword swing effects for rendering
        
        Returns:
            List of sword swing effect dictionaries
        """
        return self.sword_swings.copy()
    
    def is_attacking(self, entity_id: int) -> bool:
        """Check if entity is currently attacking
        
        Args:
            entity_id: Entity to check
            
        Returns:
            True if entity is attacking
        """
        return entity_id in self.active_attacks