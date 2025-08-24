"""
GMAP Utilities - Helper functions for working with Reborn GMAPs
"""

from typing import Tuple, Optional


class GMAPUtils:
    """Utilities for GMAP coordinate conversions and segment calculations"""
    
    @staticmethod
    def segment_to_gmap_name(base_name: str, gmaplevelx: int, gmaplevely: int) -> str:
        """Convert GMAP segment coordinates to segment filename
        
        Args:
            base_name: Base GMAP name (e.g., "zlttp")
            gmaplevelx: X segment coordinate (0-based)
            gmaplevely: Y segment coordinate (0-based)
            
        Returns:
            Segment filename (e.g., "zlttp-d8.nw")
        """
        # This should not make assumptions - the actual mapping comes from GMAP data
        raise NotImplementedError("This method should not be used - use GMAP data instead")
    
    @staticmethod
    def gmap_name_to_segment(segment_name: str) -> Tuple[str, int, int]:
        """Parse GMAP segment name to get base name and coordinates
        
        Args:
            segment_name: Segment filename (e.g., "zlttp-d8.nw")
            
        Returns:
            Tuple of (base_name, gmaplevelx, gmaplevely)
        """
        if not segment_name.endswith('.nw'):
            raise ValueError(f"Invalid segment name: {segment_name}")
            
        # Remove .nw extension
        name = segment_name[:-3]
        
        # Find the hyphen separating base name from coordinates
        if '-' not in name:
            raise ValueError(f"Invalid segment name format: {segment_name}")
            
        base_name, coords = name.rsplit('-', 1)
        
        # Parse coordinates (e.g., "d8")
        if len(coords) < 2:
            raise ValueError(f"Invalid coordinates in segment name: {segment_name}")
            
        col_letter = coords[0]
        row_str = coords[1:]
        
        # This should not make assumptions - the actual mapping comes from GMAP data
        raise NotImplementedError("This method should not be used - use GMAP data instead")
        
        return base_name, gmaplevelx, gmaplevely
    
    @staticmethod
    def local_to_gmap_position(gmaplevelx: int, gmaplevely: int, 
                              local_x: float, local_y: float) -> Tuple[float, float]:
        """Convert local segment position to global GMAP position
        
        Args:
            gmaplevelx: X segment coordinate
            gmaplevely: Y segment coordinate  
            local_x: X position within segment (in tiles)
            local_y: Y position within segment (in tiles)
            
        Returns:
            Tuple of (gmap_x, gmap_y) in tiles
        """
        gmap_x = gmaplevelx * 64 + local_x
        gmap_y = gmaplevely * 64 + local_y
        return gmap_x, gmap_y
    
    @staticmethod
    def gmap_to_local_position(gmap_x: float, gmap_y: float) -> Tuple[int, int, float, float]:
        """Convert global GMAP position to segment and local position
        
        Args:
            gmap_x: Global X position in tiles
            gmap_y: Global Y position in tiles
            
        Returns:
            Tuple of (gmaplevelx, gmaplevely, local_x, local_y)
        """
        gmaplevelx = int(gmap_x // 64)
        gmaplevely = int(gmap_y // 64)
        local_x = gmap_x % 64
        local_y = gmap_y % 64
        return gmaplevelx, gmaplevely, local_x, local_y
    
    @staticmethod
    def pixel_to_gmap_position(gmaplevelx: int, gmaplevely: int,
                              pixel_x: int, pixel_y: int) -> Tuple[float, float]:
        """Convert pixel position to global GMAP position
        
        This matches Reborn's internal positioning system where each
        segment is offset by 64 tiles (1024 pixels) in each direction.
        
        Args:
            gmaplevelx: X segment coordinate
            gmaplevely: Y segment coordinate
            pixel_x: X position in pixels within segment
            pixel_y: Y position in pixels within segment
            
        Returns:
            Tuple of (gmap_pixel_x, gmap_pixel_y) in pixels
        """
        # Each segment is 64 tiles = 1024 pixels
        gmap_pixel_x = gmaplevelx * 1024 + pixel_x
        gmap_pixel_y = gmaplevely * 1024 + pixel_y
        return gmap_pixel_x, gmap_pixel_y
    
    @staticmethod
    def get_adjacent_segments(gmaplevelx: int, gmaplevely: int) -> list[Tuple[int, int]]:
        """Get list of adjacent segment coordinates (including diagonals)
        
        Args:
            gmaplevelx: Current X segment coordinate
            gmaplevely: Current Y segment coordinate
            
        Returns:
            List of (x, y) tuples for adjacent segments
        """
        adjacent = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue  # Skip current segment
                    
                new_x = gmaplevelx + dx
                new_y = gmaplevely + dy
                
                # Only include valid coordinates (non-negative)
                if new_x >= 0 and new_y >= 0:
                    adjacent.append((new_x, new_y))
                    
        return adjacent


# Module-level functions for compatibility
def world_to_segment(world_x: float, world_y: float) -> Tuple[int, int, float, float]:
    """Convert world coordinates to segment and local coordinates (compatibility function)"""
    return GMAPUtils.gmap_to_local_position(world_x, world_y)

def segment_to_world(segment_x: int, segment_y: int, local_x: float, local_y: float) -> Tuple[float, float]:
    """Convert segment and local coordinates to world coordinates (compatibility function)"""
    return GMAPUtils.local_to_gmap_position(segment_x, segment_y, local_x, local_y)

def get_segment_from_world(world_x: float, world_y: float) -> Tuple[int, int]:
    """Get segment coordinates from world position (compatibility function)"""
    seg_x, seg_y, _, _ = GMAPUtils.gmap_to_local_position(world_x, world_y)
    return seg_x, seg_y

def is_valid_segment(seg_x: int, seg_y: int, gmap_width: int, gmap_height: int) -> bool:
    """Check if segment coordinates are valid for GMAP dimensions (compatibility function)"""
    return 0 <= seg_x < gmap_width and 0 <= seg_y < gmap_height