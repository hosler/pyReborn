"""
Coordinate System Helpers

This module provides utilities for handling the various coordinate systems in Reborn Online:
- Local level coordinates (0-63 tiles within a level)  
- World coordinates (GMAP coordinates spanning multiple levels)
- Pixel coordinates (for X2/Y2 packet properties)
- Segment coordinates (GMAP segment positions)

Key Constants:
- 16 pixels per tile (standard Reborn conversion)
- 64 tiles per GMAP segment
"""

import logging
from typing import Tuple, Optional, NamedTuple
from dataclasses import dataclass


# Constants
PIXELS_PER_TILE = 16
TILES_PER_SEGMENT = 64


@dataclass
class CoordinateSet:
    """Complete coordinate information for a position"""
    # Core coordinates (always in tiles)
    local_x: float         # Position within current level (0-63)
    local_y: float         
    world_x: float         # Position in world coordinate system
    world_y: float
    
    # GMAP information
    segment_x: int = 0     # GMAP segment coordinates
    segment_y: int = 0
    is_gmap: bool = False  # Whether this is a GMAP position
    
    # Metadata
    level_name: Optional[str] = None
    gmap_name: Optional[str] = None


class CoordinateHelpers:
    """Static methods for coordinate conversions and calculations"""
    
    @staticmethod
    def tiles_to_pixels(tiles: float) -> int:
        """Convert tile coordinates to pixels (for X2/Y2 packet properties)"""
        return int(tiles * PIXELS_PER_TILE)
    
    @staticmethod
    def pixels_to_tiles(pixels: int) -> float:
        """Convert pixel coordinates to tiles (from pixelx/pixely properties)"""
        return float(pixels) / PIXELS_PER_TILE
    
    @staticmethod
    def world_to_segment(world_x: float, world_y: float) -> Tuple[int, int, float, float]:
        """Convert world coordinates to segment and local coordinates.
        
        Args:
            world_x: World X coordinate in tiles
            world_y: World Y coordinate in tiles
            
        Returns:
            (segment_x, segment_y, local_x, local_y) tuple
        """
        segment_x = int(world_x // TILES_PER_SEGMENT)
        segment_y = int(world_y // TILES_PER_SEGMENT)
        local_x = world_x % TILES_PER_SEGMENT
        local_y = world_y % TILES_PER_SEGMENT
        return segment_x, segment_y, local_x, local_y
    
    @staticmethod
    def segment_to_world(segment_x: int, segment_y: int, local_x: float, local_y: float) -> Tuple[float, float]:
        """Convert segment and local coordinates to world coordinates.
        
        Args:
            segment_x: GMAP segment X coordinate
            segment_y: GMAP segment Y coordinate
            local_x: Local X coordinate within segment (0-63)
            local_y: Local Y coordinate within segment (0-63)
            
        Returns:
            (world_x, world_y) tuple in tiles
        """
        world_x = segment_x * TILES_PER_SEGMENT + local_x
        world_y = segment_y * TILES_PER_SEGMENT + local_y
        return world_x, world_y
    
    @staticmethod
    def create_coordinate_set(world_x: float, world_y: float, is_gmap: bool = False,
                             level_name: str = None, gmap_name: str = None) -> CoordinateSet:
        """Create a complete coordinate set from world coordinates.
        
        Args:
            world_x: World X coordinate in tiles
            world_y: World Y coordinate in tiles
            is_gmap: Whether this is a GMAP position
            level_name: Name of the current level
            gmap_name: Name of the GMAP (if applicable)
            
        Returns:
            CoordinateSet with all coordinate information
        """
        if is_gmap:
            segment_x, segment_y, local_x, local_y = CoordinateHelpers.world_to_segment(world_x, world_y)
        else:
            segment_x = segment_y = 0
            local_x = world_x
            local_y = world_y
            
        return CoordinateSet(
            local_x=local_x,
            local_y=local_y,
            world_x=world_x,
            world_y=world_y,
            segment_x=segment_x,
            segment_y=segment_y,
            is_gmap=is_gmap,
            level_name=level_name,
            gmap_name=gmap_name
        )
    
    @staticmethod
    def extract_coordinates_from_player_props(properties: dict) -> Optional[CoordinateSet]:
        """Extract coordinate information from player properties packet.
        
        Args:
            properties: Dictionary of player properties from packet
            
        Returns:
            CoordinateSet or None if insufficient coordinate data
        """
        logger = logging.getLogger(__name__)
        
        # Try to get world coordinates (x2/y2) first - these are authoritative
        world_x = properties.get('x2')
        world_y = properties.get('y2')
        
        # Fallback to pixelx/pixely (convert from pixels to tiles)
        if world_x is None and 'pixelx' in properties:
            world_x = properties['pixelx']  # Already converted to tiles in parser
        if world_y is None and 'pixely' in properties:
            world_y = properties['pixely']  # Already converted to tiles in parser
            
        # Last resort: use local x/y coordinates
        if world_x is None:
            world_x = properties.get('x', 30.0)  # Default center position
        if world_y is None:
            world_y = properties.get('y', 30.0)
            
        # Check if this is GMAP mode
        is_gmap = 'gmaplevelx' in properties and 'gmaplevely' in properties
        
        # Create coordinate set
        coord_set = CoordinateHelpers.create_coordinate_set(
            world_x=float(world_x),
            world_y=float(world_y),
            is_gmap=is_gmap
        )
        
        # Set GMAP segment info if available
        if is_gmap:
            coord_set.segment_x = properties['gmaplevelx']
            coord_set.segment_y = properties['gmaplevely']
            
        logger.debug(f"Extracted coordinates: world=({world_x:.2f},{world_y:.2f}), "
                    f"gmap={is_gmap}, segment=({coord_set.segment_x},{coord_set.segment_y})")
        
        return coord_set
    
    @staticmethod
    def validate_coordinate_consistency(coord_set: CoordinateSet) -> bool:
        """Validate that coordinate set is internally consistent.
        
        Args:
            coord_set: CoordinateSet to validate
            
        Returns:
            True if coordinates are consistent
        """
        if not coord_set.is_gmap:
            # In single level mode, world coords should match local coords
            return (abs(coord_set.world_x - coord_set.local_x) < 0.1 and
                   abs(coord_set.world_y - coord_set.local_y) < 0.1)
        else:
            # In GMAP mode, validate world = segment * 64 + local
            expected_world_x = coord_set.segment_x * TILES_PER_SEGMENT + coord_set.local_x
            expected_world_y = coord_set.segment_y * TILES_PER_SEGMENT + coord_set.local_y
            
            return (abs(coord_set.world_x - expected_world_x) < 0.1 and
                   abs(coord_set.world_y - expected_world_y) < 0.1)
    
    @staticmethod
    def create_packet_properties(coord_set: CoordinateSet, **additional_props) -> dict:
        """Create packet properties dict for sending to server.
        
        Args:
            coord_set: CoordinateSet with position information
            **additional_props: Additional properties to include
            
        Returns:
            Dictionary suitable for player properties packet
        """
        props = {
            # X2/Y2 are sent as PIXELS to server
            'x2': CoordinateHelpers.tiles_to_pixels(coord_set.world_x),
            'y2': CoordinateHelpers.tiles_to_pixels(coord_set.world_y),
        }
        
        # Add GMAP segment info if applicable
        if coord_set.is_gmap:
            props['gmaplevelx'] = coord_set.segment_x
            props['gmaplevely'] = coord_set.segment_y
            
        # Add any additional properties
        props.update(additional_props)
        
        return props
    
    @staticmethod
    def get_distance(coord1: CoordinateSet, coord2: CoordinateSet) -> float:
        """Calculate distance between two coordinate sets.
        
        Args:
            coord1: First position
            coord2: Second position
            
        Returns:
            Distance in tiles
        """
        dx = coord1.world_x - coord2.world_x
        dy = coord1.world_y - coord2.world_y
        return (dx * dx + dy * dy) ** 0.5
    
    @staticmethod
    def is_same_segment(coord1: CoordinateSet, coord2: CoordinateSet) -> bool:
        """Check if two coordinates are in the same GMAP segment.
        
        Args:
            coord1: First position
            coord2: Second position
            
        Returns:
            True if both are in same segment (or both non-GMAP)
        """
        if coord1.is_gmap != coord2.is_gmap:
            return False
            
        if not coord1.is_gmap:
            return True  # Both are single level
            
        return (coord1.segment_x == coord2.segment_x and
               coord1.segment_y == coord2.segment_y)
    
    @staticmethod
    def format_coordinates(coord_set: CoordinateSet) -> str:
        """Format coordinate set for debugging/display.
        
        Args:
            coord_set: CoordinateSet to format
            
        Returns:
            Human-readable coordinate string
        """
        if coord_set.is_gmap:
            return (f"GMAP: world=({coord_set.world_x:.2f},{coord_set.world_y:.2f}), "
                   f"segment=({coord_set.segment_x},{coord_set.segment_y}), "
                   f"local=({coord_set.local_x:.2f},{coord_set.local_y:.2f})")
        else:
            return f"Level: ({coord_set.local_x:.2f},{coord_set.local_y:.2f})"


# Convenience functions for common operations
def tiles_to_pixels(tiles: float) -> int:
    """Convert tiles to pixels (shortcut function)"""
    return CoordinateHelpers.tiles_to_pixels(tiles)


def pixels_to_tiles(pixels: int) -> float:
    """Convert pixels to tiles (shortcut function)"""
    return CoordinateHelpers.pixels_to_tiles(pixels)


def world_to_segment(world_x: float, world_y: float) -> Tuple[int, int, float, float]:
    """Convert world to segment coordinates (shortcut function)"""
    return CoordinateHelpers.world_to_segment(world_x, world_y)


def segment_to_world(segment_x: int, segment_y: int, local_x: float, local_y: float) -> Tuple[float, float]:
    """Convert segment to world coordinates (shortcut function)"""
    return CoordinateHelpers.segment_to_world(segment_x, segment_y, local_x, local_y)