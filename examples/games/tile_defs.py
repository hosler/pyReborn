#!/usr/bin/env python3
"""
Tile Definitions Parser - Parses tiledefs.txt for tile collision and properties
"""

import os
import re
from typing import Dict, Set

class TileDefs:
    """Manages tile type definitions for collision and special properties"""
    
    # Tile type constants
    NORMAL = 0
    HURT_UNDERGROUND = 2
    CHAIR = 3
    BED_UPPER = 4
    BED_LOWER = 5
    SWAMP = 6
    LAVA_SWAMP = 7
    SHALLOW_WATER = 8
    WATER = 11
    LAVA = 12
    THROW_THROUGH = 20
    JUMPING = 21
    BLOCKING = 22
    
    # Categories for easier checking
    BLOCKING_TILES = {BLOCKING, BED_UPPER, BED_LOWER, THROW_THROUGH}  # Throw-through tiles are blocking
    WATER_TILES = {WATER, SHALLOW_WATER}
    DAMAGE_TILES = {LAVA, LAVA_SWAMP, HURT_UNDERGROUND}
    SPECIAL_TILES = {CHAIR, SWAMP, THROW_THROUGH, JUMPING}
    SITTABLE_TILES = {CHAIR}  # Can sit on these
    BUSH_TILES = {2, 3, 18, 19}  # Bush tiles that can be picked up
    
    def __init__(self, tiledefs_path: str = None):
        """Initialize tile definitions
        
        Args:
            tiledefs_path: Path to tiledefs.txt file
        """
        self.type0_tiles: Dict[int, int] = {}
        self.type1_tiles: Dict[int, int] = {}
        
        if tiledefs_path and os.path.exists(tiledefs_path):
            self.load_from_file(tiledefs_path)
        else:
            # Try to find it relative to this file
            default_path = os.path.join(os.path.dirname(__file__), "tiledefs.txt")
            if os.path.exists(default_path):
                self.load_from_file(default_path)
    
    def load_from_file(self, filepath: str):
        """Load tile definitions from tiledefs.txt file"""
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Parse TYPE0TILES
        type0_match = re.search(r'var TYPE0TILES = \{([^}]+)\}', content, re.DOTALL)
        if type0_match:
            self._parse_tile_dict(type0_match.group(1), self.type0_tiles)
        
        # Parse TYPE1TILES  
        type1_match = re.search(r'var TYPE1TILES = \{([^}]+)\}', content, re.DOTALL)
        if type1_match:
            self._parse_tile_dict(type1_match.group(1), self.type1_tiles)
            
        print(f"Loaded {len(self.type0_tiles)} TYPE0 tiles and {len(self.type1_tiles)} TYPE1 tiles")
    
    def _parse_tile_dict(self, dict_content: str, target_dict: Dict[int, int]):
        """Parse a tile dictionary from string content"""
        # Remove whitespace and split by commas
        entries = dict_content.strip().split(',')
        
        for entry in entries:
            entry = entry.strip()
            if ':' in entry:
                try:
                    tile_id, tile_type = entry.split(':')
                    target_dict[int(tile_id.strip())] = int(tile_type.strip())
                except ValueError:
                    continue
    
    def get_tile_type(self, tile_id: int, tileset_type: int = 0) -> int:
        """Get the type of a tile by its ID
        
        Args:
            tile_id: The tile ID to check
            tileset_type: 0 for TYPE0TILES, 1 for TYPE1TILES
            
        Returns:
            The tile type (0-22), defaults to NORMAL (0) if not found
        """
        if tileset_type == 0:
            return self.type0_tiles.get(tile_id, self.NORMAL)
        else:
            return self.type1_tiles.get(tile_id, self.NORMAL)
    
    def is_blocking(self, tile_id: int, tileset_type: int = 0) -> bool:
        """Check if a tile blocks movement"""
        # Bush tiles ARE blocking until picked up
        if tile_id in self.BUSH_TILES:
            return True
        tile_type = self.get_tile_type(tile_id, tileset_type)
        return tile_type in self.BLOCKING_TILES
    
    def is_water(self, tile_id: int, tileset_type: int = 0) -> bool:
        """Check if a tile is water"""
        tile_type = self.get_tile_type(tile_id, tileset_type)
        return tile_type in self.WATER_TILES
    
    def is_damaging(self, tile_id: int, tileset_type: int = 0) -> bool:
        """Check if a tile causes damage"""
        tile_type = self.get_tile_type(tile_id, tileset_type)
        return tile_type in self.DAMAGE_TILES
    
    def is_bush(self, tile_id: int) -> bool:
        """Check if a tile is a bush that can be picked up"""
        return tile_id in self.BUSH_TILES
    
    def get_tile_name(self, tile_type: int) -> str:
        """Get human-readable name for a tile type"""
        names = {
            0: "Normal",
            2: "Hurt Underground",
            3: "Chair", 
            4: "Bed Upper",
            5: "Bed Lower",
            6: "Swamp",
            7: "Lava Swamp",
            8: "Shallow Water",
            11: "Water",
            12: "Lava",
            20: "Throw-through",
            21: "Jumping",
            22: "Blocking"
        }
        return names.get(tile_type, f"Unknown ({tile_type})")
    
    def get_blocking_tiles(self, tileset_type: int = 0) -> Set[int]:
        """Get all blocking tile IDs for a tileset"""
        tiles = self.type0_tiles if tileset_type == 0 else self.type1_tiles
        return {tile_id for tile_id, tile_type in tiles.items() 
                if tile_type in self.BLOCKING_TILES}
    
    def debug_tile_at_position(self, tile_id: int, tileset_type: int = 0):
        """Print debug info about a tile"""
        tile_type = self.get_tile_type(tile_id, tileset_type)
        print(f"Tile {tile_id}: {self.get_tile_name(tile_type)} (type {tile_type})")
        print(f"  Blocking: {self.is_blocking(tile_id, tileset_type)}")
        print(f"  Water: {self.is_water(tile_id, tileset_type)}")
        print(f"  Damaging: {self.is_damaging(tile_id, tileset_type)}")