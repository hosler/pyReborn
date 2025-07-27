"""
Simple GMAP Preloader that respects server adjacency rules

The gserver will only send segments that are adjacent to the player's current level.
This preloader tracks the player's position and requests only the 8 adjacent segments.

This version integrates better with PyReborn's level manager file request system.
"""

import threading
import time
import logging
from typing import Set, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

class SimpleGmapPreloader:
    """Preload adjacent GMAP segments as player moves"""
    
    def __init__(self, gmap_handler, client):
        self.gmap_handler = gmap_handler
        self.client = client
        
        # Track current position
        self.current_segment_x = None
        self.current_segment_y = None
        
        # Track which segments we've already requested
        self.requested_segments = set()
        
        # Threading
        self.running = False
        self.thread = None
        self.check_interval = 2.0  # Check every 2.0 seconds (respecting server limits)
        
        # Event subscription
        self._setup_events()
        
    def _setup_events(self):
        """Subscribe to PyReborn events"""
        if hasattr(self.client, 'events') and self.client.events:
            # Subscribe to level change events
            from pyreborn.core.events import EventType
            self.client.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
            self.client.events.subscribe(EventType.GMAP_MODE_CHANGED, self._on_gmap_mode_changed)
            logger.info("GMAP Preloader subscribed to events")
        
    def start(self):
        """Start the preloader thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            logger.info("[PRELOADER] Started simple GMAP preloader")
    
    def stop(self):
        """Stop the preloader thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            logger.info("[PRELOADER] Stopped simple GMAP preloader")
    
    def _on_level_entered(self, event: Dict):
        """Handle level entered event from PyReborn"""
        level = event.get('level')
        if level:
            logger.debug(f"[PRELOADER] Level entered: {level.name}")
            # Trigger immediate check for adjacent segments
            if self.running:
                self._check_and_request_adjacent()
    
    def _on_gmap_mode_changed(self, event: Dict):
        """Handle GMAP mode change event"""
        is_gmap = event.get('is_gmap', False)
        gmap_name = event.get('gmap_name')
        logger.info(f"[PRELOADER] GMAP mode changed: {is_gmap}, GMAP: {gmap_name}")
        if is_gmap and self.running:
            # Reset state when entering GMAP
            self.current_segment_x = None
            self.current_segment_y = None
            self.requested_segments.clear()
    
    def on_segment_loaded(self, segment_name: str):
        """Called when a segment is loaded"""
        # Remove from requested set so we can re-request if needed later
        self.requested_segments.discard(segment_name)
    
    def _worker(self):
        """Worker thread that checks for segments to preload"""
        while self.running:
            try:
                self._check_and_request_adjacent()
            except Exception as e:
                logger.error(f"[PRELOADER] Error in worker: {e}")
            
            time.sleep(self.check_interval)
    
    def _check_and_request_adjacent(self):
        """Check player position and request adjacent segments"""
        # Get current player position from client if available
        if hasattr(self.client, 'is_gmap_mode') and not self.client.is_gmap_mode:
            logger.debug("[PRELOADER] Not in GMAP mode, skipping")
            return
            
        # Get current level from client's level manager
        current_level = None
        if hasattr(self.client, 'level_manager') and self.client.level_manager:
            current_level = self.client.level_manager.current_level
            
        if not current_level:
            logger.debug("[PRELOADER] No current level")
            return
            
        level_name = current_level.name
        
        # Parse current segment
        segment_info = self.gmap_handler.parse_segment_name(level_name)
        if not segment_info:
            logger.debug(f"[PRELOADER] Cannot parse segment name: {level_name}")
            return
            
        base_name, seg_x, seg_y = segment_info
        
        # Check if we moved to a new segment
        if seg_x != self.current_segment_x or seg_y != self.current_segment_y:
            logger.info(f"[PRELOADER] Player moved to segment [{seg_x}, {seg_y}]")
            self.current_segment_x = seg_x
            self.current_segment_y = seg_y
            
            # Clear requested set when entering new segment
            # This allows re-requesting segments that may have failed before
            self.requested_segments.clear()
        
        # Get all 8 adjacent segments using PyReborn's GMAP data if available
        if hasattr(self.client.level_manager, 'gmap_data') and base_name in self.client.level_manager.gmap_data:
            # Use PyReborn's GMAP parser data
            gmap_parser = self.client.level_manager.gmap_data[base_name]
            adjacent_dict = gmap_parser.get_adjacent_segments(seg_x, seg_y)
            adjacent_segments = list(adjacent_dict.values())
            logger.debug(f"[PRELOADER] Using PyReborn GMAP data, found {len(adjacent_segments)} adjacent")
        else:
            # Fallback to our own adjacent calculation
            adjacent_segments = list(self._get_adjacent_segments(seg_x, seg_y))
            logger.debug(f"[PRELOADER] Using fallback calculation, found {len(adjacent_segments)} adjacent")
        
        # Check with level manager for already loaded/requested levels
        # Get the real level manager from PyReborn client
        level_manager = self.client.level_manager if hasattr(self.client, 'level_manager') else None
        if not level_manager:
            logger.debug("[PRELOADER] No level manager available")
            return
            
        requested_count = 0
        
        for segment_name in adjacent_segments:
            # Skip if already loaded
            if segment_name in level_manager.levels:
                logger.debug(f"[PRELOADER] {segment_name} already loaded")
                continue
                
            # Skip if already in requested files
            if segment_name in level_manager.requested_files:
                logger.debug(f"[PRELOADER] {segment_name} already requested")
                continue
                
            # Skip if we already requested it
            if segment_name in self.requested_segments:
                logger.debug(f"[PRELOADER] {segment_name} already in our requested set")
                continue
            
            # Use level manager's request_file to respect rate limiting
            logger.info(f"[PRELOADER] Requesting adjacent segment: {segment_name}")
            level_manager.request_file(segment_name)
            self.requested_segments.add(segment_name)
            requested_count += 1
            
            # Only request one per check to respect server limits
            # The level manager will handle queuing and rate limiting
            break
            
        if requested_count > 0:
            logger.info(f"[PRELOADER] Requested {requested_count} adjacent segments")
    
    def _get_adjacent_segments(self, center_x: int, center_y: int) -> Set[str]:
        """Get the 8 segments adjacent to the given position"""
        adjacent = set()
        
        # Check all 8 surrounding positions
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue  # Skip center
                    
                seg_x = center_x + dx
                seg_y = center_y + dy
                
                # Only add valid segments (non-negative coordinates)
                if seg_x >= 0 and seg_y >= 0:
                    segment_name = self.gmap_handler.get_segment_name(seg_x, seg_y)
                    if (segment_name and 
                        not segment_name.startswith(f"{self.gmap_handler.current_gmap}-INVALID")):
                        adjacent.add(segment_name)
        
        return adjacent
    
    def get_preload_status(self) -> dict:
        """Get current preload status for debugging"""
        if self.current_segment_x is None:
            return {"status": "Not initialized"}
            
        adjacent = self._get_adjacent_segments(self.current_segment_x, self.current_segment_y)
        loaded = sum(1 for seg in adjacent if self.gmap_handler.is_segment_loaded(seg))
        
        return {
            "current_segment": f"[{self.current_segment_x}, {self.current_segment_y}]",
            "adjacent_segments": len(adjacent),
            "loaded_segments": loaded,
            "requested_segments": len(self.requested_segments)
        }