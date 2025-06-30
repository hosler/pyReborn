"""
Level model for tracking level state
"""

from typing import List, Dict, Optional, Tuple
import struct

class Level:
    """Represents a level in the game"""
    
    def __init__(self, name: str):
        self.name = name
        self.width = 64  # Default width in tiles
        self.height = 64  # Default height in tiles
        
        # Level data
        self.tiles = []  # 2D array of tile indices
        self.layers = {}  # Additional layers
        self.board_data = None  # Raw board data from server
        
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
        
    def get_tile(self, x: int, y: int, layer: int = 0) -> int:
        """Get tile at position"""
        if layer == 0:
            if 0 <= x < self.width and 0 <= y < self.height:
                return self.tiles[y][x]
        elif layer in self.layers:
            layer_data = self.layers[layer]
            if 0 <= x < self.width and 0 <= y < self.height:
                return layer_data[y][x]
        return 0
    
    def set_tile(self, x: int, y: int, tile: int, layer: int = 0):
        """Set tile at position"""
        if layer == 0:
            if 0 <= x < self.width and 0 <= y < self.height:
                self.tiles[y][x] = tile
        else:
            if layer not in self.layers:
                self.layers[layer] = [[0] * self.width for _ in range(self.height)]
            if 0 <= x < self.width and 0 <= y < self.height:
                self.layers[layer][y][x] = tile
    
    def add_player(self, player):
        """Add player to level"""
        self.players[player.id] = player
        
    def remove_player(self, player_id: int):
        """Remove player from level"""
        if player_id in self.players:
            del self.players[player_id]
    
    def set_board_data(self, board_data: bytes):
        """Set board data from server and parse tiles"""
        self.board_data = board_data
        
        # Parse board data into 2D tile array
        self.tiles = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                idx = y * self.width + x
                if idx * 2 + 1 < len(board_data):
                    tile_id = struct.unpack('<H', board_data[idx*2:idx*2+2])[0]
                    row.append(tile_id)
                else:
                    row.append(0)
            self.tiles.append(row)
    
    def get_tile_id(self, x: int, y: int) -> int:
        """Get raw tile ID at position"""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.tiles[y][x]
        return 0
    
    def get_tile_string(self, x: int, y: int) -> str:
        """Get tile string representation (AA, AB, etc.) at position"""
        tile_id = self.get_tile_id(x, y)
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
        tile_id = self.get_tile_id(x, y)
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


class LevelLink:
    """Represents a link between levels"""
    
    def __init__(self, x: int, y: int, width: int, height: int, 
                 dest_level: str, dest_x: float, dest_y: float):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.dest_level = dest_level
        self.dest_x = dest_x
        self.dest_y = dest_y
    
    def contains(self, x: float, y: float) -> bool:
        """Check if position is within link area"""
        return (self.x <= x < self.x + self.width and 
                self.y <= y < self.y + self.height)


class Sign:
    """Represents a sign in a level"""
    
    def __init__(self, x: int, y: int, text: str):
        self.x = x
        self.y = y
        self.text = text


class Chest:
    """Represents a chest in a level"""
    
    def __init__(self, x: int, y: int, item: int, sign_text: str = ""):
        self.x = x
        self.y = y
        self.item = item
        self.sign_text = sign_text
        self.opened = False


class NPC:
    """Represents an NPC in a level"""
    
    def __init__(self, npc_id: int, x: float = 0, y: float = 0):
        self.id = npc_id
        self.x = x
        self.y = y
        self.image = ""
        self.script = ""
        self.attributes = {}
        self.visible = True
        

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