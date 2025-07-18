"""
GMAP Handler - Manages GMAP detection, parsing, and segment tracking
"""

import re
from typing import Optional, Tuple, Dict, Set


class GmapHandler:
    """Handles GMAP file parsing and segment tracking"""
    
    def __init__(self):
        self.current_gmap = None  # Current gmap name
        self.gmap_width = 1
        self.gmap_height = 1
        self.segment_cache = {}  # Cache of parsed segments
        self.requested_segments = set()  # Track which segments we've requested
        self.gmap_data = {}  # Store parsed gmap file data
        
        # Current level name
        self.current_level_name = None
        
        # Level adjacency map: level_name -> {north, south, east, west, northeast, northwest, southeast, southwest}
        self.level_adjacency = {}  # Dict[str, Dict[str, str]]
        
        # Level objects: level_name -> level_object
        self.level_objects = {}  # Dict[str, Level]
        
        # Track which levels have been loaded
        self.loaded_levels = set()  # Set[str]
        
    def is_gmap_level(self, level_name: str) -> bool:
        """Check if a level name indicates a gmap segment or gmap file"""
        # Check for .gmap files OR segment names with hyphens (e.g., zlttp-d8.nw)
        return (level_name.endswith('.gmap') or 
                ('-' in level_name and level_name.count('-') == 1 and level_name.endswith('.nw')))
    
    def parse_segment_name(self, level_name: str) -> Optional[Tuple[str, int, int]]:
        """Parse a segment name like 'world-a0.nw' or 'world_01-02.nw' -> ('world', x, y)"""
        # Try column-letter format first: basename-[a-z][0-9]+.nw
        match = re.match(r'^(.+?)-([a-z])(\d+)\.nw$', level_name)
        if match:
            base_name = match.group(1)
            letter = match.group(2)
            x = ord(letter) - ord('a')  # Convert letter to number (a=0, b=1, etc)
            y = int(match.group(3))
            
            # Note: Using normal letter mapping (a=0, b=1, c=2...) with flipped east/west
            
            return (base_name, x, y)
            
        # Try numbered format: basename_XX-YY.nw
        match = re.match(r'^(.+?)_(\d{2})-(\d{2})\.nw$', level_name)
        if match:
            base_name = match.group(1)
            x = int(match.group(2))
            y = int(match.group(3))
            return (base_name, x, y)
        return None
    
    def enter_gmap(self, gmap_name: str):
        """Handle entering a gmap"""
        new_gmap = gmap_name.replace('.gmap', '')
        
        # Only clear if we're entering a different gmap
        if self.current_gmap != new_gmap:
            print(f"[GMAP] Entered NEW gmap: {new_gmap} (was: {self.current_gmap})")
            self.current_gmap = new_gmap
            
            # Reset tracking
            self.current_level_name = None
            self.requested_segments.clear()
            
            # Clear the maps when entering a new gmap
            self.level_adjacency.clear()
            self.level_objects.clear()
            self.loaded_levels.clear()
        else:
            print(f"[GMAP] Already in gmap: {new_gmap}, not clearing level data")
        
    def parse_gmap_file(self, filename: str, data: bytes):
        """Parse a .gmap file to get dimensions and structure"""
        if not filename.endswith('.gmap'):
            return
            
        try:
            text = data.decode('ascii', errors='ignore').strip()
            lines = text.split('\n')
            
            if lines and lines[0].startswith('GLEVELS'):
                # Format: GLEVELS width height
                parts = lines[0].split()
                if len(parts) >= 3:
                    self.gmap_width = int(parts[1])
                    self.gmap_height = int(parts[2])
                    print(f"[GMAP] Parsed {filename}: {self.gmap_width}x{self.gmap_height} segments")
                    
                    # Store the gmap data
                    base_name = filename.replace('.gmap', '')
                    self.gmap_data[base_name] = {
                        'width': self.gmap_width,
                        'height': self.gmap_height,
                        'segments': []
                    }
                    
                    # Parse segment list if present
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip():
                            self.gmap_data[base_name]['segments'].append(line.strip())
                            
        except Exception as e:
            print(f"[GMAP] Error parsing gmap file {filename}: {e}")
    
    def update_position_from_level(self, level_name: str):
        """Update our gmap position based on level name"""
        # If it's a .gmap file, we're entering the gmap
        if level_name.endswith('.gmap'):
            self.enter_gmap(level_name)
            return
            
        # If it's a segment, parse the coordinates
        segment_info = self.parse_segment_name(level_name)
        if segment_info:
            base_name, x, y = segment_info
            # Set the current gmap if not already set
            if not self.current_gmap:
                self.current_gmap = base_name
                print(f"[GMAP] Set current gmap to {base_name}")
            
            if base_name == self.current_gmap:
                print(f"[GMAP] Now in segment [{x}, {y}] of {self.current_gmap} (level: {level_name})")
            else:
                print(f"[GMAP] Level {level_name} is from different gmap: {base_name} != {self.current_gmap}")
    
    def get_adjacent_segments(self) -> Set[str]:
        """Get list of adjacent level names we should request"""
        if not self.current_level_name:
            return set()
            
        adjacent = set()
        
        # Get all adjacent levels from the adjacency map
        if self.current_level_name in self.level_adjacency:
            for direction, adj_level_name in self.level_adjacency[self.current_level_name].items():
                if adj_level_name and adj_level_name not in self.loaded_levels:
                    adjacent.add(adj_level_name)
                    
        return adjacent
    
    def get_segments_to_request(self) -> Set[str]:
        """Get list of segment filenames we should request"""
        if not self.current_level_name:
            return set()
            
        to_request = set()
        adjacent = self.get_adjacent_segments()
        
        for level_name in adjacent:
            if level_name not in self.requested_segments:
                to_request.add(level_name)
                
        return to_request
    
    def mark_segment_requested(self, level_name: str):
        """Mark a segment as requested"""
        self.requested_segments.add(level_name)
    
    def get_target_level_from_movement(self, old_x: float, old_y: float, 
                                       new_x: float, new_y: float) -> Optional[str]:
        """Get the target level name based on movement crossing boundaries"""
        if not self.current_gmap or not self.current_level_name:
            return None
            
        # Calculate movement delta
        dx = new_x - old_x
        dy = new_y - old_y
        
        # Check if we crossed a level boundary (64x64 tiles per level)
        old_level_x = int(old_x // 64)
        old_level_y = int(old_y // 64)
        new_level_x = int(new_x // 64)
        new_level_y = int(new_y // 64)
        
        # Check if we crossed a boundary
        crossed_x = old_level_x != new_level_x
        crossed_y = old_level_y != new_level_y
        
        print(f"[GMAP BOUNDARY] World pos: ({old_x:.2f},{old_y:.2f}) -> ({new_x:.2f},{new_y:.2f})")
        print(f"                Level coords: [{old_level_x},{old_level_y}] -> [{new_level_x},{new_level_y}]")
        print(f"                crossed_x={crossed_x}, crossed_y={crossed_y}")
        
        if not (crossed_x or crossed_y):
            return None
            
        # Determine direction of movement
        direction = None
        if crossed_x and crossed_y:
            # Diagonal movement - determine primary direction
            if abs(dx) > abs(dy):
                direction = 'east' if dx > 0 else 'west'
            else:
                direction = 'south' if dy > 0 else 'north'
        elif crossed_x:
            direction = 'east' if dx > 0 else 'west'
        elif crossed_y:
            direction = 'south' if dy > 0 else 'north'
        
        if direction:
            target_level = self.get_adjacent_level(self.current_level_name, direction)
            print(f"[GMAP] Movement {direction} from {self.current_level_name} -> {target_level}")
            return target_level
                
        return None
    
    def get_segment_name(self, seg_x: int, seg_y: int) -> str:
        """Build a segment name from gmap name and coordinates
        
        Args:
            seg_x: Segment X coordinate
            seg_y: Segment Y coordinate
            
        Returns:
            Segment name like 'zlttp-d8.nw' using column letter notation
        """
        if not self.current_gmap:
            return ""
            
        # Check bounds - don't generate names for invalid coordinates
        if seg_x < 0 or seg_y < 0:
            return f"{self.current_gmap}-INVALID({seg_x},{seg_y}).nw"
            
        # Convert x coordinate to column letter (0=a, 1=b, etc)
        if seg_x >= 26:  # Beyond 'z'
            return f"{self.current_gmap}-INVALID({seg_x},{seg_y}).nw"
            
        col_letter = chr(ord('a') + seg_x)
        
        # Build segment name in format: mapname-colrow.nw
        return f"{self.current_gmap}-{col_letter}{seg_y}.nw"
    
    def add_level(self, level_name: str, level_obj):
        """Add a level to the adjacency map and object store
        
        Args:
            level_name: Name of the level
            level_obj: Level object
        """
        # Check if level is already added to prevent duplicate processing
        if level_name in self.loaded_levels:
            print(f"[GMAP] Level {level_name} already loaded, skipping duplicate addition")
            return
            
        # Parse the level name to get coordinates
        segment_info = self.parse_segment_name(level_name)
        if segment_info:
            base_name, x, y = segment_info
            print(f"[GMAP STORAGE] Adding level {level_name} at coordinates ({x}, {y})")
            print(f"[GMAP STORAGE]   - Column letter '{chr(ord('a') + x)}' = X coordinate {x}")
            print(f"[GMAP STORAGE]   - Row number {y} = Y coordinate {y}")
        
        self.level_objects[level_name] = level_obj
        self.loaded_levels.add(level_name)
        
        # Initialize adjacency map for this level
        if level_name not in self.level_adjacency:
            self.level_adjacency[level_name] = {}
        
        # Parse coordinates from level name to set up adjacency
        self._setup_adjacency_for_level(level_name)
        
        # Update adjacency for all existing levels to include this new level
        for existing_level in list(self.loaded_levels):
            if existing_level != level_name:
                self._update_adjacency_for_new_level(existing_level, level_name)
        
        print(f"[GMAP] Added level {level_name} to adjacency map")
        print(f"[GMAP] Total levels loaded: {len(self.loaded_levels)}")
        
        # Debug: Show adjacency for the new level
        if level_name in self.level_adjacency:
            adjacent = self.level_adjacency[level_name]
            print(f"[GMAP] {level_name} adjacent levels: {adjacent}")
    
    def _setup_adjacency_for_level(self, level_name: str):
        """Set up adjacency relationships for a level based on its coordinates"""
        segment_info = self.parse_segment_name(level_name)
        if not segment_info:
            return
            
        base_name, x, y = segment_info
        
        # Initialize adjacency entry for this level
        if level_name not in self.level_adjacency:
            self.level_adjacency[level_name] = {}
        
        # Calculate adjacent segment names
        # Note: East/West are flipped because Zelda LTTP map has e8 west of d8 (not east)
        directions = {
            'north': (x, y - 1),     # Y decreases = NORTH
            'south': (x, y + 1),     # Y increases = SOUTH
            'east': (x - 1, y),      # X decreases = EAST (flipped from normal)
            'west': (x + 1, y),      # X increases = WEST (flipped from normal)
            'northeast': (x - 1, y - 1),
            'northwest': (x + 1, y - 1),
            'southeast': (x - 1, y + 1),
            'southwest': (x + 1, y + 1)
        }
        
        for direction, (adj_x, adj_y) in directions.items():
            if adj_x >= 0 and adj_y >= 0:  # Only valid coordinates
                adj_name = self.get_segment_name(adj_x, adj_y)
                if adj_name and not adj_name.startswith(f"{self.current_gmap}-INVALID"):
                    # Set up adjacency relationship regardless of whether level is loaded
                    self.level_adjacency[level_name][direction] = adj_name
                    
                    # Debug output for adjacency setup (only log east/west for now)
                    if direction in ['east', 'west']:
                        print(f"[ADJACENCY] {level_name} ({x},{y}): {direction} -> {adj_name} ({adj_x},{adj_y})")
                    
                    # Set up reverse adjacency if the adjacent level is already loaded
                    if adj_name in self.loaded_levels:
                        if adj_name not in self.level_adjacency:
                            self.level_adjacency[adj_name] = {}
                        reverse_direction = self._get_reverse_direction(direction)
                        self.level_adjacency[adj_name][reverse_direction] = level_name
    
    def _update_adjacency_for_new_level(self, existing_level: str, new_level: str):
        """Update adjacency for an existing level when a new level is added"""
        if existing_level not in self.level_adjacency:
            return
            
        # Parse coordinates for both levels
        existing_info = self.parse_segment_name(existing_level)
        new_info = self.parse_segment_name(new_level)
        
        if not existing_info or not new_info:
            return
            
        existing_base, existing_x, existing_y = existing_info
        new_base, new_x, new_y = new_info
        
        # Only update if they're from the same GMAP
        if existing_base != new_base:
            return
            
        # Calculate direction from existing to new
        dx = new_x - existing_x
        dy = new_y - existing_y
        
        # Check if they're adjacent (distance of 1 in any direction)
        if abs(dx) <= 1 and abs(dy) <= 1 and (dx != 0 or dy != 0):
            # Determine direction - using flipped east/west like in _setup_adjacency_for_level
            direction = None
            if dx == 0 and dy == -1:
                direction = 'north'
            elif dx == 0 and dy == 1:
                direction = 'south'
            elif dx == -1 and dy == 0:
                direction = 'east'  # X decreases = EAST (flipped)
            elif dx == 1 and dy == 0:
                direction = 'west'  # X increases = WEST (flipped)
            elif dx == -1 and dy == -1:
                direction = 'northeast'
            elif dx == 1 and dy == -1:
                direction = 'northwest'
            elif dx == -1 and dy == 1:
                direction = 'southeast'
            elif dx == 1 and dy == 1:
                direction = 'southwest'
                
            if direction:
                # Set up bidirectional adjacency
                self.level_adjacency[existing_level][direction] = new_level
                
                if new_level not in self.level_adjacency:
                    self.level_adjacency[new_level] = {}
                reverse_direction = self._get_reverse_direction(direction)
                self.level_adjacency[new_level][reverse_direction] = existing_level

    def _get_reverse_direction(self, direction: str) -> str:
        """Get the reverse direction"""
        reverse_map = {
            'north': 'south',
            'south': 'north',
            'east': 'west',
            'west': 'east',
            'northeast': 'southwest',
            'southwest': 'northeast',
            'northwest': 'southeast',
            'southeast': 'northwest'
        }
        return reverse_map.get(direction, direction)
    
    def get_adjacent_level(self, level_name: str, direction: str) -> str:
        """Get the adjacent level in a specific direction
        
        Args:
            level_name: Current level name
            direction: Direction to look (north, south, east, west, etc.)
            
        Returns:
            Adjacent level name or None if not found
        """
        return self.level_adjacency.get(level_name, {}).get(direction)
    
    def get_level_object(self, level_name: str):
        """Get level object by name
        
        Args:
            level_name: Name of the level
            
        Returns:
            Level object or None if not found
        """
        return self.level_objects.get(level_name)
    
    def set_current_level(self, level_name: str):
        """Set the current level
        
        Args:
            level_name: Name of the current level
        """
        self.current_level_name = level_name
        print(f"[GMAP] Current level set to: {level_name}")
        
        # Debug: Show adjacent levels
        if level_name in self.level_adjacency:
            adjacent = self.level_adjacency[level_name]
            print(f"[GMAP] Adjacent levels: {adjacent}")
    
    def add_level_to_map(self, level_obj, seg_x: int, seg_y: int):
        """Legacy method - add a level to the adjacency map
        
        Args:
            level_obj: Level object to add
            seg_x: Segment X coordinate (unused in adjacency system)
            seg_y: Segment Y coordinate (unused in adjacency system)
        """
        self.add_level(level_obj.name, level_obj)
        
    def get_level_at_segment(self, seg_x: int, seg_y: int):
        """Get level at specific segment coordinates - legacy method
        
        Args:
            seg_x: Segment X coordinate
            seg_y: Segment Y coordinate
            
        Returns:
            Level object or None if not loaded
        """
        # Convert coordinates to level name
        level_name = self.get_segment_name(seg_x, seg_y)
        return self.level_objects.get(level_name)
        
    def get_current_level(self):
        """Get the level for the current segment
        
        Returns:
            Level object or None if not loaded
        """
        return self.level_objects.get(self.current_level_name)
        
    def update_level_from_name(self, level_name: str, level_obj):
        """Update level map when a level is loaded by name
        
        Args:
            level_name: Name of the level file
            level_obj: Level object
        """
        if not self.current_gmap:
            return
            
        # Parse segment coordinates from level name
        segment_info = self.parse_segment_name(level_name)
        if segment_info:
            base_name, seg_x, seg_y = segment_info
            if base_name == self.current_gmap:
                self.add_level(level_name, level_obj)
                
    def is_segment_loaded(self, level_name: str) -> bool:
        """Check if a segment is loaded
        
        Args:
            level_name: Name of the level
            
        Returns:
            True if segment is loaded
        """
        return level_name in self.loaded_levels
        
    def get_gmap_info(self) -> Dict:
        """Get current gmap information for display"""
        if not self.current_gmap:
            return {}
            
        return {
            'gmap_name': self.current_gmap,
            'gmap_width': self.gmap_width,
            'gmap_height': self.gmap_height,
            'current_level': self.current_level_name,
            'requested_count': len(self.requested_segments),
            'loaded_count': len(self.loaded_levels)
        }
    
    def clear_cache(self):
        """Clear all GMAP caches"""
        print("[GMAP] Clearing segment cache...")
        cache_size = len(self.segment_cache)
        self.segment_cache.clear()
        print(f"[GMAP] Cleared {cache_size} segment cache entries")