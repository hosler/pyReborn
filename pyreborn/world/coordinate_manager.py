"""
Coordinate Manager - All coordinate system handling

Handles coordinate transformations between:
- Local level coordinates (0-63 tiles)
- World coordinates (for GMAP systems)
- Pixel coordinates (16 pixels per tile)
- Half-tile coordinates (server protocol)
"""

import logging
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class Position:
    """Represents a position with different coordinate systems"""
    x: float
    y: float
    level: Optional[str] = None
    
    def to_tiles(self) -> Tuple[int, int]:
        """Convert to tile coordinates"""
        return int(self.x), int(self.y)
    
    def to_pixels(self) -> Tuple[int, int]:
        """Convert to pixel coordinates (16 pixels per tile)"""
        return int(self.x * 16), int(self.y * 16)
    
    def to_half_tiles(self) -> Tuple[int, int]:
        """Convert to half-tile coordinates (server protocol)"""
        return int(self.x * 2), int(self.y * 2)


@dataclass
class GMAPPosition:
    """Represents a position within a GMAP world"""
    segment_x: int
    segment_y: int
    local_x: float
    local_y: float
    level: Optional[str] = None
    
    def to_world_coordinates(self) -> Tuple[float, float]:
        """Convert to world coordinates"""
        world_x = self.segment_x * 64 + self.local_x
        world_y = self.segment_y * 64 + self.local_y
        return world_x, world_y
    
    def to_position(self) -> Position:
        """Convert to regular Position"""
        world_x, world_y = self.to_world_coordinates()
        return Position(world_x, world_y, self.level)


class CoordinateManager:
    """Manages coordinate transformations and validations"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # GMAP state
        self.gmap_enabled = False
        self.gmap_mode = False  # Add gmap_mode property for compatibility
        self.current_gmap: Optional[str] = None
        self.gmap_segments: Dict[str, Tuple[int, int]] = {}
        
        # Current position tracking
        self._current_position = Position(0.0, 0.0)
        
    def set_gmap_mode(self, enabled: bool, gmap_name: Optional[str] = None):
        """Enable/disable GMAP mode"""
        self.gmap_enabled = enabled
        self.current_gmap = gmap_name
        self.logger.debug(f"GMAP mode: {enabled}, map: {gmap_name}")
        
    def register_gmap_segment(self, level_name: str, segment_x: int, segment_y: int):
        """Register a level as a GMAP segment"""
        self.gmap_segments[level_name] = (segment_x, segment_y)
        self.logger.debug(f"Registered GMAP segment: {level_name} at ({segment_x}, {segment_y})")
        
    def is_gmap_level(self, level_name: str) -> bool:
        """Check if a level is part of the current GMAP"""
        return level_name in self.gmap_segments
        
    def get_segment_coordinates(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Get GMAP segment coordinates for a level"""
        return self.gmap_segments.get(level_name)
        
    def update_position(self, x: float, y: float, level: Optional[str] = None):
        """Update current position"""
        self._current_position = Position(x, y, level)
        self.logger.debug(f"Position updated: ({x}, {y}) in {level}")
        
    def get_position(self) -> Position:
        """Get current position"""
        return self._current_position
        
    def get_server_coordinates(self) -> Tuple[float, float]:
        """Get coordinates to send to server based on current mode"""
        pos = self._current_position
        
        if self.gmap_enabled and pos.level and self.is_gmap_level(pos.level):
            # GMAP mode + GMAP level: send world coordinates
            segment_coords = self.get_segment_coordinates(pos.level)
            if segment_coords:
                segment_x, segment_y = segment_coords
                world_x = segment_x * 64 + pos.x
                world_y = segment_y * 64 + pos.y
                self.logger.debug(f"GMAP coordinates: ({world_x}, {world_y})")
                return world_x, world_y
                
        # GMAP mode + non-GMAP level OR non-GMAP mode: send local coordinates
        self.logger.debug(f"Local coordinates: ({pos.x}, {pos.y})")
        return pos.x, pos.y
        
    def get_level_name_for_server(self) -> Optional[str]:
        """Get level name to send to server based on current mode"""
        pos = self._current_position
        
        if self.gmap_enabled and pos.level and self.is_gmap_level(pos.level):
            # GMAP mode + GMAP level: send GMAP filename
            if self.current_gmap:
                self.logger.debug(f"Sending GMAP name: {self.current_gmap}")
                return self.current_gmap
                
        # GMAP mode + non-GMAP level OR non-GMAP mode: send actual level name
        self.logger.debug(f"Sending level name: {pos.level}")
        return pos.level
        
    def local_to_world(self, x: float, y: float, level: str) -> Tuple[float, float]:
        """Convert local coordinates to world coordinates"""
        if self.is_gmap_level(level):
            segment_coords = self.get_segment_coordinates(level)
            if segment_coords:
                segment_x, segment_y = segment_coords
                return segment_x * 64 + x, segment_y * 64 + y
        return x, y
        
    def world_to_local(self, world_x: float, world_y: float) -> Tuple[float, float, Optional[str]]:
        """Convert world coordinates to local coordinates and level"""
        if not self.gmap_enabled:
            return world_x, world_y, None
            
        # Find which segment contains these world coordinates
        segment_x = int(world_x // 64)
        segment_y = int(world_y // 64)
        
        # Find level for this segment
        for level_name, (seg_x, seg_y) in self.gmap_segments.items():
            if seg_x == segment_x and seg_y == segment_y:
                local_x = world_x - segment_x * 64
                local_y = world_y - segment_y * 64
                return local_x, local_y, level_name
                
        # No matching segment found
        return world_x, world_y, None
        
    def validate_coordinates(self, x: float, y: float, level: Optional[str] = None) -> bool:
        """Validate coordinates are within acceptable bounds"""
        # Basic bounds checking (0-63 for single levels, larger for GMAP)
        max_coord = 64 * 64 if self.gmap_enabled else 64  # Max world size
        
        if x < 0 or y < 0 or x >= max_coord or y >= max_coord:
            self.logger.warning(f"Coordinates out of bounds: ({x}, {y})")
            return False
            
        return True
        
    def get_distance(self, pos1: Position, pos2: Position) -> float:
        """Calculate distance between two positions"""
        dx = pos2.x - pos1.x
        dy = pos2.y - pos1.y
        return (dx * dx + dy * dy) ** 0.5
        
    def get_status(self) -> Dict[str, Any]:
        """Get coordinate system status"""
        pos = self._current_position
        return {
            'gmap_enabled': self.gmap_enabled,
            'current_gmap': self.current_gmap,
            'current_position': {
                'x': pos.x,
                'y': pos.y,
                'level': pos.level
            },
            'server_coordinates': self.get_server_coordinates(),
            'server_level': self.get_level_name_for_server(),
            'registered_segments': len(self.gmap_segments)
        }
        
    def world_to_segment(self, world_x: float, world_y: float) -> Tuple[int, int, float, float]:
        """Convert world coordinates to segment and local coordinates"""
        seg_x = int(world_x // 64)
        seg_y = int(world_y // 64)
        local_x = world_x % 64
        local_y = world_y % 64
        return seg_x, seg_y, local_x, local_y
        
    def get_level_at_position(self, seg_x: int, seg_y: int) -> Optional[str]:
        """Get level at segment position"""
        for level_name, (sx, sy) in self.gmap_segments.items():
            if sx == seg_x and sy == seg_y:
                return level_name
        return None