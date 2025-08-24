"""
GMAP File Parser - Parses GMAP files to extract segment information
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GmapParser:
    """Parser for GMAP files"""
    
    def __init__(self):
        self.width = 0
        self.height = 0
        self.segments = []  # List of segment filenames in order
        self.tileset = None
        self.minimap_img = None
        self.map_img = None
        self.load_full_map = False
        self.preload_levels = []
        
    def parse(self, data: bytes) -> bool:
        """Parse GMAP file data
        
        Args:
            data: Raw GMAP file data
            
        Returns:
            True if parsing succeeded
        """
        try:
            # GMAP files can have different headers
            # Common formats: GRMAP001, GMAP, or WIDTH/HEIGHT directly
            text = data.decode('ascii', errors='ignore').strip()
            lines = text.split('\n')
            
            if not lines:
                logger.error("Empty GMAP file")
                return False
                
            # Check for GRMAP001 header
            if lines[0].startswith('GRMAP001'):
                lines = lines[1:]  # Skip header
            elif lines[0].startswith('GLEVELS'):
                # Old format: GLEVELS width height
                return self._parse_glevels_format(lines)
                
            # Parse standard GMAP format
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                if line.startswith('WIDTH'):
                    parts = line.split()
                    if len(parts) >= 2:
                        self.width = int(parts[1])
                        
                elif line.startswith('HEIGHT'):
                    parts = line.split()
                    if len(parts) >= 2:
                        self.height = int(parts[1])
                        
                elif line == 'LEVELNAMES':
                    # Parse the level names section
                    i += 1
                    while i < len(lines) and lines[i].strip() != 'LEVELNAMESEND':
                        level_line = lines[i].strip()
                        if level_line:
                            # Parse quoted, comma-separated level names
                            segments = self._parse_level_line(level_line)
                            self.segments.extend(segments)
                        i += 1
                        
                elif line.startswith('TILESET'):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        self.tileset = parts[1].strip()
                        
                elif line.startswith('MAPIMG'):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        self.map_img = parts[1].strip()
                        
                elif line.startswith('MINIMAPIMG'):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        self.minimap_img = parts[1].strip()
                        
                elif line == 'LOADFULLMAP':
                    self.load_full_map = True
                    
                elif line == 'LOADATSTART':
                    # Parse preload levels
                    i += 1
                    while i < len(lines) and lines[i].strip() != 'LOADATSTARTEND':
                        preload_line = lines[i].strip()
                        if preload_line:
                            # Can be comma-separated or one per line
                            if ',' in preload_line:
                                levels = self._parse_level_line(preload_line)
                                self.preload_levels.extend(levels)
                            else:
                                self.preload_levels.append(preload_line)
                        i += 1
                        
                i += 1
                
            logger.info(f"Parsed GMAP: {self.width}x{self.height} = {len(self.segments)} segments")
            return True
            
        except Exception as e:
            logger.error(f"Failed to parse GMAP file: {e}")
            return False
            
    def _parse_glevels_format(self, lines: List[str]) -> bool:
        """Parse old GLEVELS format"""
        try:
            # Format: GLEVELS width height
            parts = lines[0].split()
            if len(parts) >= 3:
                self.width = int(parts[1])
                self.height = int(parts[2])
                
            # Following lines are level names
            for i in range(1, len(lines)):
                level = lines[i].strip()
                if level:
                    self.segments.append(level)
                    
            return True
        except Exception as e:
            logger.error(f"Failed to parse GLEVELS format: {e}")
            return False
            
    def _parse_level_line(self, line: str) -> List[str]:
        """Parse a line of comma-separated, quoted level names"""
        segments = []
        
        # Remove quotes and split by comma
        line = line.replace('"', '').replace("'", '')
        parts = line.split(',')
        
        for part in parts:
            segment = part.strip()
            if segment:
                segments.append(segment)
                
        return segments
        
    def get_segment_at(self, x: int, y: int) -> Optional[str]:
        """Get segment filename at grid position
        
        Args:
            x: X coordinate (0-based)
            y: Y coordinate (0-based)
            
        Returns:
            Segment filename or None if out of bounds
        """
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return None
            
        index = y * self.width + x
        if index < len(self.segments):
            return self.segments[index]
            
        return None
        
    def get_adjacent_segments(self, x: int, y: int) -> Dict[str, str]:
        """Get all adjacent segments for a position
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Dict mapping direction to segment name
        """
        adjacent = {}
        
        # All 8 directions
        directions = {
            'north': (0, -1),
            'south': (0, 1),
            'east': (1, 0),
            'west': (-1, 0),
            'northeast': (1, -1),
            'northwest': (-1, -1),
            'southeast': (1, 1),
            'southwest': (-1, 1)
        }
        
        for direction, (dx, dy) in directions.items():
            segment = self.get_segment_at(x + dx, y + dy)
            if segment:
                adjacent[direction] = segment
                
        return adjacent
        
    def get_all_segments(self) -> List[str]:
        """Get all segment filenames"""
        return self.segments.copy()
        
    def get_preload_segments(self) -> List[str]:
        """Get segments that should be preloaded"""
        if self.load_full_map:
            # Load all segments
            return self.segments.copy()
        elif self.preload_levels:
            # Load specific preload list
            return self.preload_levels.copy()
        else:
            # No preloading
            return []