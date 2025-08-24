"""
GMAP Resolver - Intelligent level name resolution for GMAP worlds

This module provides the core logic for resolving actual level names from GMAP
coordinates, eliminating the need for hardcoded patterns and providing a robust
solution for GMAP level transitions.

Key Features:
- World coordinate to segment mapping
- Segment to level name resolution  
- Support for various GMAP file formats
- Automatic scale detection (tiles vs pixels)
- Fallback mechanisms for incomplete data
"""

import logging
import os
from typing import Dict, List, Optional, Tuple, Set, Union
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GMapLevelInfo:
    """Information about a level within a GMAP"""
    name: str
    segment_x: int
    segment_y: int
    world_bounds: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    
    
@dataclass 
class CoordinateInfo:
    """Comprehensive coordinate information"""
    world_x: float
    world_y: float
    segment_x: int
    segment_y: int
    local_x: float
    local_y: float
    is_gmap: bool
    scale_factor: float = 1.0  # For handling tiles vs pixels


class GMapResolver:
    """
    Intelligent GMAP level name resolver using world coordinates.
    
    This class eliminates the need for hardcoded GMAP patterns by using
    authoritative world coordinates (x2/y2 from player props) to determine
    the actual level name within a GMAP world.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # GMAP structure cache
        self._gmap_cache: Dict[str, Dict[Tuple[int, int], GMapLevelInfo]] = {}
        self._level_name_cache: Dict[str, Dict[str, GMapLevelInfo]] = {}
        
        # Coordinate system configuration
        self.segment_size = 64  # tiles per segment
        self.scale_detection_enabled = True
        
        # Known GMAP patterns for fallback
        self._common_patterns = [
            # Pattern: base_name + segment_x + segment_y_suffix
            lambda base, x, y: f"{base}{x}.nw" if y == 0 else f"{base}{x}.n{y}w",
            lambda base, x, y: f"{base}_{x}_{y}",
            lambda base, x, y: f"{base}-{x}-{y}",
            lambda base, x, y: f"{base}{x}_{y}",
        ]
        
    def register_gmap_structure(self, gmap_name: str, levels_data: Dict[str, Tuple[int, int]]):
        """
        Register a GMAP structure for level resolution.
        
        Args:
            gmap_name: Name of the GMAP file (e.g., "chicken.gmap")
            levels_data: Dict mapping level names to (segment_x, segment_y) coordinates
        """
        self.logger.info(f"Registering GMAP structure: {gmap_name} with {len(levels_data)} levels")
        
        gmap_key = gmap_name.lower()
        segment_map = {}
        name_map = {}
        
        for level_name, (seg_x, seg_y) in levels_data.items():
            # Calculate world bounds for this segment
            world_min_x = seg_x * self.segment_size
            world_min_y = seg_y * self.segment_size
            world_max_x = world_min_x + self.segment_size
            world_max_y = world_min_y + self.segment_size
            
            level_info = GMapLevelInfo(
                name=level_name,
                segment_x=seg_x,
                segment_y=seg_y,
                world_bounds=(world_min_x, world_min_y, world_max_x, world_max_y)
            )
            
            segment_map[(seg_x, seg_y)] = level_info
            name_map[level_name.lower()] = level_info
            
        self._gmap_cache[gmap_key] = segment_map
        self._level_name_cache[gmap_key] = name_map
        
        self.logger.info(f"GMAP {gmap_name} registered: segments {sorted(segment_map.keys())}")
        
    def resolve_level_from_world_coords(self, gmap_name: str, world_x: float, world_y: float, 
                                       scale_hint: Optional[str] = None) -> Optional[str]:
        """
        Resolve the actual level name from world coordinates.
        
        Args:
            gmap_name: GMAP file name
            world_x: World X coordinate (from x2 property)
            world_y: World Y coordinate (from y2 property) 
            scale_hint: Optional hint about coordinate scale ("tiles", "pixels", "auto")
            
        Returns:
            Actual level name or None if resolution fails
        """
        if not gmap_name:
            return None
            
        gmap_key = gmap_name.lower()
        
        # Try different scale interpretations
        scales_to_try = self._get_scales_to_try(scale_hint)
        
        for scale_factor in scales_to_try:
            scaled_x = world_x * scale_factor
            scaled_y = world_y * scale_factor
            
            # Calculate segment coordinates
            seg_x = int(scaled_x // self.segment_size)
            seg_y = int(scaled_y // self.segment_size)
            
            self.logger.debug(f"Trying scale {scale_factor}: world({world_x:.2f},{world_y:.2f}) -> "
                            f"scaled({scaled_x:.2f},{scaled_y:.2f}) -> segment({seg_x},{seg_y})")
            
            # Try direct lookup first
            if gmap_key in self._gmap_cache:
                segment_map = self._gmap_cache[gmap_key]
                if (seg_x, seg_y) in segment_map:
                    level_name = segment_map[(seg_x, seg_y)].name
                    self.logger.info(f"✅ Resolved {gmap_name} world({world_x:.2f},{world_y:.2f}) -> {level_name}")
                    return level_name
            
            # Try pattern-based resolution
            level_name = self._try_pattern_resolution(gmap_name, seg_x, seg_y)
            if level_name:
                self.logger.info(f"✅ Pattern-resolved {gmap_name} segment({seg_x},{seg_y}) -> {level_name}")
                return level_name
                
        self.logger.warning(f"❌ Could not resolve level for {gmap_name} at world({world_x:.2f},{world_y:.2f})")
        return None
        
    def resolve_level_from_segment(self, gmap_name: str, segment_x: int, segment_y: int) -> Optional[str]:
        """
        Resolve level name from segment coordinates (fallback method).
        
        Args:
            gmap_name: GMAP file name
            segment_x: Segment X coordinate
            segment_y: Segment Y coordinate
            
        Returns:
            Level name or None if resolution fails
        """
        if not gmap_name:
            return None
            
        gmap_key = gmap_name.lower()
        
        # Try direct lookup
        if gmap_key in self._gmap_cache:
            segment_map = self._gmap_cache[gmap_key]
            if (segment_x, segment_y) in segment_map:
                return segment_map[(segment_x, segment_y)].name
        
        # Try pattern-based resolution
        return self._try_pattern_resolution(gmap_name, segment_x, segment_y)
        
    def get_coordinate_info(self, gmap_name: str, world_x: float, world_y: float,
                           scale_hint: Optional[str] = None) -> Optional[CoordinateInfo]:
        """
        Get comprehensive coordinate information.
        
        Args:
            gmap_name: GMAP file name
            world_x: World X coordinate
            world_y: World Y coordinate
            scale_hint: Scale hint for coordinate interpretation
            
        Returns:
            CoordinateInfo object or None if resolution fails
        """
        scales_to_try = self._get_scales_to_try(scale_hint)
        
        for scale_factor in scales_to_try:
            scaled_x = world_x * scale_factor
            scaled_y = world_y * scale_factor
            
            seg_x = int(scaled_x // self.segment_size)
            seg_y = int(scaled_y // self.segment_size)
            
            local_x = scaled_x % self.segment_size
            local_y = scaled_y % self.segment_size
            
            # Verify this scale makes sense by checking if we can resolve a level
            if self.resolve_level_from_segment(gmap_name, seg_x, seg_y):
                return CoordinateInfo(
                    world_x=world_x,
                    world_y=world_y,
                    segment_x=seg_x,
                    segment_y=seg_y,
                    local_x=local_x,
                    local_y=local_y,
                    is_gmap=True,
                    scale_factor=scale_factor
                )
                
        return None
        
    def _get_scales_to_try(self, scale_hint: Optional[str]) -> List[float]:
        """Get list of scale factors to try based on hint."""
        if scale_hint == "tiles":
            return [1.0]
        elif scale_hint == "pixels":
            return [1.0/16.0]  # 16 pixels per tile
        elif scale_hint == "auto" or scale_hint is None:
            # Try both scales, tiles first (more common)
            return [1.0, 1.0/16.0, 2.0, 0.5]  # tiles, pixels, double-tiles, half-tiles
        else:
            return [1.0]  # default to tiles
            
    def _try_pattern_resolution(self, gmap_name: str, segment_x: int, segment_y: int) -> Optional[str]:
        """Try to resolve level name using common GMAP patterns."""
        base_name = gmap_name.replace('.gmap', '').replace('.GMAP', '')
        
        for pattern_func in self._common_patterns:
            try:
                level_name = pattern_func(base_name, segment_x, segment_y)
                # In a real implementation, we might check if this level exists
                # For now, we'll return the first pattern that seems reasonable
                if level_name and len(level_name) > 0:
                    self.logger.debug(f"Pattern generated: {level_name} for segment ({segment_x},{segment_y})")
                    return level_name
            except Exception as e:
                self.logger.debug(f"Pattern function failed: {e}")
                continue
                
        return None
        
    def load_gmap_file(self, gmap_path: str) -> bool:
        """
        Load a GMAP file and register its structure.
        
        Args:
            gmap_path: Path to the .gmap file
            
        Returns:
            True if loaded successfully
        """
        if not os.path.exists(gmap_path):
            self.logger.error(f"GMAP file not found: {gmap_path}")
            return False
            
        try:
            gmap_name = os.path.basename(gmap_path)
            levels_data = {}
            
            with open(gmap_path, 'r') as f:
                content = f.read()
                
            # Parse structured GMAP format
            lines = content.strip().split('\n')
            
            # Find dimensions
            width = 3  # default
            height = 3  # default
            
            for line in lines:
                line = line.strip()
                if line.startswith('WIDTH'):
                    width = int(line.split()[1])
                elif line.startswith('HEIGHT'):
                    height = int(line.split()[1])
            
            # Find LEVELNAMES section
            in_levelnames = False
            level_grid = []
            
            for line in lines:
                line = line.strip()
                if line == 'LEVELNAMES':
                    in_levelnames = True
                    continue
                elif line == 'LEVELNAMESEND':
                    in_levelnames = False
                    break
                elif in_levelnames and line:
                    # Parse comma-separated quoted level names
                    # Remove trailing comma and split by comma
                    level_line = line.rstrip(',')
                    level_names = []
                    
                    # Parse quoted strings
                    import re
                    matches = re.findall(r'"([^"]*)"', level_line)
                    level_names.extend(matches)
                    
                    if level_names:
                        level_grid.append(level_names)
            
            # Map level grid to segment coordinates
            for y, row in enumerate(level_grid):
                for x, level_name in enumerate(row):
                    if level_name and level_name != '0':
                        levels_data[level_name] = (x, y)
                        self.logger.debug(f"Mapped {level_name} to segment ({x},{y})")
                        
            if levels_data:
                self.register_gmap_structure(gmap_name, levels_data)
                self.logger.info(f"Loaded GMAP file: {gmap_path} with {len(levels_data)} levels")
                self.logger.info(f"GMAP dimensions: {width}x{height}, actual levels: {len(levels_data)}")
                return True
            else:
                self.logger.warning(f"No levels found in GMAP file: {gmap_path}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to load GMAP file {gmap_path}: {e}")
            return False
            
    def get_registered_gmaps(self) -> List[str]:
        """Get list of registered GMAP names."""
        return list(self._gmap_cache.keys())
        
    def get_gmap_info(self, gmap_name: str) -> Optional[Dict]:
        """Get information about a registered GMAP."""
        gmap_key = gmap_name.lower()
        if gmap_key not in self._gmap_cache:
            return None
            
        segment_map = self._gmap_cache[gmap_key]
        return {
            'gmap_name': gmap_name,
            'level_count': len(segment_map),
            'segments': list(segment_map.keys()),
            'levels': [info.name for info in segment_map.values()]
        }
        
    def clear_cache(self):
        """Clear all cached GMAP data."""
        self._gmap_cache.clear()
        self._level_name_cache.clear()
        self.logger.info("GMAP resolver cache cleared")