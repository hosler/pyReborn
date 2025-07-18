"""
GMAP Coordinate Fix for Classic Reborn Client

This module provides coordinate wrapping logic for GMAP navigation when the server
doesn't properly handle segment transitions.
"""

class GmapCoordinateFixer:
    """Handles GMAP coordinate wrapping and segment transitions"""
    
    @staticmethod
    def wrap_coordinates(x: float, y: float, current_segment_x: int, current_segment_y: int):
        """
        Wrap coordinates and calculate correct segment position
        
        Args:
            x: Local X coordinate (may be > 64 or < 0)
            y: Local Y coordinate (may be > 64 or < 0)
            current_segment_x: Current GMAP segment X
            current_segment_y: Current GMAP segment Y
            
        Returns:
            Tuple of (wrapped_x, wrapped_y, new_segment_x, new_segment_y, level_changed)
        """
        # Calculate segment offsets
        segment_offset_x = int(x // 64)
        segment_offset_y = int(y // 64)
        
        # Wrap local coordinates to 0-63 range
        wrapped_x = x % 64
        wrapped_y = y % 64
        
        # Handle negative coordinates
        if x < 0:
            segment_offset_x = -int((-x - 1) // 64) - 1
            wrapped_x = x - (segment_offset_x * 64)
            
        if y < 0:
            segment_offset_y = -int((-y - 1) // 64) - 1
            wrapped_y = y - (segment_offset_y * 64)
        
        # Calculate new segment position
        new_segment_x = current_segment_x + segment_offset_x
        new_segment_y = current_segment_y + segment_offset_y
        
        # Check if level changed
        level_changed = (segment_offset_x != 0 or segment_offset_y != 0)
        
        return wrapped_x, wrapped_y, new_segment_x, new_segment_y, level_changed
    
    @staticmethod
    def get_world_coordinates(local_x: float, local_y: float, segment_x: int, segment_y: int):
        """
        Get world coordinates from local coordinates and segment position
        
        Args:
            local_x: Local X coordinate (0-63)
            local_y: Local Y coordinate (0-63)
            segment_x: GMAP segment X
            segment_y: GMAP segment Y
            
        Returns:
            Tuple of (world_x, world_y)
        """
        world_x = segment_x * 64 + local_x
        world_y = segment_y * 64 + local_y
        return world_x, world_y
    
    @staticmethod
    def get_segment_name(base_name: str, segment_x: int, segment_y: int) -> str:
        """
        Build segment filename from coordinates
        
        Args:
            base_name: Base GMAP name (e.g., "zlttp")
            segment_x: Segment X coordinate
            segment_y: Segment Y coordinate
            
        Returns:
            Segment filename (e.g., "zlttp-d8.nw")
        """
        if segment_x < 0 or segment_y < 0:
            return ""
            
        col_letter = chr(ord('a') + segment_x)
        return f"{base_name}-{col_letter}{segment_y}.nw"


# Example fix for the renderer's update_camera method:
"""
def update_camera_fixed(self, player_x: float, player_y: float, is_gmap: bool = False, 
                       gmaplevelx: int = 0, gmaplevely: int = 0):
    # In GMAP mode, handle coordinate wrapping
    if is_gmap and gmaplevelx is not None and gmaplevely is not None:
        # Check if coordinates need wrapping
        wrapped_x, wrapped_y, new_seg_x, new_seg_y, changed = GmapCoordinateFixer.wrap_coordinates(
            player_x, player_y, gmaplevelx, gmaplevely
        )
        
        if changed:
            # Request level change (this would need to be implemented)
            print(f"GMAP transition needed: seg[{gmaplevelx},{gmaplevely}] -> seg[{new_seg_x},{new_seg_y}]")
            print(f"Player coords: ({player_x:.1f},{player_y:.1f}) -> ({wrapped_x:.1f},{wrapped_y:.1f})")
        
        # Use wrapped coordinates for world position
        world_x, world_y = GmapCoordinateFixer.get_world_coordinates(
            wrapped_x, wrapped_y, new_seg_x, new_seg_y
        )
        
        self.camera_x = world_x - (VIEWPORT_TILES_X // 2)
        self.camera_y = world_y - (VIEWPORT_TILES_Y // 2)
    else:
        # Single level mode...
        pass
"""