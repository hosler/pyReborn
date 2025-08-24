"""
GMAP Segment Mapper
===================

Maps level names to their GMAP segment positions for proper coordinate calculations.
This is essential for smooth GMAP transitions without warping.
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class GMAPInfo:
    """Information about a GMAP and its levels"""
    name: str
    width: int  # Width in segments
    height: int  # Height in segments
    levels: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # level_name -> (seg_x, seg_y)


class GMAPSegmentMapper:
    """Maps level names to GMAP segments for coordinate calculations"""
    
    def __init__(self):
        """Initialize the segment mapper"""
        self.gmaps: Dict[str, GMAPInfo] = {}
        self.level_to_gmap: Dict[str, str] = {}  # Quick lookup: level_name -> gmap_name
        self.current_gmap: Optional[str] = None
        
        logger.info("GMAP Segment Mapper initialized")
    
    def parse_gmap_file(self, gmap_name: str, gmap_data: bytes) -> bool:
        """Parse a GMAP file to extract level-to-segment mapping
        
        Args:
            gmap_name: Name of the GMAP file (e.g., 'chicken.gmap')
            gmap_data: Raw GMAP file data
            
        Returns:
            True if parsing successful
        """
        try:
            content = gmap_data.decode('latin-1', errors='replace')
            lines = content.split('\n')
            
            # New GMAP format (GRMAP001):
            # GRMAP001
            # WIDTH 3
            # HEIGHT 3
            # LEVELNAMES
            # "level1.nw","level2.nw",...
            # LEVELNAMESEND
            
            if not lines:
                logger.error(f"Empty GMAP file: {gmap_name}")
                return False
            
            width = 0
            height = 0
            level_grid = []
            
            # Check if it's the new format
            if lines[0].strip().startswith('GRMAP'):
                # New format parsing
                in_levelnames = False
                levelnames_content = []
                
                for line in lines:
                    line = line.strip()
                    
                    if line.startswith('WIDTH'):
                        width = int(line.split()[1])
                    elif line.startswith('HEIGHT'):
                        height = int(line.split()[1])
                    elif line == 'LEVELNAMES':
                        in_levelnames = True
                    elif line == 'LEVELNAMESEND':
                        in_levelnames = False
                    elif in_levelnames:
                        levelnames_content.append(line)
                
                # Parse the level names grid
                if levelnames_content:
                    # Join all lines and parse as comma-separated
                    all_levels = ''.join(levelnames_content)
                    # Remove quotes and split by comma
                    level_list = [l.strip().strip('"') for l in all_levels.split(',') if l.strip().strip('"')]
                    
                    # Convert flat list to 2D grid
                    for y in range(height):
                        row = []
                        for x in range(width):
                            idx = y * width + x
                            if idx < len(level_list):
                                row.append(level_list[idx])
                            else:
                                row.append('')
                        level_grid.append(row)
            else:
                # Old format: WIDTH HEIGHT on first line, then level grid
                dimensions = lines[0].strip().split()
                if len(dimensions) >= 2:
                    width = int(dimensions[0])
                    height = int(dimensions[1])
                    
                    # Parse level grid
                    for y in range(height):
                        if y + 1 < len(lines):
                            level_names = lines[y + 1].strip().split()
                            level_grid.append(level_names)
            
            if width == 0 or height == 0:
                logger.error(f"Invalid dimensions in {gmap_name}")
                return False
            
            # Create GMAP info
            gmap_info = GMAPInfo(
                name=gmap_name,
                width=width,
                height=height
            )
            
            # Store level-to-segment mapping with normalized names
            for seg_y, row in enumerate(level_grid):
                for seg_x, level_name in enumerate(row):
                    if level_name and level_name != 'CLEAR' and level_name != '':
                        # Normalize level name by removing .nw extension
                        normalized_name = level_name[:-3] if level_name.endswith('.nw') else level_name
                        # Store mapping with normalized name
                        gmap_info.levels[normalized_name] = (seg_x, seg_y)
                        self.level_to_gmap[normalized_name] = gmap_name
                        logger.debug(f"Mapped {normalized_name} to segment ({seg_x}, {seg_y}) in {gmap_name}")
            
            # Store GMAP info
            self.gmaps[gmap_name] = gmap_info
            
            logger.info(f"Parsed GMAP {gmap_name}: {width}x{height} with {len(gmap_info.levels)} levels")
            
            # Log the actual mapping for debugging
            if gmap_name == 'chicken.gmap':
                logger.info("Chicken GMAP mapping:")
                for level, segment in sorted(gmap_info.levels.items()):
                    logger.info(f"  {level} -> segment {segment}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to parse GMAP {gmap_name}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def set_current_gmap(self, gmap_name: str) -> None:
        """Set the current active GMAP
        
        Args:
            gmap_name: Name of the GMAP (e.g., 'chicken.gmap')
        """
        if gmap_name in self.gmaps:
            self.current_gmap = gmap_name
            logger.info(f"Set current GMAP to: {gmap_name}")
        else:
            logger.warning(f"Unknown GMAP: {gmap_name}")
    
    def get_segment_for_level(self, level_name: str, gmap_name: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """Get the GMAP segment coordinates for a level
        
        Args:
            level_name: Name of the level (e.g., 'chicken1.nw')
            gmap_name: Optional GMAP name to search in (uses current if not specified)
            
        Returns:
            (segment_x, segment_y) or None if not found
        """
        # Use specified GMAP or current
        search_gmap = gmap_name or self.current_gmap
        
        if not search_gmap:
            # Try to find which GMAP contains this level
            if level_name in self.level_to_gmap:
                search_gmap = self.level_to_gmap[level_name]
            else:
                logger.debug(f"Level {level_name} not found in any GMAP")
                return None
        
        # Look up segment in GMAP
        if search_gmap in self.gmaps:
            gmap_info = self.gmaps[search_gmap]
            if level_name in gmap_info.levels:
                return gmap_info.levels[level_name]
        
        logger.debug(f"Level {level_name} not found in GMAP {search_gmap}")
        return None
    
    def is_level_in_gmap(self, level_name: str, gmap_name: Optional[str] = None) -> bool:
        """Check if a level is part of a GMAP
        
        Args:
            level_name: Name of the level
            gmap_name: Optional specific GMAP to check (uses current if not specified)
            
        Returns:
            True if level is in the GMAP
        """
        return self.get_segment_for_level(level_name, gmap_name) is not None
    
    def calculate_world_coordinates(self, level_name: str, local_x: float, local_y: float, 
                                   gmap_name: Optional[str] = None) -> Optional[Tuple[float, float]]:
        """Calculate world coordinates from local coordinates
        
        Args:
            level_name: Current level name
            local_x: Local X coordinate in tiles
            local_y: Local Y coordinate in tiles
            gmap_name: Optional GMAP name (uses current if not specified)
            
        Returns:
            (world_x, world_y) in tiles or None if not in GMAP
        """
        segment = self.get_segment_for_level(level_name, gmap_name)
        if segment:
            world_x = segment[0] * 64 + local_x
            world_y = segment[1] * 64 + local_y
            return (world_x, world_y)
        return None
    
    def get_level_at_world_coordinates(self, world_x: float, world_y: float, 
                                       gmap_name: Optional[str] = None) -> Optional[str]:
        """Get the level name at world coordinates
        
        Args:
            world_x: World X coordinate in tiles
            world_y: World Y coordinate in tiles
            gmap_name: Optional GMAP name (uses current if not specified)
            
        Returns:
            Level name or None if outside GMAP
        """
        # Calculate segment
        seg_x = int(world_x // 64)
        seg_y = int(world_y // 64)
        
        # Use specified GMAP or current
        search_gmap = gmap_name or self.current_gmap
        if not search_gmap or search_gmap not in self.gmaps:
            return None
        
        # Look up level at segment
        gmap_info = self.gmaps[search_gmap]
        for level_name, segment in gmap_info.levels.items():
            if segment == (seg_x, seg_y):
                return level_name
        
        return None
    
    def get_statistics(self) -> Dict[str, any]:
        """Get statistics about loaded GMAPs
        
        Returns:
            Dictionary with statistics
        """
        total_levels = sum(len(gmap.levels) for gmap in self.gmaps.values())
        
        return {
            'gmaps_loaded': len(self.gmaps),
            'total_levels_mapped': total_levels,
            'current_gmap': self.current_gmap,
            'gmap_list': list(self.gmaps.keys())
        }