"""
Interaction System
==================

Handles object interactions like bushes, pots, rocks, and other destructible/interactive objects.
"""

import pygame
import logging
import time
import random
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

from pyreborn import Client
from .packet_api_compat import OutgoingPacketAPI


logger = logging.getLogger(__name__)


class ObjectType(Enum):
    """Types of interactive objects"""
    BUSH = 1      # Can be cut with sword
    POT = 2       # Can be picked up and thrown
    ROCK = 3      # Can be picked up and thrown
    SIGN = 4      # Can be read
    CHEST = 5     # Can be opened
    BOMB = 6      # Explodes


class ObjectState(Enum):
    """State of an object"""
    INTACT = 1
    BROKEN = 2
    CARRIED = 3
    RESPAWNING = 4


@dataclass
class InteractiveObject:
    """An interactive object in the world"""
    id: int
    type: ObjectType
    x: float
    y: float
    state: ObjectState = ObjectState.INTACT
    carried_by: Optional[int] = None  # Entity ID carrying this object
    respawn_time: float = 30.0  # Seconds to respawn
    destroyed_at: Optional[float] = None
    # Visual properties
    tile_id: int = 0  # Tile ID for rendering
    layer: int = 1    # Render layer (0=ground, 1=objects, 2=overhead)


@dataclass
class CarryState:
    """State of an entity carrying an object"""
    entity_id: int
    object_id: int
    object_type: ObjectType
    pickup_time: float


class InteractionSystem:
    """Manages interactions with world objects"""
    
    def __init__(self, client: Client, packet_api: OutgoingPacketAPI):
        """Initialize interaction system
        
        Args:
            client: PyReborn client for game data
            packet_api: API for sending packets
        """
        self.client = client
        self.packet_api = packet_api
        
        # Objects in the world
        self.objects: Dict[int, InteractiveObject] = {}
        self.next_object_id = 1
        
        # Carry states
        self.carry_states: Dict[int, CarryState] = {}
        
        # Object spawn points (for respawning)
        self.spawn_points: List[dict] = []
        
        # Interaction ranges
        self.INTERACT_RANGE = 1.5  # tiles
        self.THROW_FORCE = 10.0    # tiles/second
        
        # Tile mappings for objects
        self.OBJECT_TILES = {
            ObjectType.BUSH: 500,   # Example tile IDs
            ObjectType.POT: 501,
            ObjectType.ROCK: 502,
            ObjectType.SIGN: 503,
            ObjectType.CHEST: 504,
            ObjectType.BOMB: 505
        }
        
        logger.info("Interaction system initialized")
    
    def spawn_object(self, obj_type: ObjectType, x: float, y: float) -> int:
        """Spawn an interactive object
        
        Args:
            obj_type: Type of object
            x: X position in tiles
            y: Y position in tiles
            
        Returns:
            Object ID
        """
        obj_id = self.next_object_id
        self.next_object_id += 1
        
        obj = InteractiveObject(
            id=obj_id,
            type=obj_type,
            x=x,
            y=y,
            tile_id=self.OBJECT_TILES.get(obj_type, 500)
        )
        
        self.objects[obj_id] = obj
        
        # Add spawn point for respawning
        self.spawn_points.append({
            'type': obj_type,
            'x': x,
            'y': y,
            'object_id': obj_id
        })
        
        logger.debug(f"Spawned {obj_type.name} at ({x}, {y}) with ID {obj_id}")
        return obj_id
    
    def spawn_level_objects(self, level_name: str):
        """Spawn objects for a level based on its content
        
        Args:
            level_name: Name of the level
        """
        # Clear existing objects
        self.objects.clear()
        self.carry_states.clear()
        self.spawn_points.clear()
        self.next_object_id = 1
        
        # Spawn some example objects
        # In a real implementation, this would read from level data
        
        # Spawn bushes
        for i in range(5):
            x = random.randint(10, 50)
            y = random.randint(10, 50)
            self.spawn_object(ObjectType.BUSH, x, y)
        
        # Spawn pots
        for i in range(3):
            x = random.randint(10, 50)
            y = random.randint(10, 50)
            self.spawn_object(ObjectType.POT, x, y)
        
        # Spawn rocks
        for i in range(2):
            x = random.randint(10, 50)
            y = random.randint(10, 50)
            self.spawn_object(ObjectType.ROCK, x, y)
        
        logger.info(f"Spawned {len(self.objects)} objects for level {level_name}")
    
    def interact_with_object(self, entity_id: int, x: float, y: float) -> bool:
        """Attempt to interact with an object at position
        
        Args:
            entity_id: Entity attempting interaction
            x: X position of entity
            y: Y position of entity
            
        Returns:
            True if interaction occurred
        """
        # Find nearest object
        nearest_obj = self._find_nearest_object(x, y, self.INTERACT_RANGE)
        if not nearest_obj:
            return False
        
        # Check if entity is already carrying something
        if entity_id in self.carry_states:
            # Throw the carried object
            self.throw_object(entity_id, x, y)
            return True
        
        # Interact based on object type
        if nearest_obj.type in [ObjectType.POT, ObjectType.ROCK, ObjectType.BOMB]:
            # Pick up object
            self.pickup_object(entity_id, nearest_obj.id)
            return True
        elif nearest_obj.type == ObjectType.SIGN:
            # Read sign
            self._read_sign(nearest_obj)
            return True
        elif nearest_obj.type == ObjectType.CHEST:
            # Open chest
            self._open_chest(nearest_obj)
            return True
        
        return False
    
    def destroy_object(self, obj_id: int, by_sword: bool = False):
        """Destroy an object
        
        Args:
            obj_id: Object ID
            by_sword: Whether destroyed by sword
        """
        if obj_id not in self.objects:
            return
        
        obj = self.objects[obj_id]
        
        # Check if object can be destroyed this way
        if by_sword and obj.type not in [ObjectType.BUSH]:
            return  # Only bushes can be cut
        
        # Mark as broken
        obj.state = ObjectState.BROKEN
        obj.destroyed_at = time.time()
        
        # Drop items or create effects
        self._on_object_destroyed(obj)
        
        logger.info(f"Destroyed {obj.type.name} at ({obj.x}, {obj.y})")
    
    def pickup_object(self, entity_id: int, obj_id: int):
        """Pick up an object
        
        Args:
            entity_id: Entity picking up
            obj_id: Object to pick up
        """
        if obj_id not in self.objects:
            return
        
        obj = self.objects[obj_id]
        
        # Check if object can be picked up
        if obj.type not in [ObjectType.POT, ObjectType.ROCK, ObjectType.BOMB]:
            return
        
        # Check if already carried
        if obj.state == ObjectState.CARRIED:
            return
        
        # Pick up
        obj.state = ObjectState.CARRIED
        obj.carried_by = entity_id
        
        self.carry_states[entity_id] = CarryState(
            entity_id=entity_id,
            object_id=obj_id,
            object_type=obj.type,
            pickup_time=time.time()
        )
        
        # Send carry animation
        if entity_id == -1:  # Local player (entity -1)
            self._send_carry_animation()
        
        logger.info(f"Entity {entity_id} picked up {obj.type.name}")
    
    def throw_object(self, entity_id: int, x: float, y: float):
        """Throw a carried object
        
        Args:
            entity_id: Entity throwing
            x: X position of entity
            y: Y position of entity
        """
        if entity_id not in self.carry_states:
            return
        
        carry_state = self.carry_states[entity_id]
        obj = self.objects.get(carry_state.object_id)
        
        if not obj:
            return
        
        # Get throw direction (based on entity facing)
        direction = self._get_entity_direction(entity_id)
        
        # Calculate throw velocity
        vx, vy = 0, 0
        if direction == 0:  # Up
            vy = -self.THROW_FORCE
        elif direction == 1:  # Left
            vx = -self.THROW_FORCE
        elif direction == 2:  # Down
            vy = self.THROW_FORCE
        elif direction == 3:  # Right
            vx = self.THROW_FORCE
        
        # Drop object in front of entity
        obj.x = x + (vx / self.THROW_FORCE)
        obj.y = y + (vy / self.THROW_FORCE)
        obj.state = ObjectState.INTACT
        obj.carried_by = None
        
        # Remove carry state
        del self.carry_states[entity_id]
        
        # Send throw animation
        if entity_id == -1:  # Local player (entity -1)
            self._send_throw_animation()
        
        # Object will break on impact
        self.destroy_object(obj.id)
        
        logger.info(f"Entity {entity_id} threw {obj.type.name}")
    
    def check_sword_hits(self, attack_x: float, attack_y: float, 
                        attack_range: float, direction: int):
        """Check if sword attack hits any objects
        
        Args:
            attack_x: Attack origin X
            attack_y: Attack origin Y
            attack_range: Attack range
            direction: Attack direction
        """
        for obj_id, obj in list(self.objects.items()):
            if obj.state != ObjectState.INTACT:
                continue
            
            # Check if in range
            dx = obj.x - attack_x
            dy = obj.y - attack_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance > attack_range:
                continue
            
            # Check if in arc
            in_arc = False
            if direction == 0 and dy < 0:  # Up
                in_arc = True
            elif direction == 1 and dx < 0:  # Left
                in_arc = True
            elif direction == 2 and dy > 0:  # Down
                in_arc = True
            elif direction == 3 and dx > 0:  # Right
                in_arc = True
            
            if in_arc:
                # Hit object with sword
                self.destroy_object(obj_id, by_sword=True)
    
    def update(self, dt: float):
        """Update interaction system
        
        Args:
            dt: Delta time in seconds
        """
        current_time = time.time()
        
        # Update carried objects
        for entity_id, carry_state in self.carry_states.items():
            obj = self.objects.get(carry_state.object_id)
            if obj:
                # Update object position to match carrier
                entity_pos = self._get_entity_position(entity_id)
                if entity_pos:
                    obj.x, obj.y = entity_pos
        
        # Respawn destroyed objects
        for obj in self.objects.values():
            if obj.state == ObjectState.BROKEN and obj.destroyed_at:
                if current_time - obj.destroyed_at >= obj.respawn_time:
                    # Respawn object
                    obj.state = ObjectState.INTACT
                    obj.destroyed_at = None
                    
                    # Find original spawn point
                    for spawn in self.spawn_points:
                        if spawn['object_id'] == obj.id:
                            obj.x = spawn['x']
                            obj.y = spawn['y']
                            break
                    
                    logger.debug(f"Respawned {obj.type.name} at ({obj.x}, {obj.y})")
    
    def _find_nearest_object(self, x: float, y: float, max_range: float) -> Optional[InteractiveObject]:
        """Find nearest interactive object
        
        Args:
            x: X position
            y: Y position
            max_range: Maximum range
            
        Returns:
            Nearest object or None
        """
        nearest = None
        nearest_dist = max_range
        
        for obj in self.objects.values():
            if obj.state != ObjectState.INTACT:
                continue
            
            dx = obj.x - x
            dy = obj.y - y
            dist = (dx * dx + dy * dy) ** 0.5
            
            if dist < nearest_dist:
                nearest = obj
                nearest_dist = dist
        
        return nearest
    
    def _get_entity_position(self, entity_id: int) -> Optional[Tuple[float, float]]:
        """Get entity position
        
        Args:
            entity_id: Entity ID
            
        Returns:
            (x, y) position or None
        """
        session_manager = self.client.get_manager('session')
        if not session_manager:
            return None
        
        if entity_id == -1:
            player = session_manager.get_player()
            if player:
                return (player.x, player.y)
        else:
            all_players = session_manager.get_all_players()
            if entity_id in all_players:
                player = all_players[entity_id]
                return (player.x, player.y)
        
        return None
    
    def _get_entity_direction(self, entity_id: int) -> int:
        """Get entity facing direction
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Direction (0=Up, 1=Left, 2=Down, 3=Right)
        """
        # Default to down
        return 2
    
    def _on_object_destroyed(self, obj: InteractiveObject):
        """Handle object destruction effects
        
        Args:
            obj: Destroyed object
        """
        # Could drop items, create particles, etc.
        if obj.type == ObjectType.BUSH:
            # Bushes might drop rupees
            pass
        elif obj.type == ObjectType.POT:
            # Pots might have items inside
            pass
    
    def _send_carry_animation(self):
        """Send carry animation for local player"""
        try:
            # Carry sprite is typically sprite 16-19
            self.packet_api.set_player_properties(sprite=16)
            logger.debug("Sent carry animation")
        except Exception as e:
            logger.error(f"Failed to send carry animation: {e}")
    
    def _send_throw_animation(self):
        """Send throw animation for local player"""
        try:
            # Return to normal sprite
            self.packet_api.set_player_properties(sprite=2)  # Down idle
            logger.debug("Sent throw animation")
        except Exception as e:
            logger.error(f"Failed to send throw animation: {e}")
    
    def _read_sign(self, sign: InteractiveObject):
        """Read a sign
        
        Args:
            sign: Sign object
        """
        logger.info(f"Reading sign at ({sign.x}, {sign.y})")
        # Would display sign text
    
    def _open_chest(self, chest: InteractiveObject):
        """Open a chest
        
        Args:
            chest: Chest object
        """
        logger.info(f"Opening chest at ({chest.x}, {chest.y})")
        # Would give items
    
    def get_visible_objects(self) -> List[InteractiveObject]:
        """Get all visible objects for rendering
        
        Returns:
            List of visible objects
        """
        return [
            obj for obj in self.objects.values()
            if obj.state in [ObjectState.INTACT, ObjectState.CARRIED]
        ]
    
    def is_carrying(self, entity_id: int) -> bool:
        """Check if entity is carrying an object
        
        Args:
            entity_id: Entity to check
            
        Returns:
            True if carrying
        """
        return entity_id in self.carry_states