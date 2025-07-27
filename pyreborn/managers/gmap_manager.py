"""
GMAP Manager - Handles all GMAP-specific logic
"""

import logging
from typing import Optional, Dict, Tuple, Set
from ..parsers.gmap_parser import GmapParser
from ..utils.logging_config import ModuleLogger

logger = ModuleLogger.get_logger(__name__)


class GMapSegment:
    """Represents a single segment in a GMAP"""
    def __init__(self, x: int, y: int, level_name: str):
        self.x = x
        self.y = y
        self.level_name = level_name
        

class GMapData:
    """Holds parsed GMAP data"""
    def __init__(self):
        self.width = 0
        self.height = 0
        self.segments: Dict[Tuple[int, int], str] = {}  # (x,y) -> level_name
        self.tileset = None
        self.minimap_img = None
        self.map_img = None
        

class GMapManager:
    """Manages GMAP state and operations"""
    
    def __init__(self, client):
        self.client = client
        self.gmaps: Dict[str, GMapData] = {}  # gmap_name -> GMapData
        self.current_gmap: Optional[str] = None
        self.current_segment: Optional[Tuple[int, int]] = None
        self._is_active = False
        
    @property
    def is_active(self) -> bool:
        """Check if we're currently in GMAP mode"""
        return self._is_active and self.current_gmap is not None
        
    @property
    def is_ready(self) -> bool:
        """Check if we're in GMAP mode with full data loaded and segment coordinates set"""
        if not self.is_active:
            logger.debug(f"[GMAP_READY] Not active - is_active={self.is_active}, current_gmap={self.current_gmap}")
            return False
            
        # Check if GMAP data exists
        gmap_data = self.gmaps.get(self.current_gmap)
        if not gmap_data:
            logger.debug(f"[GMAP_READY] No data for GMAP '{self.current_gmap}' - available: {list(self.gmaps.keys())}")
            return False
            
        # Check if segment coordinates are set
        if self.current_segment is None:
            logger.debug(f"[GMAP_READY] No current segment set - current_segment={self.current_segment}")
            return False
            
        logger.debug(f"[GMAP_READY] Ready! GMAP='{self.current_gmap}', segment={self.current_segment}")
        return True
        
    def handle_gmap_file(self, filename: str, data: bytes):
        """Process a GMAP file"""
        if not filename.endswith('.gmap'):
            return
            
        gmap_name = filename[:-5]  # Remove .gmap extension
        logger.info(f"Processing GMAP file: {filename} ({len(data)} bytes)")
        
        # Parse GMAP file
        parser = GmapParser()
        if parser.parse(data):
            gmap_data = GMapData()
            gmap_data.width = parser.width
            gmap_data.height = parser.height
            gmap_data.tileset = parser.tileset
            gmap_data.minimap_img = parser.minimap_img
            gmap_data.map_img = parser.map_img
            
            # Build segment map
            for y in range(parser.height):
                for x in range(parser.width):
                    idx = y * parser.width + x
                    if idx < len(parser.segments):
                        level_name = parser.segments[idx]
                        if level_name and level_name != '':
                            gmap_data.segments[(x, y)] = level_name
                            
            self.gmaps[gmap_name] = gmap_data
            logger.info(f"Loaded GMAP '{gmap_name}': {gmap_data.width}x{gmap_data.height} segments")
            logger.debug(f"Segments: {list(gmap_data.segments.values())}")
        else:
            logger.error(f"Failed to parse GMAP file: {filename}")
            
    def enter_gmap(self, gmap_name: str):
        """Enter GMAP mode"""
        if gmap_name not in self.gmaps:
            logger.warning(f"Entering unknown GMAP: {gmap_name}")
            
        self.current_gmap = gmap_name
        self._is_active = True
        logger.info(f"Entered GMAP mode: {gmap_name}")
        
        # Emit event
        self.client.events.emit('gmap_mode_changed', {
            'is_gmap': True,
            'gmap_name': gmap_name,
            'level_name': self.client.level_manager.current_level.name if self.client.level_manager.current_level else None
        })
        
    def exit_gmap(self):
        """Exit GMAP mode"""
        if not self._is_active:
            return
            
        logger.info(f"Exiting GMAP mode (was in: {self.current_gmap})")
        self.current_gmap = None
        self.current_segment = None
        self._is_active = False
        
        # Clear player GMAP coordinates
        if self.client.local_player:
            self.client.local_player.gmaplevelx = None
            self.client.local_player.gmaplevely = None
            
        # Emit event
        self.client.events.emit('gmap_mode_changed', {
            'is_gmap': False,
            'gmap_name': None,
            'level_name': self.client.level_manager.current_level.name if self.client.level_manager.current_level else None
        })
        
    def update_segment_from_level(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Update current segment based on level name"""
        if not self._is_active or not self.current_gmap:
            return None
            
        gmap_data = self.gmaps.get(self.current_gmap)
        if not gmap_data:
            return None
            
        # Find segment coordinates for this level
        for (x, y), seg_level in gmap_data.segments.items():
            if seg_level == level_name:
                self.current_segment = (x, y)
                logger.info(f"Updated GMAP segment to ({x}, {y}) for level {level_name}")
                
                # Update player GMAP coordinates
                if self.client.local_player:
                    self.client.local_player.gmaplevelx = x
                    self.client.local_player.gmaplevely = y
                    
                return (x, y)
                
        logger.warning(f"Level {level_name} not found in GMAP {self.current_gmap}")
        return None
        
    def get_segment_for_position(self, x: float, y: float) -> Optional[Tuple[int, int]]:
        """Calculate which segment a world position is in"""
        if not self._is_active:
            return None
            
        # Each segment is 64x64 tiles
        segment_x = int(x // 64)
        segment_y = int(y // 64)
        
        return (segment_x, segment_y)
        
    def get_world_position(self, local_x: float, local_y: float) -> Tuple[float, float]:
        """Convert local position to world position based on current segment"""
        if not self._is_active or not self.current_segment:
            return (local_x, local_y)
            
        world_x = self.current_segment[0] * 64 + local_x
        world_y = self.current_segment[1] * 64 + local_y
        
        return (world_x, world_y)
        
    def is_level_in_current_gmap(self, level_name: str) -> bool:
        """Check if a level is part of the current GMAP"""
        if not self._is_active or not self.current_gmap:
            return False
            
        gmap_data = self.gmaps.get(self.current_gmap)
        if not gmap_data:
            return False
            
        return level_name in gmap_data.segments.values()
        
    def get_adjacent_segments(self) -> Dict[str, Optional[str]]:
        """Get adjacent segment level names"""
        result = {
            'north': None,
            'south': None,
            'east': None,
            'west': None
        }
        
        if not self._is_active or not self.current_segment or not self.current_gmap:
            return result
            
        gmap_data = self.gmaps.get(self.current_gmap)
        if not gmap_data:
            return result
            
        x, y = self.current_segment
        
        # Check each direction
        if (x, y-1) in gmap_data.segments:
            result['north'] = gmap_data.segments[(x, y-1)]
        if (x, y+1) in gmap_data.segments:
            result['south'] = gmap_data.segments[(x, y+1)]
        if (x+1, y) in gmap_data.segments:
            result['east'] = gmap_data.segments[(x+1, y)]
        if (x-1, y) in gmap_data.segments:
            result['west'] = gmap_data.segments[(x-1, y)]
            
        return result