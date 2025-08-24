"""
Tile Type System
================

Defines tile types and loads tile type definitions from binary data.
Based on Preagonal C# implementation.
"""

import os
import logging
from enum import IntEnum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class TileType(IntEnum):
    """Tile type definitions matching Reborn protocol"""
    NONBLOCK = 0          # Walkable tiles
    HURT_UNDERGROUND = 2  # Damage tiles underground
    CHAIR = 3             # Sittable objects
    BED_UPPER = 4         # Upper part of bed (blocking)
    BED_LOWER = 5         # Lower part of bed (blocking)
    SWAMP = 6             # Slows movement
    LAVA_SWAMP = 7        # Damage + slow movement
    NEAR_WATER = 8        # Shallow water
    WATER = 11            # Deep water
    LAVA = 12             # Lava (damage)
    THROW_THROUGH = 20    # Can throw items through but blocks walking
    JUMP_STONE = 21       # Jump tiles
    BLOCKING = 22         # Solid walls and obstacles


class TileTypeManager:
    """Manages tile type definitions loaded from binary data"""
    
    def __init__(self, file_path: Optional[str] = None):
        """Initialize tile type manager
        
        Args:
            file_path: Path to tiletypes.dat file (defaults to assets/tiletypes1.dat)
        """
        self.tile_types: Dict[int, TileType] = {}
        self.loaded = False
        
        if file_path is None:
            # Default to tiletypes1.dat in assets directory
            base_dir = os.path.dirname(os.path.dirname(__file__))
            file_path = os.path.join(base_dir, "assets", "tiletypes1.dat")
        
        if os.path.exists(file_path):
            self.load_from_file(file_path)
        else:
            logger.warning(f"Tile types file not found: {file_path}")
            self._use_defaults()
    
    def load_from_file(self, file_path: str) -> bool:
        """Load tile types from binary file
        
        Args:
            file_path: Path to tiletypes.dat file
            
        Returns:
            True if successful
        """
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            
            # Each byte represents the tile type for that tile ID
            for tile_id, tile_type_value in enumerate(data):
                try:
                    self.tile_types[tile_id] = TileType(tile_type_value)
                except ValueError:
                    # Unknown tile type, default to NONBLOCK
                    logger.debug(f"Unknown tile type {tile_type_value} for tile {tile_id}, defaulting to NONBLOCK")
                    self.tile_types[tile_id] = TileType.NONBLOCK
            
            self.loaded = True
            logger.info(f"Loaded {len(self.tile_types)} tile type definitions from {file_path}")
            
            # Log statistics
            stats = self._get_statistics()
            logger.debug(f"Tile type statistics: {stats}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load tile types from {file_path}: {e}")
            self._use_defaults()
            return False
    
    def _use_defaults(self):
        """Use default tile type mappings when file not available"""
        logger.info("Using default tile type mappings")
        
        # Default all tiles to NONBLOCK
        for i in range(4096):
            self.tile_types[i] = TileType.NONBLOCK
        
        # Apply some common blocking ranges (based on typical Reborn tilesets)
        blocking_ranges = [
            (2, 20),      # Stone walls
            (34, 50),     # Trees
            (66, 82),     # Buildings
            (98, 114),    # More walls
            (220, 250),   # Cliffs
            (512, 540),   # Interior walls
            (1024, 1056), # Castle walls
        ]
        
        for start, end in blocking_ranges:
            for tile_id in range(start, min(end + 1, 4096)):
                self.tile_types[tile_id] = TileType.BLOCKING
        
        # Water tiles
        water_ranges = [(20, 34), (170, 185), (900, 920)]
        for start, end in water_ranges:
            for tile_id in range(start, min(end + 1, 4096)):
                self.tile_types[tile_id] = TileType.WATER
    
    def get_tile_type(self, tile_id: int) -> TileType:
        """Get the type of a tile by its ID
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            The tile type
        """
        if tile_id < 0 or tile_id >= len(self.tile_types):
            return TileType.BLOCKING  # Out of bounds = solid
        
        return self.tile_types.get(tile_id, TileType.NONBLOCK)
    
    def is_blocking(self, tile_id: int) -> bool:
        """Check if a tile blocks movement
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile blocks movement
        """
        tile_type = self.get_tile_type(tile_id)
        
        # These tile types block movement
        blocking_types = {
            TileType.BLOCKING,
            TileType.BED_UPPER,
            TileType.BED_LOWER,
            TileType.THROW_THROUGH,  # Can throw through but not walk through
        }
        
        return tile_type in blocking_types
    
    def is_water(self, tile_id: int) -> bool:
        """Check if a tile is water
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile is water
        """
        tile_type = self.get_tile_type(tile_id)
        return tile_type in {TileType.WATER, TileType.NEAR_WATER}
    
    def is_damaging(self, tile_id: int) -> bool:
        """Check if a tile causes damage
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile causes damage
        """
        tile_type = self.get_tile_type(tile_id)
        return tile_type in {TileType.LAVA, TileType.LAVA_SWAMP, TileType.HURT_UNDERGROUND}
    
    def is_slowing(self, tile_id: int) -> bool:
        """Check if a tile slows movement
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile slows movement
        """
        tile_type = self.get_tile_type(tile_id)
        return tile_type in {TileType.SWAMP, TileType.LAVA_SWAMP}
    
    def is_sittable(self, tile_id: int) -> bool:
        """Check if a tile can be sat on
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile is sittable
        """
        return self.get_tile_type(tile_id) == TileType.CHAIR
    
    def is_jumpable(self, tile_id: int) -> bool:
        """Check if a tile is a jump stone
        
        Args:
            tile_id: The tile ID to check
            
        Returns:
            True if tile is jumpable
        """
        return self.get_tile_type(tile_id) == TileType.JUMP_STONE
    
    def _get_statistics(self) -> Dict[str, int]:
        """Get statistics about loaded tile types
        
        Returns:
            Dictionary with counts of each tile type
        """
        stats = {}
        for tile_type in TileType:
            count = sum(1 for t in self.tile_types.values() if t == tile_type)
            if count > 0:
                stats[tile_type.name] = count
        return stats
    
    def debug_tile(self, tile_id: int):
        """Print debug information about a tile
        
        Args:
            tile_id: The tile ID to debug
        """
        tile_type = self.get_tile_type(tile_id)
        logger.debug(f"Tile {tile_id}:")
        logger.debug(f"  Type: {tile_type.name} ({tile_type.value})")
        logger.debug(f"  Blocking: {self.is_blocking(tile_id)}")
        logger.debug(f"  Water: {self.is_water(tile_id)}")
        logger.debug(f"  Damaging: {self.is_damaging(tile_id)}")
        logger.debug(f"  Slowing: {self.is_slowing(tile_id)}")
        logger.debug(f"  Sittable: {self.is_sittable(tile_id)}")
        logger.debug(f"  Jumpable: {self.is_jumpable(tile_id)}")


# Global instance for easy access
_tile_manager: Optional[TileTypeManager] = None


def get_tile_manager() -> TileTypeManager:
    """Get or create the global tile type manager
    
    Returns:
        The tile type manager instance
    """
    global _tile_manager
    if _tile_manager is None:
        _tile_manager = TileTypeManager()
    return _tile_manager