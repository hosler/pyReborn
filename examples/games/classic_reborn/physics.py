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
                   bush_carrying: bool = False, direction: Direction = None, 
                   is_gmap: bool = False, gmap_handler=None) -> bool:
        """Check if a position is valid for movement
        
        Args:
            x: Target X position in tiles
            y: Target Y position in tiles
            level: Current level
            bush_carrying: Whether player is carrying a bush
            direction: Player's current facing direction
            is_gmap: Whether we're in GMAP mode (allows unlimited movement)
            gmap_handler: GMAP handler for checking adjacent segments
            
        Returns:
            True if movement is allowed
        """
        if not level:
            return False
            
        # Check bounds - in GMAP mode, allow unlimited movement
        if not is_gmap:
            # Regular mode - strict 64x64 boundaries
            if x < 0 or y < 0 or x >= 63 or y >= 63:
                return False
            
        # Check collision for all 4 corners of player
        # Player collision box is offset by 1 tile right and varies by direction
        x_offset = 1.0  # 1 tile right
        y_offset = 1.0  # 1 tile down (base offset)
        
        # Shadow/collision box dimensions - make smaller to stay within boundaries
        shadow_width = 0.5  # Reduced to 0.5 to ensure we stay within segment bounds
        shadow_height = 0.8  # Reduced to 0.8
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
        
        # Clamp check points to stay within segment bounds in GMAP mode
        if is_gmap:
            clamped_points = []
            for check_x, check_y in check_points:
                # Clamp to 0-63.99 range to stay within segment
                clamped_x = max(0, min(63.99, check_x))
                clamped_y = max(0, min(63.99, check_y))
                clamped_points.append((clamped_x, clamped_y))
            check_points = clamped_points
        
        for check_x, check_y in check_points:
            # In GMAP mode, we need to check the correct segment's tiles
            if is_gmap:
                # Convert world coordinates to segment coordinates
                seg_x = int(check_x // 64)
                seg_y = int(check_y // 64)
                local_x = check_x - (seg_x * 64)
                local_y = check_y - (seg_y * 64)
                tile_x = int(local_x)
                tile_y = int(local_y)
                
                # Check if we need to look at a different segment
                if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                    # Check adjacent segment if gmap_handler is available
                    if gmap_handler and hasattr(gmap_handler, 'get_level_object'):
                        current_level_name = gmap_handler.current_level_name
                        if current_level_name:
                            # Parse current segment coordinates
                            segment_info = gmap_handler.parse_segment_name(current_level_name)
                            if segment_info:
                                base_name, curr_seg_x, curr_seg_y = segment_info
                                
                                # Determine which adjacent segment we need
                                direction = None
                                adj_tile_x = tile_x
                                adj_tile_y = tile_y
                                
                                if tile_x < 0:
                                    direction = 'east'  # Moving west from current segment
                                    adj_tile_x = 64 + tile_x  # Wrap to east side of adjacent segment
                                elif tile_x >= 64:
                                    direction = 'west'  # Moving east from current segment  
                                    adj_tile_x = tile_x - 64  # Wrap to west side of adjacent segment
                                elif tile_y < 0:
                                    direction = 'north'  # Moving north from current segment
                                    adj_tile_y = 64 + tile_y  # Wrap to south side of adjacent segment
                                elif tile_y >= 64:
                                    direction = 'south'  # Moving south from current segment
                                    adj_tile_y = tile_y - 64  # Wrap to north side of adjacent segment
                                
                                if direction:
                                    # Get adjacent level in that direction
                                    target_segment_name = gmap_handler.get_adjacent_level(current_level_name, direction)
                                    if target_segment_name:
                                        target_level = gmap_handler.get_level_object(target_segment_name)
                                        if target_level and 0 <= adj_tile_x < 64 and 0 <= adj_tile_y < 64:
                                            adj_tile_id = target_level.get_board_tile_id(adj_tile_x, adj_tile_y)
                                            if self.tile_defs.is_blocking(adj_tile_id):
                                                print(f"[PHYSICS DEBUG] Blocking tile {adj_tile_id} in adjacent segment {target_segment_name} at ({adj_tile_x}, {adj_tile_y}) - direction {direction}")
                                                return False
                                            continue
                    
                    # No adjacent segment or tile available - allow movement at boundary
                    continue
                    
                # Check tile in current segment
                level_to_check = level
            else:
                tile_x = int(check_x)
                tile_y = int(check_y)
                
                # Regular bounds check
                if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                    return False
                    
                level_to_check = level
                
            tile_id = level_to_check.get_board_tile_id(tile_x, tile_y)
            
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