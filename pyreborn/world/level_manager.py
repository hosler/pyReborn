"""
Level Manager - Consolidated level data management

Handles all level-related functionality:
- Level loading and caching
- Level data parsing
- Level entities (signs, chests, NPCs, baddies)
- Level transitions and warping
"""

import logging
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from pathlib import Path

from .level_parser import LevelParser
# Use simple tuple for position instead of complex Position class
Position = tuple  # (x, y)


@dataclass
class LevelEntity:
    """Base class for level entities"""
    x: float
    y: float
    entity_type: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Sign(LevelEntity):
    """Represents a sign in a level"""
    text: str = ""
    
    def __post_init__(self):
        self.entity_type = "sign"


@dataclass
class Chest(LevelEntity):
    """Represents a chest in a level"""
    item: str = ""
    sign_text: str = ""
    
    def __post_init__(self):
        self.entity_type = "chest"


@dataclass 
class NPC(LevelEntity):
    """Represents an NPC in a level"""
    image: str = ""
    script: str = ""
    
    def __post_init__(self):
        self.entity_type = "npc"


@dataclass
class Baddy(LevelEntity):
    """Represents a baddy in a level"""
    verse: int = 0
    power: int = 0
    
    def __post_init__(self):
        self.entity_type = "baddy"


@dataclass
class LevelData:
    """Represents complete level data"""
    name: str
    width: int = 64
    height: int = 64
    tiles: List[List[int]] = field(default_factory=list)
    board: List[str] = field(default_factory=list)
    
    # Entities
    signs: List[Sign] = field(default_factory=list)
    chests: List[Chest] = field(default_factory=list)
    npcs: List[NPC] = field(default_factory=list)
    baddies: List[Baddy] = field(default_factory=list)
    links: List[Any] = field(default_factory=list)  # Level links/warps
    
    # Metadata
    loaded_time: float = field(default_factory=time.time)
    modified_time: Optional[float] = None
    
    def get_all_entities(self) -> List[LevelEntity]:
        """Get all entities in the level"""
        entities = []
        entities.extend(self.signs)
        entities.extend(self.chests)
        entities.extend(self.npcs)
        entities.extend(self.baddies)
        return entities
        
    def get_entities_at(self, x: int, y: int) -> List[LevelEntity]:
        """Get entities at specific coordinates"""
        entities = []
        for entity in self.get_all_entities():
            if int(entity.x) == x and int(entity.y) == y:
                entities.append(entity)
        return entities


class LevelManager:
    """Manages level loading, caching, and data access"""
    
    def __init__(self, cache_size: int = 50):
        self.logger = logging.getLogger(__name__)
        self.cache_size = cache_size
        
        # Level cache
        self.levels: Dict[str, LevelData] = {}
        self._levels = self.levels  # Compatibility alias for tests
        self.access_times: Dict[str, float] = {}
        
        # Current state
        self.current_level: Optional[str] = None
        self.loading_levels: Set[str] = set()
        
        # Parser
        self.parser = LevelParser()
        
    def load_level(self, level_name: str, level_data: Optional[bytes] = None) -> bool:
        """Load a level from data or cache"""
        if level_name in self.loading_levels:
            self.logger.debug(f"Level already loading: {level_name}")
            return False
            
        if level_name in self.levels:
            self.logger.debug(f"Level already cached: {level_name}")
            self.access_times[level_name] = time.time()
            return True
            
        if level_data is None:
            self.logger.warning(f"No level data provided for: {level_name}")
            return False
            
        self.loading_levels.add(level_name)
        
        try:
            # Parse level data
            parsed_data = self.parser.parse_level_data(level_name, level_data)
            if not parsed_data:
                self.logger.error(f"Failed to parse level: {level_name}")
                return False
                
            # Create level data structure
            level = LevelData(name=level_name)
            level.tiles = parsed_data.get('tiles', [])
            level.board = parsed_data.get('board', [])
            level.width = parsed_data.get('width', 64)
            level.height = parsed_data.get('height', 64)
            
            # Parse entities
            self._parse_entities(level, parsed_data)
            
            # Store in cache
            self._add_to_cache(level_name, level)
            
            self.logger.info(f"Level loaded: {level_name} ({level.width}x{level.height})")
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading level {level_name}: {e}")
            return False
        finally:
            self.loading_levels.discard(level_name)
            
    def get_level(self, level_name: str) -> Optional[LevelData]:
        """Get level data from cache"""
        if level_name in self.levels:
            self.access_times[level_name] = time.time()
            return self.levels[level_name]
        return None
        
    def is_level_loaded(self, level_name: str) -> bool:
        """Check if level is loaded in cache"""
        return level_name in self.levels
        
    def set_current_level(self, level_name: str):
        """Set the current level"""
        if self.current_level != level_name:
            # Throttle level change messages
            if not hasattr(self, '_last_level_change') or self._last_level_change != level_name:
                self.logger.info(f"Changed level: {self.current_level} -> {level_name}")
                self._last_level_change = level_name
            else:
                self.logger.debug(f"Changed level: {self.current_level} -> {level_name} (throttled)")
            self.current_level = level_name
            
    def get_current_level(self) -> Optional['Level']:
        """Get current level data as a Level model"""
        level_data = None
        
        if self.current_level:
            # If current_level is a GMAP name, find the actual level
            if self.current_level.endswith('.gmap'):
                # Return the first cached level (usually the player's actual level)
                # In a proper implementation, we'd track the actual level within the GMAP
                if self.levels:
                    # Try to find a non-gmap level
                    for level_name, data in self.levels.items():
                        if not level_name.endswith('.gmap'):
                            level_data = data
                            break
            else:
                level_data = self.get_level(self.current_level)
        
        # Convert LevelData to Level model if found
        if level_data:
            from pyreborn.models.level import Level
            level = Level(level_data.name)
            level.width = level_data.width
            level.height = level_data.height
            level.tiles = level_data.tiles
            level.links = level_data.links
            level.npcs = level_data.npcs
            level.signs = level_data.signs
            level.chests = level_data.chests
            return level
        
        return None
        
    def preload_level(self, level_name: str):
        """Mark a level for preloading"""
        if level_name not in self.levels and level_name not in self.loading_levels:
            self.logger.debug(f"Level marked for preloading: {level_name}")
            # In a real implementation, this would trigger background loading
            
    def unload_level(self, level_name: str):
        """Remove level from cache"""
        if level_name in self.levels:
            del self.levels[level_name]
            del self.access_times[level_name]
            self.logger.debug(f"Level unloaded: {level_name}")
            
    def get_tile_at(self, level_name: str, x: int, y: int) -> Optional[int]:
        """Get tile at specific coordinates"""
        level = self.get_level(level_name)
        if not level or x < 0 or y < 0 or x >= level.width or y >= level.height:
            return None
            
        if y < len(level.tiles) and x < len(level.tiles[y]):
            return level.tiles[y][x]
        return 0
        
    def get_entities_at(self, level_name: str, x: int, y: int) -> List[LevelEntity]:
        """Get entities at specific coordinates"""
        level = self.get_level(level_name)
        if not level:
            return []
        return level.get_entities_at(x, y)
        
    def add_entity(self, level_name: str, entity: LevelEntity):
        """Add entity to level"""
        level = self.get_level(level_name)
        if not level:
            return
            
        if entity.entity_type == "sign":
            level.signs.append(entity)
        elif entity.entity_type == "chest":
            level.chests.append(entity)
        elif entity.entity_type == "npc":
            level.npcs.append(entity)
        elif entity.entity_type == "baddy":
            level.baddies.append(entity)
            
        self.logger.debug(f"Added {entity.entity_type} to {level_name} at ({entity.x}, {entity.y})")
        
    def remove_entity(self, level_name: str, entity: LevelEntity):
        """Remove entity from level"""
        level = self.get_level(level_name)
        if not level:
            return
            
        entity_lists = {
            "sign": level.signs,
            "chest": level.chests, 
            "npc": level.npcs,
            "baddy": level.baddies
        }
        
        entity_list = entity_lists.get(entity.entity_type)
        if entity_list and entity in entity_list:
            entity_list.remove(entity)
            self.logger.debug(f"Removed {entity.entity_type} from {level_name}")
            
    def cache_level(self, level_name: str, level_data: Any):
        """Cache a level (compatibility method)"""
        if hasattr(level_data, 'name'):
            level_data.name = level_name
        if isinstance(level_data, LevelData):
            self._add_to_cache(level_name, level_data)
        else:
            # Convert to LevelData if needed
            level = LevelData(name=level_name)
            if hasattr(level_data, 'width'):
                level.width = level_data.width
            if hasattr(level_data, 'height'):
                level.height = level_data.height
            if hasattr(level_data, 'tiles'):
                level.tiles = level_data.tiles
            self._add_to_cache(level_name, level)
            
    def get_cached_level(self, level_name: str) -> Optional[Any]:
        """Get cached level (compatibility method)"""
        return self.get_level(level_name)
        
    def clear_cache(self):
        """Clear all cached levels except current"""
        levels_to_clear = list(self.levels.keys())
        for level_name in levels_to_clear:
            if level_name != self.current_level:
                self.unload_level(level_name)
                
    # Add adjacent levels support
    @property
    def adjacent_levels(self):
        """Get adjacent levels list"""
        if not hasattr(self, '_adjacent_levels'):
            self._adjacent_levels = []
        return self._adjacent_levels
        
    @adjacent_levels.setter
    def adjacent_levels(self, value):
        """Set adjacent levels list"""
        self._adjacent_levels = value
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            'cached_levels': len(self.levels),
            'cache_size_limit': self.cache_size,
            'loading_levels': list(self.loading_levels),
            'current_level': self.current_level,
            'level_names': list(self.levels.keys())
        }
        
    def cleanup_cache(self):
        """Clean up old levels from cache"""
        if len(self.levels) <= self.cache_size:
            return
            
        # Remove least recently used levels
        sorted_levels = sorted(self.access_times.items(), key=lambda x: x[1])
        to_remove = len(self.levels) - self.cache_size
        
        for level_name, _ in sorted_levels[:to_remove]:
            if level_name != self.current_level:  # Don't remove current level
                self.unload_level(level_name)
                
    def _add_to_cache(self, level_name: str, level_data: LevelData):
        """Add level to cache with cleanup"""
        self.levels[level_name] = level_data
        self.access_times[level_name] = time.time()
        self.cleanup_cache()
    
    def load_levels_from_cache_directory(self, cache_dir_path: str):
        """Load level files from cache directory for GMAP mode
        
        Args:
            cache_dir_path: Path to cache directory containing .nw files
        """
        try:
            import os
            from pathlib import Path
            
            cache_dir = Path(cache_dir_path)
            if not cache_dir.exists():
                self.logger.debug(f"Cache directory not found: {cache_dir}")
                return
            
            # Find all .nw files in cache
            cached_files = [f for f in os.listdir(cache_dir) if f.endswith('.nw')]
            self.logger.info(f"🗺️ Found {len(cached_files)} cached level files for GMAP loading")
            
            loaded_count = 0
            for filename in cached_files:
                level_name = filename  # Keep full filename with .nw extension
                
                # Skip if already loaded
                if level_name in self.levels:
                    continue
                
                # Load level from cache file
                cache_file_path = cache_dir / filename
                if self._load_level_from_file(cache_file_path, level_name):
                    loaded_count += 1
            
            if loaded_count > 0:
                self.logger.info(f"✅ Loaded {loaded_count} additional levels from cache for GMAP mode")
                
        except Exception as e:
            self.logger.error(f"Failed to load levels from cache: {e}")
    
    def _load_level_from_file(self, file_path: Path, level_name: str) -> bool:
        """Load a level from a cached file
        
        Args:
            file_path: Path to cached level file
            level_name: Name to use for the level
            
        Returns:
            True if loaded successfully
        """
        try:
            with open(file_path, 'rb') as f:
                level_data_bytes = f.read()
            
            if len(level_data_bytes) < 8192:  # Level should be at least 8192 bytes (4096 tiles * 2 bytes)
                self.logger.warning(f"Cached level file too small: {file_path} ({len(level_data_bytes)} bytes)")
                return False
            
            # Parse level data from bytes
            level_data = self._parse_cached_level_data(level_data_bytes, level_name)
            if level_data:
                self._add_to_cache(level_name, level_data)
                self.logger.debug(f"📁 Loaded level from cache: {level_name}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to load cached level {file_path}: {e}")
        
        return False
    
    def _parse_cached_level_data(self, data_bytes: bytes, level_name: str):
        """Parse level data from cached bytes using proper GLEVNW01 format parsing
        
        Args:
            data_bytes: Raw level data bytes (GLEVNW01 format)
            level_name: Name of the level
            
        Returns:
            LevelData object or None
        """
        try:
            # Use the existing LevelParser to handle GLEVNW01 format properly
            parsed_data = self.parser.parse(data_bytes)
            
            if not parsed_data:
                self.logger.warning(f"LevelParser returned no data for {level_name}")
                return None
            
            # Create LevelData object from parsed data
            level_data = LevelData(
                name=level_name,
                width=64,
                height=64
            )
            
            # Convert board_data (bytes) to 2D tile array
            board_data = parsed_data.get('board_data', b'')
            if len(board_data) >= 8192:  # 64x64 tiles * 2 bytes per tile
                tiles_2d = []
                for y in range(64):
                    row = []
                    for x in range(64):
                        tile_index = (y * 64 + x) * 2
                        if tile_index + 1 < len(board_data):
                            # Read 16-bit little-endian tile ID
                            tile_value = board_data[tile_index] | (board_data[tile_index + 1] << 8)
                            row.append(tile_value)
                        else:
                            row.append(0)
                    tiles_2d.append(row)
                
                level_data.tiles = tiles_2d
                self.logger.debug(f"📊 Parsed {len(tiles_2d)*64} tiles from GLEVNW01 cached level: {level_name}")
            else:
                self.logger.warning(f"Insufficient board data for {level_name}: {len(board_data)} bytes")
                # Create empty tiles as fallback
                level_data.tiles = [[0 for x in range(64)] for y in range(64)]
            
            # Add parsed entities from LevelParser - fix entity_type requirement
            level_data.signs = [Sign(x=sign.x, y=sign.y, entity_type="sign", text=sign.text) for sign in parsed_data.get('signs', [])]
            level_data.npcs = [NPC(x=npc.x, y=npc.y, entity_type="npc", image=npc.image, script=npc.script) for npc in parsed_data.get('npcs', [])]
            
            # Convert chests dict to Chest objects - fix entity_type requirement
            chest_items = parsed_data.get('chests', {})
            for (x, y), item in chest_items.items():
                chest = Chest(x=x, y=y, entity_type="chest", item=str(item), sign_text="")
                level_data.chests.append(chest)
            
            # Store links for compatibility (even though they're not used in rendering)
            level_data.links = parsed_data.get('links', [])
            
            self.logger.info(f"✅ Successfully parsed GLEVNW01 cached level: {level_name} with {len(level_data.signs)} signs, {len(level_data.npcs)} NPCs, {len(level_data.chests)} chests")
            return level_data
                
        except Exception as e:
            self.logger.error(f"Failed to parse GLEVNW01 cached level data for {level_name}: {e}")
            import traceback
            traceback.print_exc()
        
        return None
        
    def _parse_entities(self, level: LevelData, parsed_data: Dict[str, Any]):
        """Parse entities from level data"""
        # Signs
        for sign_data in parsed_data.get('signs', []):
            sign = Sign(
                x=sign_data.get('x', 0),
                y=sign_data.get('y', 0),
                text=sign_data.get('text', '')
            )
            level.signs.append(sign)
            
        # Chests
        for chest_data in parsed_data.get('chests', []):
            chest = Chest(
                x=chest_data.get('x', 0),
                y=chest_data.get('y', 0),
                item=chest_data.get('item', ''),
                sign_text=chest_data.get('sign', '')
            )
            level.chests.append(chest)
            
        # NPCs
        for npc_data in parsed_data.get('npcs', []):
            npc = NPC(
                x=npc_data.get('x', 0),
                y=npc_data.get('y', 0),
                image=npc_data.get('image', ''),
                script=npc_data.get('script', '')
            )
            level.npcs.append(npc)
            
        # Baddies
        for baddy_data in parsed_data.get('baddies', []):
            baddy = Baddy(
                x=baddy_data.get('x', 0),
                y=baddy_data.get('y', 0),
                verse=baddy_data.get('verse', 0),
                power=baddy_data.get('power', 0)
            )
            level.baddies.append(baddy)