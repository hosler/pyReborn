"""
Extended Level Manager
======================

Extends the standard level manager with GMAP segment mapping capabilities.
This provides the missing update_segment_from_level method and better GMAP integration.
"""

import logging
from typing import Optional, Tuple, Dict, Any
from pyreborn.managers.level_manager import LevelManager
from pyreborn.models.level import Level
# Import GMAPSegmentMapper with absolute path
import sys
import os
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)
from utils.gmap_segment_mapper import GMAPSegmentMapper


logger = logging.getLogger(__name__)


class ExtendedLevelManager(LevelManager):
    """Extended level manager with GMAP segment mapping"""
    
    def __init__(self):
        """Initialize extended level manager"""
        super().__init__()
        self.segment_mapper = GMAPSegmentMapper()
        self._segment_cache: Dict[str, Tuple[int, int]] = {}
        
        logger.info("Extended Level Manager initialized with segment mapping")
    
    def update_segment_from_level(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Get the GMAP segment coordinates for a level
        
        This is the missing method that level_link_manager needs!
        
        Args:
            level_name: Name of the level (e.g., 'chicken1.nw')
            
        Returns:
            (segment_x, segment_y) or None if not in GMAP
        """
        # Check cache first
        if level_name in self._segment_cache:
            return self._segment_cache[level_name]
        
        # Get segment from mapper
        segment = self.segment_mapper.get_segment_for_level(level_name)
        
        if segment:
            # Cache the result
            self._segment_cache[level_name] = segment
            logger.debug(f"Level {level_name} mapped to segment {segment}")
        else:
            logger.debug(f"Level {level_name} is not in current GMAP")
        
        return segment
    
    def get_level_at_segment(self, seg_x: int, seg_y: int) -> Optional[str]:
        """Get the level name at a specific GMAP segment
        
        Args:
            seg_x: Segment X coordinate
            seg_y: Segment Y coordinate
            
        Returns:
            Level name or None if no level at that segment
        """
        # Calculate world coordinates for segment center
        world_x = seg_x * 64 + 32
        world_y = seg_y * 64 + 32
        
        # Use mapper to find level
        return self.segment_mapper.get_level_at_world_coordinates(world_x, world_y)
    
    def handle_gmap_file(self, filename: str, file_data: bytes) -> bool:
        """Handle GMAP file received from server
        
        Override parent method to parse GMAP for segment mapping.
        
        Args:
            filename: GMAP filename
            file_data: Raw GMAP data
            
        Returns:
            True if handled successfully
        """
        # Parse GMAP for segment mapping FIRST
        if self.segment_mapper.parse_gmap_file(filename, file_data):
            self.segment_mapper.set_current_gmap(filename)
            logger.info(f"✅ Parsed GMAP {filename} for segment mapping")
            
            # Clear segment cache when GMAP changes
            self._segment_cache.clear()
            
            # Now we have the mapping, let parent do its processing
            result = super().handle_gmap_file(filename, file_data)
            return result
        else:
            logger.warning(f"Failed to parse GMAP {filename} for segment mapping")
            # Still let parent try to handle it
            return super().handle_gmap_file(filename, file_data)
    
    def is_level_in_current_gmap(self, level_name: str) -> bool:
        """Check if a level is part of the current GMAP
        
        Args:
            level_name: Level to check
            
        Returns:
            True if level is in current GMAP
        """
        return self.segment_mapper.is_level_in_gmap(level_name)
    
    def calculate_world_coordinates(self, level_name: str, local_x: float, local_y: float) -> Optional[Tuple[float, float]]:
        """Calculate world coordinates from local coordinates
        
        Args:
            level_name: Current level name
            local_x: Local X coordinate in tiles
            local_y: Local Y coordinate in tiles
            
        Returns:
            (world_x, world_y) or None if not in GMAP
        """
        return self.segment_mapper.calculate_world_coordinates(level_name, local_x, local_y)
    
    def get_segment_mapper_stats(self) -> Dict[str, Any]:
        """Get statistics from the segment mapper
        
        Returns:
            Statistics dictionary
        """
        return self.segment_mapper.get_statistics()
    
    def refresh_segment_cache(self) -> None:
        """Refresh the segment cache (useful after GMAP changes)"""
        self._segment_cache.clear()
        logger.info("Cleared segment cache for refresh")