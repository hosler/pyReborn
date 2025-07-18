"""
Physics Module - Handles collision detection and movement validation
"""

from typing import Tuple, Optional, List
from pyreborn.models.level import Level
from pyreborn.protocol.enums import Direction
from tile_defs import TileDefs


class Physics:
    """Handles collision detection and physics"""
    
    def __init__(self, tile_defs: TileDefs):
        """Initialize physics system
        
        Args:
            tile_defs: Tile definitions for collision checking
        """
        self.tile_defs = tile_defs
        
    def can_move_to(self, x: float, y: float, level: Level, 
                   bush_carrying: bool = False, direction: Direction = None) -> bool:
        """Check if a position is valid for movement
        
        Args:
            x: Target X position in tiles
            y: Target Y position in tiles
            level: Current level
            bush_carrying: Whether player is carrying a bush
            direction: Player's current facing direction
            
        Returns:
            True if movement is allowed
        """
        if not level:
            return False
            
        # Check bounds
        if x < 0 or y < 0 or x >= 63 or y >= 63:
            return False
            
        # Check collision for all 4 corners of player
        # Player collision box is offset by 1 tile right and varies by direction
        x_offset = 1.0  # 1 tile right
        y_offset = 1.0  # 1 tile down (base offset)
        
        # Shadow/collision box dimensions
        shadow_width = 1.2
        shadow_height = 1.6  # Taller box for all directions (was 0.6, now 1.6)
        shadow_x_start = 0.1  # slight offset within the shadow
        
        # Direction-specific adjustments
        if direction == Direction.LEFT:
            x_offset -= 3.0 / 16.0  # 3 pixels left (3/16 of a tile)
        
        check_points = [
            (x + x_offset + shadow_x_start, y + y_offset),                    # Top-left of shadow
            (x + x_offset + shadow_x_start + shadow_width, y + y_offset),     # Top-right of shadow
            (x + x_offset + shadow_x_start, y + y_offset + shadow_height),    # Bottom-left
            (x + x_offset + shadow_x_start + shadow_width, y + y_offset + shadow_height), # Bottom-right
            (x + x_offset + 0.5, y + y_offset + shadow_height/2),             # Center of shadow
        ]
        
        for check_x, check_y in check_points:
            tile_x = int(check_x)
            tile_y = int(check_y)
            
            # Bounds check
            if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                return False
                
            tile_id = level.get_board_tile_id(tile_x, tile_y)
            
            # Check blocking tiles
            if self.tile_defs.is_blocking(tile_id):
                return False
                
        return True
        
    def check_tile_at_position(self, x: float, y: float, level: Level) -> int:
        """Get the tile ID at a specific position
        
        Args:
            x: X position in tiles
            y: Y position in tiles
            level: Current level
            
        Returns:
            Tile ID at position, or -1 if out of bounds
        """
        if not level:
            return -1
            
        tile_x = int(x)
        tile_y = int(y)
        
        if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
            return -1
            
        return level.get_board_tile_id(tile_x, tile_y)
        
    def is_in_water(self, x: float, y: float, level: Level) -> bool:
        """Check if position is in water
        
        Args:
            x: X position in tiles
            y: Y position in tiles
            level: Current level
            
        Returns:
            True if in water
        """
        if not level:
            return False
            
        # Check the tiles at player's feet
        check_points = [
            (x + 0.2, y + 0.8),  # Bottom-left
            (x + 0.8, y + 0.8),  # Bottom-right
            (x + 0.5, y + 0.9),  # Bottom center
        ]
        
        for check_x, check_y in check_points:
            tile_id = self.check_tile_at_position(check_x, check_y, level)
            if tile_id >= 0 and self.tile_defs.is_water(tile_id):
                return True
                
        return False
        
    def is_on_chair(self, x: float, y: float, level: Level) -> bool:
        """Check if position is on a chair
        
        Args:
            x: X position in tiles
            y: Y position in tiles
            level: Current level
            
        Returns:
            True if on a chair
        """
        if not level:
            return False
            
        # Check center of player position
        tile_id = self.check_tile_at_position(x + 0.5, y + 0.5, level)
        return tile_id >= 0 and self.tile_defs.is_chair(tile_id)
        
    def get_sword_hit_positions(self, x: float, y: float, direction: int) -> List[Tuple[float, float]]:
        """Get positions that a sword swing would hit
        
        Args:
            x: Player X position
            y: Player Y position
            direction: Direction player is facing
            
        Returns:
            List of (x, y) positions the sword hits
        """
        # Direction constants
        UP = 0
        DOWN = 2
        LEFT = 1
        RIGHT = 3
        
        # Sword reaches 1 tile in front, covering 2 tile width
        hit_positions = []
        
        if direction == UP:
            hit_positions = [(x, y - 1), (x + 1, y - 1)]
        elif direction == DOWN:
            hit_positions = [(x, y + 1), (x + 1, y + 1)]
        elif direction == LEFT:
            hit_positions = [(x - 1, y), (x - 1, y + 1)]
        elif direction == RIGHT:
            hit_positions = [(x + 1, y), (x + 1, y + 1)]
            
        return hit_positions
        
    def get_grab_check_positions(self, x: float, y: float, direction: int) -> List[Tuple[float, float]]:
        """Get positions to check for grabbable objects
        
        Args:
            x: Player X position
            y: Player Y position
            direction: Direction player is facing
            
        Returns:
            List of (x, y) positions to check
        """
        # Direction offsets
        dx = dy = 0
        if direction == 0:  # UP
            dy = -1
        elif direction == 2:  # DOWN
            dy = 1
        elif direction == 1:  # LEFT
            dx = -1
        elif direction == 3:  # RIGHT
            dx = 1
            
        # Check from player center at multiple distances
        base_x = x + 0.5
        base_y = y + 0.5
        
        positions = []
        for distance in [0.5, 0.8, 1.0]:
            check_x = base_x + dx * distance
            check_y = base_y + dy * distance
            positions.append((check_x, check_y))
            
        return positions
        
    def check_chest_collision(self, player_x: float, player_y: float, 
                            chest_x: int, chest_y: int) -> bool:
        """Check if player collides with a 2x2 chest
        
        Args:
            player_x: Player X position
            player_y: Player Y position
            chest_x: Chest X position
            chest_y: Chest Y position
            
        Returns:
            True if player overlaps with chest
        """
        # Check if player's bounding box overlaps with 2x2 chest
        return (player_x < chest_x + 2 and player_x + 1 > chest_x and
                player_y < chest_y + 2 and player_y + 1 > chest_y)