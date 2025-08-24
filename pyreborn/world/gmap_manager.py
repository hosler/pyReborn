"""
GMAP Manager - Multi-level world management

Handles GMAP (Reborn Map) functionality:
- GMAP file parsing and loading
- Multi-level world navigation
- Seamless level transitions
- Level-to-segment mapping
- World coordinate-based level resolution
"""

import logging
import os
import time
import threading
from typing import Dict, List, Optional, Tuple, Set, Union, Any
from dataclasses import dataclass, field

from .gmap_resolver import GMapResolver, CoordinateInfo


@dataclass
class GMAPLevel:
    """Represents a level within a GMAP"""
    name: str
    x: int  # Segment X coordinate
    y: int  # Segment Y coordinate
    filename: Optional[str] = None
    
    
@dataclass
class GMAPData:
    """Represents a complete GMAP structure"""
    name: str
    width: int  # Width in segments
    height: int  # Height in segments
    levels: Dict[Tuple[int, int], GMAPLevel] = field(default_factory=dict)
    level_names: Dict[str, GMAPLevel] = field(default_factory=dict)
    

class GMAPManager:
    """Manages GMAP worlds and multi-level navigation"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Current GMAP state
        self.current_gmap: Optional[GMAPData] = None
        self.enabled = False
        self.gmap_mode = False  # Add gmap_mode property
        
        # Level tracking
        self.loaded_levels: Set[str] = set()
        self.adjacent_levels: Dict[str, List[str]] = {}
        
        # Enhanced resolution system
        self.resolver = GMapResolver()
        
        # Current world coordinates and resolved level
        self.current_world_x: Optional[float] = None
        self.current_world_y: Optional[float] = None
        self.resolved_level_name: Optional[str] = None
        
        # Movement state tracking for coordinate and level name continuity
        self.client_movement_active = False
        self.last_client_movement_time = 0.0
        self.movement_timeout = 0.1  # seconds - SHORT timeout to prevent infinite loops
        self.pending_client_coords: Optional[Tuple[float, float]] = None
        self.pending_client_level: Optional[str] = None
        
        # Client reference for automatic downloads
        self.client = None
        self.requested_files: Set[str] = set()
        self.failed_requests: Dict[str, int] = {}  # Track failed request counts
        self.max_retry_attempts = 3
        
        # Download progress tracking
        self.download_stats = {
            'gmap_files_requested': 0,
            'level_files_requested': 0,
            'total_files_requested': 0,
            'failed_requests': 0,
            'successful_downloads': 0,
            'cache_hits': 0,
            'last_request_time': None,
            'download_start_time': None
        }
        
        # Delayed request tracking
        self.pending_requests = []  # List of delayed requests waiting for GMAP structure
    
    def set_client(self, client):
        """Set client reference for automatic downloads
        
        Args:
            client: PyReborn client instance that can request files
        """
        self.client = client
        self.logger.debug("Client reference set for GMAP automatic downloads")
        
    def load_gmap_data(self, gmap_name: str, levels_data: Dict[str, Tuple[int, int]]):
        """Load GMAP data from level mapping"""
        self.logger.info(f"Loading GMAP: {gmap_name}")
        
        # Create GMAP data structure
        gmap_data = GMAPData(name=gmap_name, width=0, height=0)
        
        # Process each level
        for level_name, (seg_x, seg_y) in levels_data.items():
            level = GMAPLevel(name=level_name, x=seg_x, y=seg_y)
            gmap_data.levels[(seg_x, seg_y)] = level
            gmap_data.level_names[level_name] = level
            
            # Update GMAP dimensions
            gmap_data.width = max(gmap_data.width, seg_x + 1)
            gmap_data.height = max(gmap_data.height, seg_y + 1)
            
        self.current_gmap = gmap_data
        self.enabled = True
        
        # Register with resolver for intelligent level resolution
        self.resolver.register_gmap_structure(gmap_name, levels_data)
        
        self.logger.info(f"GMAP loaded: {len(levels_data)} levels, {gmap_data.width}x{gmap_data.height} segments")
        
    def parse_gmap_file(self, gmap_path: str) -> Optional[GMAPData]:
        """Parse a .gmap file (basic implementation)"""
        if not os.path.exists(gmap_path):
            self.logger.error(f"GMAP file not found: {gmap_path}")
            return None
            
        try:
            gmap_name = os.path.basename(gmap_path).replace('.gmap', '')
            gmap_data = GMAPData(name=gmap_name, width=0, height=0)
            
            with open(gmap_path, 'r') as f:
                lines = f.readlines()
                
            current_y = 0
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                levels = line.split()
                for x, level_name in enumerate(levels):
                    if level_name and level_name != '0':
                        level = GMAPLevel(name=level_name, x=x, y=current_y)
                        gmap_data.levels[(x, current_y)] = level
                        gmap_data.level_names[level_name] = level
                        
                gmap_data.width = max(gmap_data.width, len(levels))
                current_y += 1
                
            gmap_data.height = current_y
            
            # Also register with resolver
            levels_data = {level.name: (level.x, level.y) for level in gmap_data.levels.values()}
            self.resolver.register_gmap_structure(gmap_name + '.gmap', levels_data)
            
            self.logger.info(f"Parsed GMAP file: {gmap_path} ({gmap_data.width}x{gmap_data.height})")
            return gmap_data
            
        except Exception as e:
            self.logger.error(f"Failed to parse GMAP file {gmap_path}: {e}")
            return None
    
    def parse_gmap_content(self, gmap_content: str, gmap_name: str) -> Optional[GMAPData]:
        """Parse GMAP content from string data
        
        Args:
            gmap_content: GMAP file content as string
            gmap_name: Name of the GMAP file
            
        Returns:
            Parsed GMAPData or None if parsing failed
        """
        try:
            gmap_data = GMAPData(name=gmap_name, width=0, height=0)
            lines = gmap_content.strip().split('\n')
            
            # Parse GRMAP001 format
            in_levelnames_section = False
            current_y = 0
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if line == 'LEVELNAMES':
                    in_levelnames_section = True
                    continue
                elif line == 'LEVELNAMESEND':
                    break
                elif line.startswith('WIDTH'):
                    gmap_data.width = int(line.split()[1])
                elif line.startswith('HEIGHT'):
                    gmap_data.height = int(line.split()[1])
                elif in_levelnames_section:
                    # Parse level names: "level1.nw","level2.nw","level3.nw",
                    # Remove quotes and comma, split by comma
                    level_names = [name.strip().strip('"').strip(',') for name in line.split(',') if name.strip()]
                    
                    for x, level_name in enumerate(level_names):
                        if level_name and level_name != '0':
                            level = GMAPLevel(name=level_name, x=x, y=current_y)
                            gmap_data.levels[(x, current_y)] = level
                            gmap_data.level_names[level_name] = level
                    
                    current_y += 1
            
            # Register with resolver
            levels_data = {level.name: (level.x, level.y) for level in gmap_data.levels.values()}
            self.resolver.register_gmap_structure(gmap_name, levels_data)
            
            self.logger.info(f"✅ Parsed GMAP content: {gmap_name} ({gmap_data.width}x{gmap_data.height}, {len(gmap_data.levels)} levels)")
            
            # Process any pending requests now that structure is available
            if hasattr(self, 'pending_requests'):
                self._process_pending_requests()
            
            return gmap_data
            
        except Exception as e:
            self.logger.error(f"Failed to parse GMAP content for {gmap_name}: {e}")
            return None
            
    def enable_gmap(self, gmap_data: GMAPData):
        """Enable GMAP mode with given data"""
        self.current_gmap = gmap_data
        self.enabled = True
        self.logger.info(f"GMAP mode enabled: {gmap_data.name}")
        
    def disable_gmap(self):
        """Disable GMAP mode"""
        self.enabled = False
        self.gmap_mode = False
        self.current_gmap = None
        self.loaded_levels.clear()
        self.adjacent_levels.clear()
        
        # Clear world coordinate state
        self.current_world_x = None
        self.current_world_y = None
        self.resolved_level_name = None
        
        self.logger.info("GMAP mode disabled")
        
    def is_enabled(self) -> bool:
        """Check if GMAP mode is enabled"""
        return self.enabled and self.current_gmap is not None
        
    def is_gmap_level(self, level_name: str) -> bool:
        """Check if a level is part of the current GMAP"""
        if not self.current_gmap:
            return False
        return level_name in self.current_gmap.level_names
        
    def get_level_segment(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Get segment coordinates for a level"""
        if not self.current_gmap:
            return None
            
        level = self.current_gmap.level_names.get(level_name)
        if level:
            return level.x, level.y
        return None
        
    def get_level_at_segment(self, seg_x: int, seg_y: int) -> Optional[str]:
        """Get level name at specific segment coordinates"""
        if not self.current_gmap:
            return None
            
        level = self.current_gmap.levels.get((seg_x, seg_y))
        return level.name if level else None
        
    def get_adjacent_levels(self, level_name: str) -> List[str]:
        """Get adjacent levels for seamless navigation"""
        if level_name in self.adjacent_levels:
            return self.adjacent_levels[level_name]
            
        adjacent = []
        segment = self.get_level_segment(level_name)
        if not segment or not self.current_gmap:
            return adjacent
            
        seg_x, seg_y = segment
        
        # Check all 8 directions (including diagonals)
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                    
                adj_x, adj_y = seg_x + dx, seg_y + dy
                adj_level = self.get_level_at_segment(adj_x, adj_y)
                if adj_level:
                    adjacent.append(adj_level)
                    
        self.adjacent_levels[level_name] = adjacent
        return adjacent
        
    def should_preload_level(self, level_name: str, current_level: str) -> bool:
        """Determine if a level should be preloaded for smooth transitions"""
        if not self.is_enabled():
            return False
            
        # Always preload adjacent levels
        adjacent = self.get_adjacent_levels(current_level)
        return level_name in adjacent
        
    def mark_level_loaded(self, level_name: str):
        """Mark a level as loaded"""
        self.loaded_levels.add(level_name)
        self.logger.debug(f"Level marked as loaded: {level_name}")
        
    def is_level_loaded(self, level_name: str) -> bool:
        """Check if a level is loaded"""
        return level_name in self.loaded_levels
        
    def world_to_segment(self, world_x: float, world_y: float) -> Tuple[int, int, float, float]:
        """Convert world coordinates to segment and local coordinates"""
        seg_x = int(world_x // 64)
        seg_y = int(world_y // 64)
        local_x = world_x % 64
        local_y = world_y % 64
        return seg_x, seg_y, local_x, local_y
        
    def get_level_at_position(self, seg_x: int, seg_y: int) -> Optional[str]:
        """Get level at segment position"""
        return self.get_level_at_segment(seg_x, seg_y)
    
    def get_world_bounds(self) -> Tuple[int, int]:
        """Get world bounds in tiles"""
        if not self.current_gmap:
            return 64, 64  # Single level default
            
        width_tiles = self.current_gmap.width * 64
        height_tiles = self.current_gmap.height * 64
        return width_tiles, height_tiles
        
    def get_gmap_info(self) -> Optional[Dict]:
        """Get information about current GMAP"""
        if not self.current_gmap:
            return None
            
        return {
            'name': self.current_gmap.name,
            'enabled': self.enabled,
            'dimensions': {
                'width': self.current_gmap.width,
                'height': self.current_gmap.height,
                'total_segments': len(self.current_gmap.levels)
            },
            'loaded_levels': list(self.loaded_levels),
            'level_count': len(self.current_gmap.level_names)
        }
        
    def update_world_position(self, world_x: float, world_y: float, gmap_name: str = None) -> Optional[str]:
        """Update world position and resolve current level name.
        
        This method is called by server packets like PLO_GMAPWARP2. It respects active
        client movement to prevent coordinate wrapping during GMAP traversal.
        
        Args:
            world_x: World X coordinate (from x2 property)
            world_y: World Y coordinate (from y2 property) 
            gmap_name: Optional GMAP name override
            
        Returns:
            Resolved level name or None if resolution fails
        """
        # 🎯 FIX: Check if client movement is active to prevent coordinate wrapping
        if self.is_client_movement_active():
            # Client movement is active - use pending client coordinates instead
            pending_x, pending_y = self.pending_client_coords
            # Use throttled logging for server updates
            if not hasattr(self, '_last_server_update_log') or time.time() - self._last_server_update_log > 2.0:
                self.logger.debug(f"🎯 Server update blocked by client movement: server({world_x:.1f},{world_y:.1f}) → using client({pending_x:.1f},{pending_y:.1f})")
                self._last_server_update_log = time.time()
            world_x, world_y = pending_x, pending_y
        else:
            # No active client movement - validate server coordinates before accepting
            if not self.validate_coordinate_change(world_x, world_y):
                if not hasattr(self, '_last_reject_log') or time.time() - self._last_reject_log > 5.0:
                    self.logger.warning(f"🚫 Rejecting server coordinate update due to suspicious change")
                    self._last_reject_log = time.time()
                return self.resolved_level_name  # Keep current state
            # Throttle debug messages for server updates
            if not hasattr(self, '_last_coord_update_log') or time.time() - self._last_coord_update_log > 2.0:
                self.logger.debug(f"🎯 Server coordinate update: ({world_x:.1f},{world_y:.1f})")
                self._last_coord_update_log = time.time()
        
        self.current_world_x = world_x
        self.current_world_y = world_y
        
        # 🎯 FIX: Try to auto-enable GMAP if we're getting coordinate updates but not enabled
        if not self.is_enabled():
            if gmap_name:
                # We have a GMAP name but manager is not enabled - try to enable it
                self.logger.info(f"🔧 Auto-enabling GMAP for coordinate update: {gmap_name}")
                if hasattr(self, 'check_and_parse_downloaded_gmap_file'):
                    self.check_and_parse_downloaded_gmap_file(gmap_name)
                    
            if not self.is_enabled():
                self.logger.warning("🚫 GMAP manager not enabled for coordinate update")
                return None
            
        # Use current GMAP or provided override
        target_gmap = gmap_name or (self.current_gmap.name if self.current_gmap else None)
        if not target_gmap:
            self.logger.warning("🚫 No target GMAP name for coordinate update")
            return None
            
        # Resolve level name using world coordinates
        resolved_name = self.resolver.resolve_level_from_world_coords(
            target_gmap, world_x, world_y, scale_hint="auto"
        )
        
        if resolved_name:
            self.resolved_level_name = resolved_name
            
            # 🎯 FIXED: world_x, world_y are now ACTUAL world coordinates from PLO_GMAPWARP2
            # No additional calculation needed since packet processing now handles it correctly
            self.current_world_x = world_x
            self.current_world_y = world_y
            
            # Calculate segment from world coordinates for adjacent level loading
            try:
                import math
                segment_x = math.floor(world_x / 64)
                segment_y = math.floor(world_y / 64)
                local_x = world_x % 64
                local_y = world_y % 64
                
                # Throttle position logging to avoid spam
                if not hasattr(self, '_last_position_log') or time.time() - self._last_position_log > 3.0:
                    self.logger.info(f"🎯 GMAP position: world({world_x:.1f},{world_y:.1f}) = segment({segment_x},{segment_y}) + local({local_x:.1f},{local_y:.1f})")
                    self._last_position_log = time.time()
                
                # Auto-request adjacent levels (with GMAP structure check) - throttle this too
                if not hasattr(self, '_last_adjacent_request_log') or time.time() - self._last_adjacent_request_log > 5.0:
                    self.logger.info(f"🚀 Auto-requesting adjacent levels for segment ({segment_x},{segment_y})")
                    self._last_adjacent_request_log = time.time()
                if self._is_gmap_structure_available():
                    self._request_adjacent_levels(gmap_name, segment_x, segment_y)
                else:
                    self.logger.info(f"⏳ GMAP structure not ready - deferring adjacent level requests")
                    # Schedule delayed retry when GMAP structure becomes available
                    self._schedule_delayed_level_requests(gmap_name, segment_x, segment_y)
                
                # 🎯 CRITICAL: Preload cached levels for GMAP rendering
                self._preload_cached_levels_for_gmap()
                
            except Exception as e:
                self.logger.error(f"Error calculating segment coordinates: {e}")
                # Still store world coordinates even if segment calculation fails
                self.current_world_x = world_x
                self.current_world_y = world_y
            
            self.logger.info(f"🎯 Resolved world position -> {resolved_name}")
        else:
            self.logger.warning(f"❌ Could not resolve level at world position ({world_x:.2f},{world_y:.2f})")
            
        return resolved_name
        
    def get_effective_level_name(self) -> Optional[str]:
        """Get the effective level name (resolved actual level, not GMAP filename).
        
        This performs real-time position-based resolution to ensure the correct
        level is returned based on current player position.
        
        Returns:
            Resolved level name if in GMAP mode, otherwise None
        """
        if not self.is_enabled():
            return None
            
        # 🎯 FIX: Do real-time position-based resolution instead of using stale resolved_level_name
        if (self.current_world_x is not None and self.current_world_y is not None and 
            self.current_gmap):
            # Get current position-based resolution
            current_resolved = self.resolve_world_position(self.current_world_x, self.current_world_y)
            if current_resolved:
                # Update cached resolved level name
                self.resolved_level_name = current_resolved
                return current_resolved
        
        # Fallback to cached resolved level name if real-time resolution fails
        return self.resolved_level_name
        
    def enter_gmap_mode(self, gmap_name: str, world_x: float = None, world_y: float = None,
                       segment_x: int = None, segment_y: int = None) -> Optional[str]:
        """Enter GMAP mode with optional position information.
        
        Args:
            gmap_name: Name of the GMAP
            world_x: World X coordinate (preferred)
            world_y: World Y coordinate (preferred)
            segment_x: GMAP segment X (fallback)
            segment_y: GMAP segment Y (fallback)
            
        Returns:
            Resolved level name or None
        """
        self.gmap_mode = True
        self.enabled = True
        
        # 🚀 AUTOMATIC GMAP FILE DOWNLOAD
        self._request_gmap_file(gmap_name)
        
        # 🎯 FIX: Download all GMAP levels proactively  
        self.request_comprehensive_gmap_download(gmap_name, force_all=True)
        
        # Try world coordinate resolution first
        if world_x is not None and world_y is not None:
            resolved_name = self.update_world_position(world_x, world_y, gmap_name)
            if resolved_name:
                return resolved_name
                
        # Fallback to segment-based resolution
        if segment_x is not None and segment_y is not None:
            resolved_name = self.resolver.resolve_level_from_segment(gmap_name, segment_x, segment_y)
            if resolved_name:
                self.resolved_level_name = resolved_name
                self.logger.info(f"🎯 Resolved segment ({segment_x},{segment_y}) -> {resolved_name}")
                return resolved_name
                
        self.logger.warning(f"❌ Could not resolve level for GMAP {gmap_name}")
        return None
        
    def get_coordinate_info(self) -> Optional[CoordinateInfo]:
        """Get comprehensive coordinate information for current position.
        
        Returns:
            CoordinateInfo object or None if not in GMAP mode
        """
        if not self.is_enabled() or not self.current_gmap:
            return None
            
        if self.current_world_x is None or self.current_world_y is None:
            return None
            
        return self.resolver.get_coordinate_info(
            self.current_gmap.name, self.current_world_x, self.current_world_y
        )
    
    def set_client_movement_active(self, world_x: float, world_y: float, level_name: str = None):
        """Mark that client-initiated movement is active with pending coordinates and level
        
        This prevents server PLO_GMAPWARP2 and PLO_LEVELNAME packets from overriding client-calculated 
        coordinates and level names during active movement periods.
        
        Args:
            world_x: Client-calculated world X coordinate  
            world_y: Client-calculated world Y coordinate
            level_name: Client-calculated resolved level name
        """
        self.client_movement_active = True
        self.last_client_movement_time = time.time()
        self.pending_client_coords = (world_x, world_y)
        self.pending_client_level = level_name
        # Throttle client movement debug messages
        if not hasattr(self, '_last_movement_log') or time.time() - self._last_movement_log > 2.0:
            self.logger.debug(f"🎯 Client movement active: pending coords ({world_x:.1f},{world_y:.1f}) level='{level_name}'")
            self._last_movement_log = time.time()
    
    def clear_client_movement(self):
        """Clear client movement state - allows server packets to update coordinates and level names normally"""
        self.client_movement_active = False
        self.pending_client_coords = None
        self.pending_client_level = None
        # Throttle clear movement debug messages
        if not hasattr(self, '_last_clear_log') or time.time() - self._last_clear_log > 2.0:
            self.logger.debug("🎯 Client movement cleared - server updates allowed")
            self._last_clear_log = time.time()
    
    def is_client_movement_active(self) -> bool:
        """Check if client movement is still active (within timeout window)"""
        if not self.client_movement_active:
            return False
        
        # Check if movement has timed out
        current_time = time.time()
        if current_time - self.last_client_movement_time > self.movement_timeout:
            self.logger.debug("🎯 Client movement timed out - clearing state")
            self.clear_client_movement()
            return False
        
        return True
    
    def update_from_client_movement(self, world_x: float, world_y: float) -> str:
        """Update coordinates from client movement and resolve level name
        
        Args:
            world_x: Client-calculated world X coordinate
            world_y: Client-calculated world Y coordinate
            
        Returns:
            Resolved level name or None if resolution fails
        """
        # Resolve level name first  
        resolved_name = self.resolve_world_position(world_x, world_y)
        if resolved_name:
            self.resolved_level_name = resolved_name
        
        # Set movement active with coordinates AND level name protection
        self.set_client_movement_active(world_x, world_y, resolved_name)
        
        # Update current coordinates immediately
        self.current_world_x = world_x
        self.current_world_y = world_y
        
        self.logger.debug(f"🎯 Client movement update: ({world_x:.1f},{world_y:.1f}) → {resolved_name}")
        return resolved_name
    
    def should_accept_server_level_name(self, server_level_name: str) -> bool:
        """Check if server level name should be accepted or blocked by client movement
        
        Args:
            server_level_name: Level name from server PLO_LEVELNAME packet
            
        Returns:
            True if server level name should be accepted, False if it should be blocked
        """
        if not self.is_client_movement_active():
            # No active client movement - accept server level name
            return True
        
        # Check if server level matches our pending client level
        if self.pending_client_level and server_level_name == self.pending_client_level:
            # Server level matches client calculation - accept it and clear movement state
            self.logger.debug(f"🎯 Server level '{server_level_name}' matches client calculation - accepting and clearing movement state")
            self.clear_client_movement()  # Movement completed successfully
            return True
        
        # Server level conflicts with client movement - block it  
        self.logger.debug(f"🎯 Server level '{server_level_name}' conflicts with client level '{self.pending_client_level}' - blocking")
        return False
    
    def resolve_world_position(self, world_x: float, world_y: float) -> Optional[str]:
        """Resolve level name from world coordinates
        
        Args:
            world_x: World X coordinate
            world_y: World Y coordinate
            
        Returns:
            Resolved level name or None if resolution fails
        """
        if not self.is_enabled() or not self.current_gmap:
            # Try to load GMAP structure if we have a GMAP name
            if hasattr(self, 'current_gmap') and self.current_gmap and self.current_gmap.name:
                self.check_and_parse_downloaded_gmap_file(self.current_gmap.name)
            if not self.is_enabled() or not self.current_gmap:
                return None
            
        return self.resolver.resolve_level_from_world_coords(
            self.current_gmap.name, world_x, world_y, scale_hint="auto"
        )
    
    def validate_coordinate_change(self, new_x: float, new_y: float) -> bool:
        """Validate that coordinate change is reasonable (not a wrap/reset)
        
        Args:
            new_x: New world X coordinate
            new_y: New world Y coordinate
            
        Returns:
            True if coordinate change is reasonable, False if it looks like wrapping
        """
        if self.current_world_x is None or self.current_world_y is None:
            return True  # First coordinate set, always accept
        
        # Calculate movement distance
        dx = abs(new_x - self.current_world_x)
        dy = abs(new_y - self.current_world_y)
        
        # Flag as wrapping if movement is > 32 tiles (half a segment) in any direction
        max_reasonable_movement = 32.0
        if dx > max_reasonable_movement or dy > max_reasonable_movement:
            self.logger.warning(f"🚫 Suspicious coordinate change detected: ({self.current_world_x:.1f},{self.current_world_y:.1f}) → ({new_x:.1f},{new_y:.1f}) delta=({dx:.1f},{dy:.1f})")
            return False
        
        return True
        
    def is_gmap_mode(self) -> bool:
        """Check if currently in GMAP mode (as opposed to just having GMAP enabled)."""
        return self.gmap_mode and self.enabled
        
    def retry_failed_requests(self, force_all: bool = False):
        """Retry previously failed file requests if client is now authenticated
        
        Args:
            force_all: If True, retry all failed requests regardless of attempt count
        """
        if not self._is_client_authenticated():
            self.logger.debug("Client not authenticated - cannot retry failed requests")
            return 0
        
        failed_files = list(self.failed_requests.keys())
        if not failed_files:
            self.logger.debug("No failed requests to retry")
            return 0
        
        retried_count = 0
        success_count = 0
        
        self.logger.info(f"🔄 Retrying {len(failed_files)} failed file requests (force_all={force_all})")
        
        for filename in failed_files:
            retry_count = self.failed_requests[filename]
            
            # Skip if exceeded max attempts (unless forced)
            if not force_all and retry_count >= self.max_retry_attempts:
                self.logger.debug(f"⚠️ Skipping {filename} - exceeded max attempts ({retry_count})")
                continue
            
            retried_count += 1
            
            # Try to request the file again
            if filename.endswith('.gmap'):
                # GMAP file - use GMAP-specific retry
                self._request_gmap_file_immediate(filename)
                success_count += 1  # Assume success for GMAP files
            else:
                # Level file - use level-specific retry
                if self._request_level_file(filename):
                    success_count += 1
        
        self.logger.info(f"📊 Retry summary: {retried_count} attempted, {success_count} successful")
        return success_count
    
    def retry_all_gmap_levels(self, gmap_name: str = None) -> int:
        """Retry requesting all levels in GMAP that haven't been successfully downloaded
        
        Args:
            gmap_name: Optional GMAP name override
            
        Returns:
            Number of levels successfully requested
        """
        if not self.current_gmap:
            self.logger.warning("No GMAP structure available for retry")
            return 0
        
        all_levels = list(self.current_gmap.level_names.keys())
        missing_levels = []
        
        # Find levels that haven't been requested or failed
        for level_name in all_levels:
            if level_name not in self.requested_files:
                missing_levels.append(level_name)
        
        if not missing_levels:
            self.logger.info("✅ All GMAP levels have been requested")
            return 0
        
        self.logger.info(f"🔄 Retrying {len(missing_levels)} missing GMAP levels")
        
        success_count = 0
        for level_name in missing_levels:
            if self._request_level_file(level_name):
                success_count += 1
        
        self.logger.info(f"📊 Missing level retry: {success_count}/{len(missing_levels)} successful")
        return success_count
    
    def request_comprehensive_gmap_download(self, gmap_name: str = None, force_all: bool = False) -> int:
        """Request comprehensive download of all GMAP levels with full reporting
        
        Args:
            gmap_name: Optional GMAP name override
            force_all: If True, retry all failed requests
            
        Returns:
            Number of levels successfully requested
        """
        self.logger.info("🚀 Starting comprehensive GMAP download...")
        
        # Step 1: Request all GMAP levels
        requested_count = self.request_all_gmap_levels(gmap_name)
        
        # Step 2: Retry any failed requests if requested
        if force_all:
            retry_count = self.retry_failed_requests(force_all=True)
            self.logger.info(f"🔄 Retried {retry_count} failed requests")
        
        # Step 3: Preload from cache
        self._preload_cached_levels_for_gmap()
        
        # Step 4: Print progress report
        self.print_download_report(detailed=True)
        
        # Step 5: Check cache coverage if possible
        if self.current_gmap and hasattr(self.client, 'cache_manager'):
            try:
                cache_manager = self.client.cache_manager
                if hasattr(cache_manager, 'get_cache_coverage_for_gmap'):
                    all_levels = list(self.current_gmap.level_names.keys())
                    coverage = cache_manager.get_cache_coverage_for_gmap(all_levels)
                    self.logger.info(f"💾 Cache coverage: {coverage['coverage_percentage']:.1f}% ({coverage['cached_count']}/{coverage['total_count']})")
                    
                    if coverage['missing_levels']:
                        self.logger.info(f"⚠️ Missing from cache: {len(coverage['missing_levels'])} levels")
                        if len(coverage['missing_levels']) <= 10:  # Show up to 10 missing levels
                            self.logger.info(f"   Missing: {', '.join(coverage['missing_levels'])}")
            except Exception as e:
                self.logger.debug(f"Could not check cache coverage: {e}")
        
        self.logger.info(f"✅ Comprehensive download complete: {requested_count} levels requested")
        return requested_count
    
    def get_download_progress(self) -> Dict[str, Any]:
        """Get comprehensive download progress statistics
        
        Returns:
            Dictionary with download progress information
        """
        progress = dict(self.download_stats)
        
        # Add calculated fields
        if self.current_gmap:
            total_gmap_levels = len(self.current_gmap.level_names)
            requested_levels = len([f for f in self.requested_files if not f.endswith('.gmap')])
            progress['total_gmap_levels'] = total_gmap_levels
            progress['requested_levels'] = requested_levels
            progress['completion_percentage'] = (requested_levels / total_gmap_levels * 100) if total_gmap_levels > 0 else 0
        else:
            progress['total_gmap_levels'] = 0
            progress['requested_levels'] = 0
            progress['completion_percentage'] = 0
        
        # Add timing information
        if progress['download_start_time']:
            progress['download_duration'] = time.time() - progress['download_start_time']
        else:
            progress['download_duration'] = 0
        
        # Add failure rate
        total_requests = progress['total_files_requested']
        failed_requests = progress['failed_requests']
        progress['failure_rate'] = (failed_requests / total_requests * 100) if total_requests > 0 else 0
        
        # Add current status
        progress['active_requests'] = len(self.requested_files)
        progress['pending_failures'] = len(self.failed_requests)
        
        return progress
    
    def print_download_report(self, detailed: bool = False):
        """Print a comprehensive download progress report
        
        Args:
            detailed: If True, show detailed breakdown
        """
        progress = self.get_download_progress()
        
        self.logger.info("📊 GMAP Download Progress Report")
        self.logger.info("=" * 50)
        
        # Overall progress
        if self.current_gmap:
            completion = progress['completion_percentage']
            self.logger.info(f"🎯 GMAP Coverage: {completion:.1f}% ({progress['requested_levels']}/{progress['total_gmap_levels']} levels)")
        else:
            self.logger.info("🎯 GMAP Coverage: No GMAP structure loaded")
        
        # Request statistics
        self.logger.info(f"📥 Total Requests: {progress['total_files_requested']}")
        self.logger.info(f"   └─ GMAP files: {progress['gmap_files_requested']}")
        self.logger.info(f"   └─ Level files: {progress['level_files_requested']}")
        
        # Success/failure rates
        if progress['total_files_requested'] > 0:
            success_rate = 100 - progress['failure_rate']
            self.logger.info(f"✅ Success Rate: {success_rate:.1f}%")
            self.logger.info(f"❌ Failure Rate: {progress['failure_rate']:.1f}%")
        
        # Timing information
        if progress['download_duration'] > 0:
            duration_mins = progress['download_duration'] / 60
            self.logger.info(f"⏱️ Download Duration: {duration_mins:.1f} minutes")
        
        # Current status
        if progress['active_requests'] > 0:
            self.logger.info(f"🔄 Active Requests: {progress['active_requests']}")
        if progress['pending_failures'] > 0:
            self.logger.info(f"⚠️ Pending Failures: {progress['pending_failures']}")
        
        # Detailed breakdown
        if detailed:
            self.logger.info("\n📋 Detailed Breakdown:")
            if self.requested_files:
                self.logger.info(f"✅ Successfully requested files:")
                for filename in sorted(self.requested_files):
                    self.logger.info(f"   └─ {filename}")
            
            if self.failed_requests:
                self.logger.info(f"❌ Failed requests:")
                for filename, attempts in self.failed_requests.items():
                    self.logger.info(f"   └─ {filename} ({attempts} attempts)")
        
        self.logger.info("=" * 50)
    
    def _update_download_stats(self, filename: str, success: bool, is_retry: bool = False):
        """Update download statistics
        
        Args:
            filename: Name of file being tracked
            success: Whether the request was successful
            is_retry: Whether this is a retry attempt
        """
        current_time = time.time()
        
        # Initialize timing if first request
        if self.download_stats['download_start_time'] is None:
            self.download_stats['download_start_time'] = current_time
        
        self.download_stats['last_request_time'] = current_time
        
        # Track request counts (only for new requests, not retries)
        if not is_retry:
            self.download_stats['total_files_requested'] += 1
            
            if filename.endswith('.gmap'):
                self.download_stats['gmap_files_requested'] += 1
            else:
                self.download_stats['level_files_requested'] += 1
        
        # Track success/failure
        if success:
            if not is_retry:
                self.download_stats['successful_downloads'] += 1
        else:
            self.download_stats['failed_requests'] += 1
    
    def cleanup(self):
        """Clean up GMAP resources"""
        self.disable_gmap()
        self.resolver.clear_cache()
        self.requested_files.clear()
        self.failed_requests.clear()
        self.pending_requests.clear()
        
        # Print final download report
        if self.download_stats['total_files_requested'] > 0:
            self.logger.info("📊 Final GMAP download report:")
            self.print_download_report(detailed=False)
        
        self.logger.debug("GMAP manager cleaned up")
    
    def _preload_cached_levels_for_gmap(self):
        """Preload all cached levels for better GMAP rendering performance"""
        if not self.client:
            self.logger.debug("No client available for cache preloading")
            return
        
        try:
            # Get level manager to trigger cache loading
            if hasattr(self.client, 'level_manager') and self.client.level_manager:
                level_manager = self.client.level_manager
                
                # Trigger cache loading if method exists
                if hasattr(level_manager, 'load_levels_from_cache_directory'):
                    cache_dir = self._get_cache_directory_path()
                    
                    if cache_dir:
                        self.logger.info(f"🔄 Preloading cached levels from: {cache_dir}")
                        
                        # Count existing levels before loading
                        existing_count = len(getattr(level_manager, 'levels', {}))
                        
                        # Load from cache
                        level_manager.load_levels_from_cache_directory(cache_dir)
                        
                        # Count levels after loading
                        new_count = len(getattr(level_manager, 'levels', {}))
                        loaded_count = new_count - existing_count
                        
                        if loaded_count > 0:
                            self.logger.info(f"✅ Preloaded {loaded_count} new levels for GMAP rendering (total: {new_count})")
                            self.download_stats['cache_hits'] += loaded_count
                        else:
                            self.logger.info(f"📦 No new levels found in cache (total cached: {new_count})")
                    else:
                        self.logger.debug("No cache directory available for preloading")
                else:
                    self.logger.debug("Level manager doesn't support cache directory loading")
            else:
                self.logger.debug("No level manager available for preloading")
                
        except Exception as e:
            self.logger.error(f"Error preloading cached levels: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
    
    def _get_cache_directory_path(self) -> Optional[str]:
        """Get the appropriate cache directory path for level files
        
        Returns:
            Cache directory path or None if not available
        """
        try:
            # Method 1: Try cache manager with server-specific directory
            if hasattr(self.client, 'cache_manager') and self.client.cache_manager:
                cache_manager = self.client.cache_manager
                
                # Try to get server-specific cache directory
                if hasattr(cache_manager, '_get_server_dir') and callable(cache_manager._get_server_dir):
                    try:
                        server_dir = cache_manager._get_server_dir()
                        if server_dir and server_dir.exists():
                            self.logger.debug(f"Found server-specific cache directory: {server_dir}")
                            return str(server_dir)
                    except Exception as e:
                        self.logger.debug(f"Could not get server-specific cache directory: {e}")
                
                # Try to get base cache directory and construct server path
                if hasattr(cache_manager, 'levels_dir') and cache_manager.levels_dir:
                    levels_dir = cache_manager.levels_dir
                    
                    # Try server-specific subdirectory
                    if hasattr(cache_manager, 'current_server') and hasattr(cache_manager, 'current_server_port'):
                        if cache_manager.current_server and cache_manager.current_server_port:
                            server_name = f"{cache_manager.current_server}_{cache_manager.current_server_port}"
                            server_name = server_name.replace(':', '_').replace('.', '_')
                            server_cache_dir = levels_dir / server_name
                            
                            if server_cache_dir.exists():
                                self.logger.debug(f"Found constructed server cache directory: {server_cache_dir}")
                                return str(server_cache_dir)
                    
                    # Fallback to levels directory if it exists
                    if levels_dir.exists():
                        self.logger.debug(f"Using base levels cache directory: {levels_dir}")
                        return str(levels_dir)
            
            # Method 2: Try legacy cache directory attribute
            if hasattr(self.client, 'cache_manager') and self.client.cache_manager:
                legacy_cache_dir = getattr(self.client.cache_manager, 'level_cache_dir', None)
                if legacy_cache_dir:
                    from pathlib import Path
                    cache_path = Path(legacy_cache_dir)
                    if cache_path.exists():
                        self.logger.debug(f"Using legacy cache directory: {cache_path}")
                        return str(cache_path)
            
            # Method 3: Try common cache locations
            common_cache_paths = [
                "cache/levels/localhost_14900",
                "cache/levels", 
                "../cache/levels/localhost_14900",
                "../cache/levels"
            ]
            
            for cache_path_str in common_cache_paths:
                from pathlib import Path
                cache_path = Path(cache_path_str)
                if cache_path.exists():
                    self.logger.debug(f"Found common cache directory: {cache_path}")
                    return str(cache_path.resolve())
            
            self.logger.debug("No cache directory found in any method")
            return None
            
        except Exception as e:
            self.logger.error(f"Error determining cache directory path: {e}")
            return None
    
    def _is_gmap_structure_available(self) -> bool:
        """Check if GMAP structure is available for level requests
        
        Returns:
            True if GMAP structure is loaded and ready
        """
        if not self.current_gmap:
            return False
        
        # Check if we have meaningful level data
        if not self.current_gmap.level_names:
            return False
        
        # Check if we have segment mapping
        if not self.current_gmap.levels:
            return False
        
        # Basic sanity check - should have reasonable dimensions
        if self.current_gmap.width <= 0 or self.current_gmap.height <= 0:
            return False
        
        return True
    
    def _schedule_delayed_level_requests(self, gmap_name: str, segment_x: int, segment_y: int):
        """Schedule level requests to be retried when GMAP structure becomes available
        
        Args:
            gmap_name: GMAP name
            segment_x: Segment X coordinate  
            segment_y: Segment Y coordinate
        """
        # Add to pending requests if not already present
        request_info = {
            'type': 'adjacent_levels',
            'gmap_name': gmap_name,
            'segment_x': segment_x,
            'segment_y': segment_y,
            'timestamp': time.time()
        }
        
        # Avoid duplicates
        for existing in self.pending_requests:
            if (existing.get('type') == 'adjacent_levels' and 
                existing.get('segment_x') == segment_x and 
                existing.get('segment_y') == segment_y):
                self.logger.debug(f"Adjacent level request already pending for segment ({segment_x},{segment_y})")
                return
        
        self.pending_requests.append(request_info)
        self.logger.debug(f"Scheduled delayed adjacent level request for segment ({segment_x},{segment_y})")
    
    def _process_pending_requests(self):
        """Process any pending requests that were waiting for GMAP structure"""
        if not self.pending_requests:
            return
        
        if not self._is_gmap_structure_available():
            self.logger.debug("GMAP structure still not available - keeping requests pending")
            return
        
        processed_count = 0
        remaining_requests = []
        
        for request in self.pending_requests:
            try:
                if request['type'] == 'adjacent_levels':
                    self.logger.info(f"🔄 Processing delayed adjacent level request for segment ({request['segment_x']},{request['segment_y']})")
                    self._request_adjacent_levels(request['gmap_name'], request['segment_x'], request['segment_y'])
                    processed_count += 1
                elif request['type'] == 'comprehensive_download':
                    self.logger.info(f"🔄 Processing delayed comprehensive download request")
                    self.request_all_gmap_levels(request['gmap_name'])
                    processed_count += 1
                else:
                    # Unknown request type - keep for later
                    remaining_requests.append(request)
                    
            except Exception as e:
                self.logger.error(f"Error processing pending request: {e}")
                # Keep failed request for retry
                remaining_requests.append(request)
        
        # Update pending requests list
        self.pending_requests = remaining_requests
        
        if processed_count > 0:
            self.logger.info(f"✅ Processed {processed_count} pending GMAP requests")
    
    def _request_gmap_file(self, gmap_name: str):
        """Request GMAP file from server automatically
        
        Args:
            gmap_name: Name of GMAP file to request
        """
        if not self.client:
            self.logger.warning(f"Cannot request GMAP file {gmap_name} - no client reference")
            return
        
        # Avoid duplicate requests
        if gmap_name in self.requested_files:
            self.logger.debug(f"GMAP file {gmap_name} already requested")
            return
        
        try:
            self.logger.info(f"🚀 Automatically requesting GMAP file: {gmap_name}")
            
            # Check if client is authenticated before requesting
            if not self._is_client_authenticated():
                self.logger.info("⏳ Client not yet authenticated - delaying GMAP file request")
                # Schedule delayed request with proper authentication checking
                import threading
                def delayed_request():
                    # Wait up to 5 seconds for authentication, checking every 0.5 seconds
                    for attempt in range(10):  # 10 attempts * 0.5s = 5 seconds max
                        time.sleep(0.5)
                        if self._is_client_authenticated():
                            self.logger.info(f"✅ Client authenticated after {(attempt + 1) * 0.5:.1f}s - requesting GMAP file")
                            self._request_gmap_file_immediate(gmap_name)
                            return
                    
                    self.logger.warning(f"⚠️ Client still not authenticated after 5 seconds - skipping {gmap_name}")
                
                thread = threading.Thread(target=delayed_request, daemon=True)
                thread.start()
                return
            
            # Client is authenticated - request immediately
            self._request_gmap_file_immediate(gmap_name)
                
        except Exception as e:
            self.logger.error(f"Failed to request GMAP file {gmap_name}: {e}")
    
    def _request_gmap_file_immediate(self, gmap_name: str):
        """Request GMAP file immediately (assumes client is authenticated)
        
        Args:
            gmap_name: Name of GMAP file to request
        """
        if gmap_name in self.requested_files:
            return
        
        # Check if we've failed too many times
        if self.failed_requests.get(gmap_name, 0) >= self.max_retry_attempts:
            self.logger.warning(f"⚠️ Skipping {gmap_name} - exceeded max retry attempts ({self.max_retry_attempts})")
            return
        
        if hasattr(self.client, 'request_file'):
            success = self.client.request_file(gmap_name)
            if success:
                self.requested_files.add(gmap_name)
                # Reset failure count on success
                if gmap_name in self.failed_requests:
                    del self.failed_requests[gmap_name]
                self.logger.info(f"✅ GMAP file request sent: {gmap_name}")
            else:
                # Track failure and potentially retry later
                self.failed_requests[gmap_name] = self.failed_requests.get(gmap_name, 0) + 1
                retry_count = self.failed_requests[gmap_name]
                self.logger.warning(f"⚠️ Failed to request GMAP file: {gmap_name} (attempt {retry_count}/{self.max_retry_attempts})")
        else:
            self.logger.warning("Client does not have request_file method")
    
    def _request_adjacent_levels(self, gmap_name: str, segment_x: int, segment_y: int):
        """Request adjacent levels around current position
        
        Args:
            gmap_name: Current GMAP name
            segment_x: Current segment X
            segment_y: Current segment Y
        """
        if not self.client or not self.current_gmap:
            self.logger.debug("Cannot request adjacent levels - no client or GMAP data")
            return
        
        # Get adjacent levels from current GMAP data
        adjacent_levels = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue  # Skip current segment
                
                adj_x = segment_x + dx
                adj_y = segment_y + dy
                level_name = self.get_level_at_segment(adj_x, adj_y)
                
                if level_name:
                    adjacent_levels.append(level_name)
        
        # Request each adjacent level
        requested_count = 0
        for level_name in adjacent_levels:
            if self._request_level_file(level_name):
                requested_count += 1
        
        if adjacent_levels:
            self.logger.info(f"🗺️ Requested {requested_count}/{len(adjacent_levels)} adjacent levels for segment ({segment_x}, {segment_y})")
    
    def request_all_gmap_levels(self, gmap_name: str = None) -> int:
        """Request ALL levels in the current GMAP structure for comprehensive caching
        
        Args:
            gmap_name: Optional GMAP name override
            
        Returns:
            Number of levels requested
        """
        if not self.client:
            self.logger.warning("Cannot request GMAP levels - no client available")
            return 0
        
        # Wait for GMAP structure to be available if not ready
        if not self.current_gmap:
            target_gmap = gmap_name or "chicken.gmap"  # Default assumption
            self.logger.info(f"⏳ Waiting for GMAP structure to be available: {target_gmap}")
            
            # Try to load from cache or request GMAP file
            self._request_gmap_file(target_gmap)
            
            # Wait up to 10 seconds for GMAP structure
            for attempt in range(20):  # 20 attempts * 0.5s = 10 seconds
                time.sleep(0.5)
                if self.check_and_parse_downloaded_gmap_file(target_gmap):
                    self.logger.info(f"✅ GMAP structure loaded: {target_gmap}")
                    break
            else:
                self.logger.warning(f"⚠️ GMAP structure not available after 10 seconds: {target_gmap}")
                return 0
        
        if not self.current_gmap:
            self.logger.error("❌ No GMAP structure available for comprehensive download")
            return 0
        
        # Get all unique level names from GMAP structure
        all_levels = list(self.current_gmap.level_names.keys())
        self.logger.info(f"🚀 Starting comprehensive GMAP download: {len(all_levels)} levels")
        
        # Request all levels
        requested_count = 0
        already_requested = 0
        failed_count = 0
        
        for level_name in all_levels:
            if level_name in self.requested_files:
                already_requested += 1
                continue
                
            if self._request_level_file(level_name):
                requested_count += 1
            else:
                failed_count += 1
        
        self.logger.info(f"📊 Comprehensive download summary:")
        self.logger.info(f"   Total levels: {len(all_levels)}")
        self.logger.info(f"   Newly requested: {requested_count}")
        self.logger.info(f"   Already requested: {already_requested}")
        self.logger.info(f"   Failed requests: {failed_count}")
        
        return requested_count
    
    def _request_level_file(self, level_name: str) -> bool:
        """Request a single level file with error handling and retry logic
        
        Args:
            level_name: Name of level file to request
            
        Returns:
            True if request was sent successfully
        """
        if not self.client or not level_name:
            return False
        
        # Skip if already requested successfully
        if level_name in self.requested_files:
            return True
        
        # Check failure count - skip if exceeded max retries
        if self.failed_requests.get(level_name, 0) >= self.max_retry_attempts:
            self.logger.debug(f"⚠️ Skipping {level_name} - exceeded max retry attempts")
            return False
        
        # Ensure client is authenticated before requesting
        if not self._is_client_authenticated():
            self.logger.debug(f"⏳ Client not authenticated - deferring request for {level_name}")
            return False
        
        try:
            if hasattr(self.client, 'request_file'):
                success = self.client.request_file(level_name)
                if success:
                    self.requested_files.add(level_name)
                    # Reset failure count on success
                    if level_name in self.failed_requests:
                        del self.failed_requests[level_name]
                    # Update statistics
                    self._update_download_stats(level_name, True)
                    self.logger.debug(f"📁 Requested level: {level_name}")
                    return True
                else:
                    # Track failure
                    self.failed_requests[level_name] = self.failed_requests.get(level_name, 0) + 1
                    retry_count = self.failed_requests[level_name]
                    # Update statistics
                    self._update_download_stats(level_name, False)
                    self.logger.debug(f"⚠️ Failed to request {level_name} (attempt {retry_count}/{self.max_retry_attempts})")
                    return False
            else:
                self.logger.warning("Client does not have request_file method")
                self._update_download_stats(level_name, False)
                return False
                
        except Exception as e:
            # Track failure
            self.failed_requests[level_name] = self.failed_requests.get(level_name, 0) + 1
            retry_count = self.failed_requests[level_name]
            # Update statistics
            self._update_download_stats(level_name, False)
            self.logger.debug(f"Exception requesting {level_name}: {e} (attempt {retry_count})")
            return False
    
    def _is_client_authenticated(self) -> bool:
        """Check if client is fully authenticated and can request files
        
        Returns:
            True if client is authenticated and ready for file transfers
        """
        if not self.client:
            return False
        
        # Check multiple authentication indicators
        auth_checks = []
        
        # Check 1: Client authenticated flag
        client_auth = getattr(self.client, 'authenticated', False)
        auth_checks.append(('client.authenticated', client_auth))
        
        # Check 2: Client is_authenticated method
        if hasattr(self.client, 'is_authenticated') and callable(self.client.is_authenticated):
            method_auth = self.client.is_authenticated()
            auth_checks.append(('client.is_authenticated()', method_auth))
        
        # Check 3: Session manager authentication
        if hasattr(self.client, 'session_manager'):
            session_manager = self.client.session_manager
            if hasattr(session_manager, 'is_authenticated') and callable(session_manager.is_authenticated):
                session_auth = session_manager.is_authenticated()
                auth_checks.append(('session_manager.is_authenticated()', session_auth))
        
        # Check 4: Client has file request capability
        has_request_method = hasattr(self.client, 'request_file') and callable(self.client.request_file)
        auth_checks.append(('client.request_file available', has_request_method))
        
        # All checks must pass
        is_authenticated = all(result for name, result in auth_checks)
        
        if not is_authenticated:
            # Log authentication status for debugging (always show for debugging)
            self.logger.warning(f"🔍 File request authentication failed:")
            for name, result in auth_checks:
                self.logger.warning(f"   {name}: {'✅' if result else '❌'}")
        
        return is_authenticated
    
    def check_and_parse_downloaded_gmap_file(self, gmap_name: str) -> bool:
        """Check if GMAP file has been downloaded and parse it
        
        Args:
            gmap_name: Name of GMAP file to check and parse
            
        Returns:
            True if file was found and parsed successfully
        """
        if not self.client:
            return False
        
        try:
            # Check if we already have parsed data
            if self.current_gmap and self.current_gmap.name == gmap_name:
                return True
            
            # Try to get GMAP content from various sources
            gmap_content = None
            
            # Method 1: Check cache manager
            if hasattr(self.client, 'cache_manager'):
                cache_manager = self.client.cache_manager
                if hasattr(cache_manager, 'get_file'):
                    try:
                        gmap_content = cache_manager.get_file(gmap_name)
                        if gmap_content:
                            self.logger.info(f"📁 Found GMAP file in cache: {gmap_name}")
                    except Exception as e:
                        self.logger.debug(f"Could not get GMAP from cache manager: {e}")
            
            # Method 2: Check level manager (files sometimes stored there)
            if not gmap_content and hasattr(self.client, 'level_manager'):
                level_manager = self.client.level_manager
                if hasattr(level_manager, 'levels') and gmap_name in level_manager.levels:
                    try:
                        level_obj = level_manager.levels[gmap_name]
                        if hasattr(level_obj, 'content'):
                            gmap_content = level_obj.content
                        elif hasattr(level_obj, 'data'):
                            gmap_content = level_obj.data
                        
                        if gmap_content:
                            self.logger.info(f"📁 Found GMAP file in level manager: {gmap_name}")
                    except Exception as e:
                        self.logger.debug(f"Could not get GMAP from level manager: {e}")
            
            # Parse GMAP content if found
            if gmap_content:
                # Convert bytes to string if needed
                if isinstance(gmap_content, bytes):
                    gmap_content = gmap_content.decode('utf-8', errors='ignore')
                
                # Parse the GMAP structure
                gmap_data = self.parse_gmap_content(gmap_content, gmap_name)
                if gmap_data:
                    # Load the parsed GMAP data
                    self.current_gmap = gmap_data
                    self.enabled = True
                    self.logger.info(f"🗺️ GMAP structure loaded: {gmap_name} → {len(gmap_data.levels)} levels")
                    return True
            
            self.logger.debug(f"GMAP file {gmap_name} not found or not parseable yet")
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking/parsing GMAP file {gmap_name}: {e}")
            return False