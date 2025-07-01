#!/usr/bin/env python3
"""
Bush Handler - Manages bush pickup and throwing mechanics
"""

import time
import math
from typing import Optional, Tuple, List
from dataclasses import dataclass
from pyreborn.protocol.enums import Direction

@dataclass
class ThrownBush:
    """Represents a bush that has been thrown"""
    x: float
    y: float
    velocity_x: float
    velocity_y: float
    start_time: float
    start_x: float
    start_y: float
    
    def get_position(self, current_time: float) -> Tuple[float, float]:
        """Get current position of thrown bush"""
        elapsed = current_time - self.start_time
        x = self.start_x + self.velocity_x * elapsed
        y = self.start_y + self.velocity_y * elapsed
        return x, y
    
    def get_distance_traveled(self, current_time: float) -> float:
        """Get distance traveled from start position"""
        x, y = self.get_position(current_time)
        dx = x - self.start_x
        dy = y - self.start_y
        return math.sqrt(dx * dx + dy * dy)

class BushHandler:
    """Handles bush pickup and throwing mechanics"""
    
    # Bush tile IDs
    BUSH_TILES = {2, 3, 18, 19}
    
    # Throwing parameters - more violent!
    THROW_SPEED = 20.0  # tiles per second (was 8)
    MAX_THROW_DISTANCE = 10.0  # tiles (was 5)
    
    def __init__(self):
        self.carrying_bush = False
        self.thrown_bushes: List[ThrownBush] = []
        self.bush_explosions: List[Tuple[float, float, float]] = []  # x, y, time
        
    def is_bush_tile(self, tile_id: int) -> bool:
        """Check if a tile is a bush"""
        return tile_id in self.BUSH_TILES
    
    def check_grabbable_at_position(self, level, tile_defs, x: float, y: float) -> Optional[Tuple[int, int]]:
        """Check if there's a grabbable (blocking) tile at the given position
        
        Returns:
            Tuple of (tile_x, tile_y) if grabbable tile found, None otherwise
        """
        # Check the tile at position
        tile_x = int(x)
        tile_y = int(y)
        
        if 0 <= tile_x < 64 and 0 <= tile_y < 64:
            tile_id = level.get_board_tile_id(tile_x, tile_y)
            # Only blocking tiles can be grabbed
            if tile_defs.is_blocking(tile_id):
                # For now, only bushes can actually be picked up
                if self.is_bush_tile(tile_id):
                    return (tile_x, tile_y)
                    
        return None
    
    def try_pickup_bush(self, level, tile_defs, player_x: float, player_y: float, direction: Direction) -> Optional[Tuple[int, int]]:
        """Try to pick up a bush in front of the player
        
        Returns:
            Bush position (tile_x, tile_y) if bush was picked up, None otherwise
        """
        if self.carrying_bush:
            return None
            
        # Calculate position in front of player based on direction
        dx, dy = 0, 0
        if direction == Direction.UP:
            dy = -1
        elif direction == Direction.DOWN:
            dy = 1
        elif direction == Direction.LEFT:
            dx = -1
        elif direction == Direction.RIGHT:
            dx = 1
            
        check_x = player_x + dx
        check_y = player_y + dy
        
        grabbable_pos = self.check_grabbable_at_position(level, tile_defs, check_x, check_y)
        if grabbable_pos:
            # Pick up the tile (for now only bushes)
            tile_x, tile_y = grabbable_pos
            self.carrying_bush = True
            return (tile_x, tile_y)
            
        return None
    
    def throw_bush(self, player_x: float, player_y: float, direction: Direction):
        """Throw the carried bush"""
        if not self.carrying_bush:
            return
            
        # Calculate throw velocity based on direction
        velocity_x, velocity_y = 0, 0
        if direction == Direction.UP:
            velocity_y = -self.THROW_SPEED
        elif direction == Direction.DOWN:
            velocity_y = self.THROW_SPEED
        elif direction == Direction.LEFT:
            velocity_x = -self.THROW_SPEED
        elif direction == Direction.RIGHT:
            velocity_x = self.THROW_SPEED
            
        # Create thrown bush
        thrown_bush = ThrownBush(
            x=player_x,
            y=player_y,
            velocity_x=velocity_x,
            velocity_y=velocity_y,
            start_time=time.time(),
            start_x=player_x,
            start_y=player_y
        )
        
        self.thrown_bushes.append(thrown_bush)
        self.carrying_bush = False
    
    def update_thrown_bushes(self, level, tile_defs, current_time: float):
        """Update all thrown bushes and check for collisions"""
        bushes_to_remove = []
        
        for i, bush in enumerate(self.thrown_bushes):
            # Get current position
            x, y = bush.get_position(current_time)
            
            # Check if traveled max distance
            if bush.get_distance_traveled(current_time) >= self.MAX_THROW_DISTANCE:
                self.explode_bush(x, y, current_time)
                bushes_to_remove.append(i)
                continue
                
            # Check collision with blocking tiles
            tile_x = int(x)
            tile_y = int(y)
            
            if tile_x < 0 or tile_y < 0 or tile_x >= 64 or tile_y >= 64:
                # Out of bounds
                self.explode_bush(x, y, current_time)
                bushes_to_remove.append(i)
                continue
                
            tile_id = level.get_board_tile_id(tile_x, tile_y)
            tile_type = tile_defs.get_tile_type(tile_id)
            
            # Check if hit a blocking tile (but can go through throw-through tiles)
            if tile_defs.is_blocking(tile_id) and tile_type != tile_defs.THROW_THROUGH:
                self.explode_bush(x, y, current_time)
                bushes_to_remove.append(i)
                continue
        
        # Remove exploded bushes
        for i in reversed(bushes_to_remove):
            self.thrown_bushes.pop(i)
    
    def explode_bush(self, x: float, y: float, time: float):
        """Create a bush explosion effect"""
        self.bush_explosions.append((x, y, time))
    
    def update_explosions(self, current_time: float):
        """Remove old explosion effects"""
        self.bush_explosions = [(x, y, t) for x, y, t in self.bush_explosions 
                                if current_time - t < 0.5]  # Explosions last 0.5 seconds