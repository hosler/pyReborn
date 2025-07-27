"""
Physics Module - Handles collision detection and movement validation
"""

from typing import Tuple, Optional, List
from pyreborn.models.level import Level
from pyreborn.protocol.enums import Direction
from parsers.tiledefs import TileDefs


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
            x: Target X position in tiles (world coords if is_gmap)
            y: Target Y position in tiles (world coords if is_gmap)
            level: Current level
            bush_carrying: Whether player is carrying a bush
            direction: Player's current facing direction
            is_gmap: Whether we're in GMAP mode (allows unlimited movement)
            gmap_handler: GMAP handler for checking adjacent segments
            
        Returns:
            True if movement is allowed
        """
        
        # Debug what coordinates we received
        if is_gmap:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[PHYSICS] can_move_to called with GMAP coords: ({x:.1f}, {y:.1f}), is_gmap={is_gmap}")
        if not level:
            return False
            
        # Check bounds
        if not is_gmap:
            # Regular mode - strict 64x64 boundaries
            if x < 0 or y < 0 or x >= 63 or y >= 63:
                return False
        else:
            # GMAP mode - no bounds checking, we can move across segments
            # The connection manager will handle level transitions
            if x > 61 or y > 61 or x < 3 or y < 3:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[PHYSICS] GMAP movement check at boundary: player at ({x:.1f}, {y:.1f})")
            
        # Check collision for all 4 corners of player
        # Player collision box is offset by 1 tile right and varies by direction
        x_offset = 1.0  # 1 tile right
        y_offset = 1.0  # 1 tile down (base offset)
        
        # Shadow/collision box dimensions - make smaller to stay within boundaries
        shadow_width = 0.5  # Reduced to 0.5 to ensure we stay within segment bounds
        shadow_height = 0.8  # Reduced to 0.8
        shadow_x_start = 0.1  # slight offset within the shadow
        
        # Debug collision box position for movement near boundaries
        if (is_gmap and (x % 64 > 61 or y % 64 > 61)) or (not is_gmap and (x > 61 or y > 61)):
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[PHYSICS] Player trying to move to ({x:.1f}, {y:.1f})")
            logger.info(f"[PHYSICS] Collision box will extend from ({x + x_offset + shadow_x_start:.1f}, {y + y_offset:.1f}) to ({x + x_offset + shadow_x_start + shadow_width:.1f}, {y + y_offset + shadow_height:.1f})")
        
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
        
        # In GMAP mode, we don't clamp - we need to check adjacent segments
        
        for check_x, check_y in check_points:
            # In GMAP mode, we need to check the correct segment's tiles
            if is_gmap and gmap_handler:
                # Debug first collision point near boundaries
                if x > 61 or y > 61:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"[PHYSICS] Checking collision point: ({check_x:.2f}, {check_y:.2f}) for player at ({x:.1f}, {y:.1f})")
                # For GMAP, we're now using world coordinates
                # Convert world coordinates to segment + local
                seg_x = int(check_x // 64)
                seg_y = int(check_y // 64)
                tile_x = int(check_x - (seg_x * 64))
                tile_y = int(check_y - (seg_y * 64))
                
                # Debug when collision point extends to next segment
                if x > 61 and (tile_x >= 64 or seg_x > int(x // 64)):
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"[PHYSICS] Collision point ({check_x:.1f}, {check_y:.1f}) extends to next segment [{seg_x}, {seg_y}], tile ({tile_x}, {tile_y})")
                
                # Debug logging for boundary issues
                if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"[PHYSICS] Collision point crosses segment boundary: world ({check_x:.2f}, {check_y:.2f}) -> seg [{seg_x}, {seg_y}] tile ({tile_x}, {tile_y})")
                    logger.info(f"[PHYSICS] Player trying to move to: ({x:.2f}, {y:.2f})")
                    logger.info(f"[PHYSICS] GMAP dimensions known: {gmap_handler.gmap_width}x{gmap_handler.gmap_height}")
                    logger.info(f"[PHYSICS] Collision check will need adjacent segment")
                
                # Get the level at these segment coordinates
                if gmap_handler:
                    # Build segment name from coordinates
                    base_name = gmap_handler.current_gmap.replace('.gmap', '')
                    
                    # Check if segment coordinates are valid
                    if seg_x < 0 or seg_y < 0:
                        # Outside GMAP bounds - block movement
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"[PHYSICS] Outside GMAP bounds: segment [{seg_x}, {seg_y}]")
                        return False
                    
                    # Check GMAP dimensions if available
                    if hasattr(gmap_handler, 'gmap_width') and hasattr(gmap_handler, 'gmap_height'):
                        if seg_x >= gmap_handler.gmap_width or seg_y >= gmap_handler.gmap_height:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.info(f"[PHYSICS] Outside GMAP bounds: segment [{seg_x}, {seg_y}] exceeds GMAP size ({gmap_handler.gmap_width}x{gmap_handler.gmap_height})")
                            return False
                    
                    # Get the segment name from GMAP data
                    segment_name = None
                    if hasattr(gmap_handler, 'connection_gmap_data'):
                        # Look for the GMAP data (check both formats)
                        gmap_key = f"{base_name}.gmap" if f"{base_name}.gmap" in gmap_handler.connection_gmap_data else base_name
                        if gmap_key in gmap_handler.connection_gmap_data:
                            position_map = gmap_handler.connection_gmap_data[gmap_key].get('position_map', {})
                            segment_name = position_map.get((seg_x, seg_y))
                            if x > 125 or y > 125:  # Debug near boundaries
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.info(f"[PHYSICS] Looking up segment [{seg_x}, {seg_y}] -> {segment_name}")
                    
                    if not segment_name:
                        # Fallback to constructing name (shouldn't happen with proper GMAP data)
                        segment_name = f"{base_name}{seg_x + seg_y * 3 + 1}.nw"  # Simple numbering for chicken
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"[PHYSICS] No GMAP data, guessing segment name: {segment_name}")
                    
                    # Get the level object
                    target_level = gmap_handler.get_level_object(segment_name)
                    
                    # Debug which segment we're checking
                    if x > 125 or y > 125 or x < 65:  # Near segment boundaries in world coords
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"[PHYSICS] Checking segment {segment_name} for collision at tile ({tile_x}, {tile_y})")
                        logger.info(f"[PHYSICS] Target level loaded: {target_level is not None}")
                        logger.info(f"[PHYSICS] Tile coordinates valid: {0 <= tile_x < 64 and 0 <= tile_y < 64}")
                    
                    if target_level and 0 <= tile_x < 64 and 0 <= tile_y < 64:
                        tile_id = target_level.get_board_tile_id(tile_x, tile_y)
                        if self.tile_defs.is_blocking(tile_id):
                            import logging
                            logger = logging.getLogger(__name__)  
                            logger.info(f"[PHYSICS] Blocked by tile {tile_id} at world ({check_x:.2f}, {check_y:.2f}), segment {segment_name}, tile ({tile_x}, {tile_y})")
                            return False
                    elif not target_level:
                        # Level not loaded - allow movement (it will be loaded when we move there)
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"[PHYSICS] Segment {segment_name} not loaded, allowing movement to trigger load")
                        # Continue checking other points
                        continue
            else:
                # Non-GMAP mode - use local coordinates
                tile_x = int(check_x)
                tile_y = int(check_y)
                
                # Regular bounds check
                if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                    return False
                    
                # Check blocking tiles in current level
                tile_id = level.get_board_tile_id(tile_x, tile_y)
                if self.tile_defs.is_blocking(tile_id):
                    return False
                
        return True
        
    def check_tile_at_position(self, x: float, y: float, level: Level, is_gmap: bool = False, gmap_handler=None) -> int:
        """Get the tile ID at a specific position
        
        Args:
            x: X position in tiles (world coords if is_gmap)
            y: Y position in tiles (world coords if is_gmap)
            level: Current level
            is_gmap: Whether we're in GMAP mode
            gmap_handler: GMAP handler for checking adjacent segments
            
        Returns:
            Tile ID at position, or -1 if out of bounds
        """
        if not level:
            return -1
            
        if is_gmap and gmap_handler:
            # World coordinates - convert to segment + local
            seg_x = int(x // 64)
            seg_y = int(y // 64)
            tile_x = int(x - (seg_x * 64))
            tile_y = int(y - (seg_y * 64))
            
            # Get the level at these segment coordinates
            base_name = gmap_handler.current_gmap.replace('.gmap', '')
            segment_name = f"{base_name}-{chr(ord('a') + seg_x)}{seg_y}.nw"
            
            target_level = gmap_handler.get_level_object(segment_name)
            if target_level and 0 <= tile_x < 64 and 0 <= tile_y < 64:
                return target_level.get_board_tile_id(tile_x, tile_y)
            return -1
        else:
            # Local coordinates
            tile_x = int(x)
            tile_y = int(y)
            
            if tile_x < 0 or tile_x >= 64 or tile_y < 0 or tile_y >= 64:
                return -1
                
            return level.get_board_tile_id(tile_x, tile_y)
        
    def is_in_water(self, x: float, y: float, level: Level, is_gmap: bool = False, gmap_handler=None) -> bool:
        """Check if position is in water
        
        Args:
            x: X position in tiles (world coords if is_gmap)
            y: Y position in tiles (world coords if is_gmap)
            level: Current level
            is_gmap: Whether we're in GMAP mode
            gmap_handler: GMAP handler for checking adjacent segments
            
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
            tile_id = self.check_tile_at_position(check_x, check_y, level, is_gmap, gmap_handler)
            if tile_id >= 0 and self.tile_defs.is_water(tile_id):
                return True
                
        return False
        
    def is_on_chair(self, x: float, y: float, level: Level, is_gmap: bool = False, gmap_handler=None) -> bool:
        """Check if position is on a chair
        
        Args:
            x: X position in tiles (world coords if is_gmap)
            y: Y position in tiles (world coords if is_gmap)
            level: Current level
            is_gmap: Whether we're in GMAP mode
            gmap_handler: GMAP handler for checking adjacent segments
            
        Returns:
            True if on a chair
        """
        if not level:
            return False
            
        # Check center of player position
        tile_id = self.check_tile_at_position(x + 0.5, y + 0.5, level, is_gmap, gmap_handler)
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