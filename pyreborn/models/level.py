"""
Level model for tracking level state

UNIFIED FORMAT: All levels store board data as List[int] of exactly 4096 tile IDs,
regardless of whether data came from PLO_BOARDPACKET or downloaded files.
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LevelLink:
    """Represents a link from one level to another"""
    x: int
    y: int
    width: int
    height: int
    destination: str
    dest_x: float
    dest_y: float
    

@dataclass  
class Sign:
    """Represents a sign in a level"""
    x: int
    y: int
    text: str
    

@dataclass
class Chest:
    """Represents a chest in a level"""
    x: int
    y: int
    item: str
    signIndex: int


@dataclass
class NPC:
    """Represents an NPC in a level"""
    id: int
    x: float
    y: float
    sprite: int
    script: str = ""

class Level:
    """Represents a level in the game"""
    
    def __init__(self, name: str):
        self.name = name
        self.width = 64  # Always 64x64 for standardization
        self.height = 64  # Always 64x64 for standardization
        
        # UNIFIED BOARD DATA - single source of truth
        self.board_tiles: List[int] = [0] * 4096  # Always exactly 4096 tile IDs
        
        # Additional layers (optional)
        self.layers = {}  # Additional layers if needed
        
        # NPCs in level
        self.npcs = {}  # npc_id -> NPC object
        
        # Links to other levels
        self.links = []  # List of level links
        
        # Signs in level
        self.signs = []  # List of signs
        
        # Items/chests
        self.chests = []  # List of chests
        self.items = []  # List of items
        
        # Players currently in level
        self.players = {}  # player_id -> Player object
        
        # Baddies
        self.baddies = {}  # baddy_id -> Baddy object
        
        # Active objects
        self.bombs = []  # Active bombs
        self.arrows = []  # Active arrows
        self.horses = []  # Active horses
        
        # Level properties
        self.mod_time = 0  # Last modification time
        
        # Cached 2D tiles array for compatibility
        self._tiles_2d_cache = None
        self._tiles_2d_dirty = True
        
    def get_tile(self, x: int, y: int, layer: int = 0) -> int:
        """Get tile at position using unified format"""
        if layer == 0:
            if 0 <= x < 64 and 0 <= y < 64:
                idx = y * 64 + x
                return self.board_tiles[idx]
        elif layer in self.layers:
            layer_data = self.layers[layer]
            if 0 <= x < 64 and 0 <= y < 64:
                return layer_data[y][x]
        return 0
    
    def set_tile(self, x: int, y: int, tile: int, layer: int = 0):
        """Set tile at position using unified format"""
        if layer == 0:
            if 0 <= x < 64 and 0 <= y < 64:
                idx = y * 64 + x
                self.board_tiles[idx] = tile
                self._tiles_2d_dirty = True  # Mark cache as dirty
        else:
            if layer not in self.layers:
                self.layers[layer] = [[0] * 64 for _ in range(64)]
            if 0 <= x < 64 and 0 <= y < 64:
                self.layers[layer][y][x] = tile
    
    @property
    def tiles(self):
        """Get tiles as 2D array [y][x] for compatibility with renderers"""
        if self._tiles_2d_dirty or self._tiles_2d_cache is None:
            # Convert flat array to 2D array
            self._tiles_2d_cache = []
            for y in range(64):
                row = []
                for x in range(64):
                    idx = y * 64 + x
                    row.append(self.board_tiles[idx] if idx < len(self.board_tiles) else 0)
                self._tiles_2d_cache.append(row)
            self._tiles_2d_dirty = False
        return self._tiles_2d_cache
    
    def add_player(self, player):
        """Add player to level"""
        self.players[player.id] = player
        
    def remove_player(self, player_id: int):
        """Remove player from level"""
        if player_id in self.players:
            del self.players[player_id]
    
    def add_link(self, link):
        """Add a level link"""
        self.links.append(link)
    
    def add_sign(self, sign):
        """Add a sign to the level"""
        self.signs.append(sign)
    
    def add_chest(self, chest):
        """Add a chest to the level"""
        self.chests.append(chest)
    
    def add_npc(self, npc):
        """Add an NPC to the level"""
        self.npcs[npc.id] = npc
    
    def set_board_tiles(self, tiles: List[int]):
        """Set level board data using unified format
        
        Args:
            tiles: List of exactly 4096 tile IDs (processed by LevelDataProcessor)
        """
        if not isinstance(tiles, list) or len(tiles) != 4096:
            logger.error(f"Invalid board tiles for {self.name}: expected List[int] of length 4096, "
                        f"got {type(tiles)} of length {len(tiles) if hasattr(tiles, '__len__') else 'unknown'}")
            self.board_tiles = [0] * 4096
            return
            
        # Validate tile IDs are integers in valid range
        valid_tiles = []
        for i, tile in enumerate(tiles):
            if isinstance(tile, int) and 0 <= tile <= 65535:
                valid_tiles.append(tile)
            else:
                logger.warning(f"Invalid tile at index {i} for {self.name}: {tile}, using 0")
                valid_tiles.append(0)
                
        self.board_tiles = valid_tiles
        self._tiles_2d_dirty = True  # Mark cache as dirty after updating board
        logger.debug(f"Board tiles set for {self.name}: {len(valid_tiles)} tiles, "
                    f"{sum(1 for t in valid_tiles if t > 0)} non-zero")
    
    def get_board_tiles(self) -> List[int]:
        """Get level board data as unified format
        
        Returns:
            List of exactly 4096 tile IDs
        """
        return self.board_tiles.copy()
    
    def get_tile_id(self, x: int, y: int) -> int:
        """Get tile ID at position (unified format)"""
        return self.get_tile(x, y, 0)
    
    def get_board_tiles_array(self) -> List[int]:
        """Get the full 64x64 board as a flat array of tile IDs"""
        return self.board_tiles[:]
    
    def get_board_tiles_2d(self) -> List[List[int]]:
        """Get the 64x64 board as a 2D array of tile IDs"""
        board_2d = []
        for y in range(64):
            row = []
            for x in range(64):
                idx = y * 64 + x
                row.append(self.board_tiles[idx])
            board_2d.append(row)
        return board_2d
    
    @property
    def tiles(self):
        """Compatibility property that returns 2D array of tiles"""
        return self.get_board_tiles_2d()
    
    @tiles.setter
    def tiles(self, value):
        """Compatibility setter that accepts 2D array and converts to flat array"""
        if isinstance(value, list) and len(value) == 64:
            # Convert 2D array to flat array
            flat_tiles = []
            for row in value:
                if isinstance(row, list) and len(row) == 64:
                    flat_tiles.extend(row)
                else:
                    # Invalid row, fill with zeros
                    flat_tiles.extend([0] * 64)
            self.set_board_tiles(flat_tiles)
        else:
            logger.error(f"Invalid tiles format for {self.name}: expected 64x64 2D array")
    
    @staticmethod
    def tile_to_tileset_coords(tile_id: int) -> Tuple[int, int, int, int]:
        """
        Convert tile ID to tileset coordinates using server algorithm.
        Returns: (tx, ty, px, py) where tx,ty are tile coords and px,py are pixel coords
        """
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        px = tx * 16
        py = ty * 16
        return tx, ty, px, py
    
    def get_tile_string(self, x: int, y: int) -> str:
        """Get tile string representation (AA, AB, etc.) at position"""
        tile_id = self.get_tile(x, y, 0)
        return self.tile_id_to_string(tile_id)
    
    @staticmethod
    def tile_id_to_string(tile_id: int) -> str:
        """Convert tile ID to string representation"""
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        if 0 <= tile_id < 4096:
            first_char = base64_chars[tile_id // 64]
            second_char = base64_chars[tile_id % 64]
            return first_char + second_char
        return "??"
    
    @staticmethod
    def string_to_tile_id(tile_str: str) -> int:
        """Convert tile string to ID"""
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        if len(tile_str) == 2:
            first_idx = base64_chars.find(tile_str[0])
            second_idx = base64_chars.find(tile_str[1])
            if first_idx >= 0 and second_idx >= 0:
                return first_idx * 64 + second_idx
        return 0
    
    def get_tile_tileset_position(self, x: int, y: int) -> Tuple[int, int]:
        """Get tileset position (in tiles) for the tile at level position"""
        tile_id = self.get_tile(x, y, 0)
        return self.tile_id_to_tileset_position(tile_id)
    
    @staticmethod
    def tile_id_to_tileset_position(tile_id: int) -> Tuple[int, int]:
        """Convert server tile ID to tileset position using server mapping
        
        Uses the mapping generated from alltiles.nw to convert server tile IDs
        to their correct positions in the tileset (128x32 tiles).
        """
        try:
            from ..server_tile_mapping import get_tileset_position
            return get_tileset_position(tile_id)
        except ImportError:
            # Fallback if mapping not available
            return (0, 0)
    
    @staticmethod
    def tileset_position_to_tile_id(tileset_x: int, tileset_y: int) -> int:
        """Convert tileset position to server tile ID"""
        try:
            from ..server_tile_mapping import get_server_tile_id
            return get_server_tile_id(tileset_x, tileset_y)
        except ImportError:
            # Fallback
            return 0
    
    def get_tile_pixels(self, x: int, y: int, tile_size: int = 16) -> Tuple[int, int]:
        """Get pixel position in tileset for tile at level position"""
        tileset_x, tileset_y = self.get_tile_tileset_position(x, y)
        return (tileset_x * tile_size, tileset_y * tile_size)
    
    
    
    def __repr__(self):
        return f"Level(name='{self.name}', size={self.width}x{self.height}, players={len(self.players)}, npcs={len(self.npcs)})"


class Baddy:
    """Represents a baddy (enemy) in a level"""
    
    def __init__(self, baddy_id: int, x: float, y: float, baddy_type: int):
        self.id = baddy_id
        self.x = x
        self.y = y
        self.type = baddy_type
        self.health = 1
        self.mode = 0  # AI mode
        self.direction = 2  # Facing direction