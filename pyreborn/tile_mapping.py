"""
Tile mapping utilities for Graal - handles tile IDs, strings, and tileset positions
"""

import os
import re
import struct
from typing import Dict, Optional, Tuple, List


class TileInfo:
    """Information about a single tile"""
    
    def __init__(self, tile_id: str, x: int, y: int, blocking: int = 0):
        self.tile_id = tile_id
        self.x = x  # X position in tileset (for reference)
        self.y = y  # Y position in tileset (for reference) 
        self.blocking = blocking  # 0 = passable, >0 = blocked
    
    def is_blocking(self) -> bool:
        """Check if this tile blocks movement"""
        return self.blocking > 0
    
    def __repr__(self):
        return f"TileInfo(id='{self.tile_id}', blocking={self.blocking})"


class TileMapping:
    """Simple tile mapping for collision detection"""
    
    def __init__(self):
        self.tiles: Dict[str, TileInfo] = {}
    
    def load_mapping(self, mapping_file: str) -> bool:
        """Load tile mapping from the mytext.txt format"""
        if not os.path.exists(mapping_file):
            print(f"❌ Tile mapping file not found: {mapping_file}")
            return False
        
        try:
            with open(mapping_file, 'r') as f:
                content = f.read()
            
            # Parse format: "ID" : [x, y, blocking],
            pattern = r'"([^"]+)"\s*:\s*\[(\d+),\s*(\d+),\s*(\d+)\]'
            matches = re.findall(pattern, content)
            
            for tile_id, x_str, y_str, blocking_str in matches:
                self.tiles[tile_id] = TileInfo(
                    tile_id=tile_id,
                    x=int(x_str),
                    y=int(y_str),
                    blocking=int(blocking_str)
                )
            
            print(f"✅ Loaded {len(self.tiles)} tile mappings")
            return True
            
        except Exception as e:
            print(f"❌ Error loading tile mapping: {e}")
            return False
    
    def is_tile_blocking(self, tile_id: str) -> bool:
        """Check if a tile blocks movement"""
        tile_info = self.tiles.get(tile_id)
        return tile_info.is_blocking() if tile_info else False
    
    def get_tile_info(self, tile_id: str) -> Optional[TileInfo]:
        """Get tile information"""
        return self.tiles.get(tile_id)
    
    def parse_level_tiles(self, board_data: str, level_width: int = 64) -> Tuple[list, int, int]:
        """Parse level board data into 2D tile array
        
        Returns: (tile_array, width, height)
        """
        # Remove whitespace and split into 2-character tile IDs
        clean_data = board_data.replace(' ', '').replace('\n', '')
        tiles = [clean_data[i:i+2] for i in range(0, len(clean_data), 2)]
        
        # Convert to 2D array
        level_height = len(tiles) // level_width
        
        tile_array = []
        for y in range(level_height):
            row = []
            for x in range(level_width):
                idx = y * level_width + x
                if idx < len(tiles):
                    row.append(tiles[idx])
                else:
                    row.append("AA")  # Default tile
            tile_array.append(row)
        
        return tile_array, level_width, level_height
    
    def parse_nw_file(self, nw_file: str) -> Optional[Tuple[list, int, int]]:
        """Parse a .nw level file and extract tile data
        
        Returns: (tile_array, width, height) or None
        """
        if not os.path.exists(nw_file):
            print(f"❌ Level file not found: {nw_file}")
            return None
        
        try:
            with open(nw_file, 'r') as f:
                content = f.read()
            
            # Extract board data
            board_pattern = r'BOARD\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-Za-z0-9+/]+)'
            matches = re.findall(board_pattern, content)
            
            if not matches:
                print("❌ No board data found in level file")
                return None
            
            # Combine all board sections
            all_tile_data = ""
            for x_str, y_str, width_str, height_str, tile_data in matches:
                all_tile_data += tile_data
            
            # Parse into 2D array
            tile_array, width, height = self.parse_level_tiles(all_tile_data)
            
            print(f"✅ Parsed level: {width}x{height} tiles")
            return tile_array, width, height
            
        except Exception as e:
            print(f"❌ Error parsing level file: {e}")
            return None
    
    def create_blocking_map(self, tile_array: list) -> list:
        """Create a boolean map of blocking tiles"""
        blocking_map = []
        for row in tile_array:
            blocking_row = []
            for tile_id in row:
                blocking_row.append(self.is_tile_blocking(tile_id))
            blocking_map.append(blocking_row)
        return blocking_map
    
    def analyze_tiles(self, tile_array: list) -> dict:
        """Analyze tile composition"""
        tile_counts = {}
        blocking_count = 0
        total_tiles = 0
        
        for row in tile_array:
            for tile_id in row:
                tile_counts[tile_id] = tile_counts.get(tile_id, 0) + 1
                total_tiles += 1
                if self.is_tile_blocking(tile_id):
                    blocking_count += 1
        
        return {
            "total_tiles": total_tiles,
            "unique_tiles": len(tile_counts),
            "blocking_tiles": blocking_count,
            "passable_tiles": total_tiles - blocking_count,
            "blocking_percentage": (blocking_count / total_tiles * 100) if total_tiles > 0 else 0,
            "most_common": sorted(tile_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        }


class TilesetMapper:
    """Maps tile IDs/strings to tileset positions"""
    
    def __init__(self):
        self.base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        self.tileset_width = 128  # Tiles per row in tileset
        self.tileset_height = 32  # Total rows in tileset
        
        # Build string to position mapping from alltiles.nw structure
        self.string_to_position = self._build_alltiles_mapping()
    
    def _build_alltiles_mapping(self) -> Dict[str, Tuple[int, int]]:
        """Build mapping based on alltiles.nw structure"""
        mapping = {}
        
        # Build mapping for all 4096 possible tile IDs
        for tile_id in range(4096):
            tile_str = self.tile_id_to_string(tile_id)
            
            # Calculate position in alltiles.nw (64x64 grid)
            alltiles_y = tile_id // 64
            alltiles_x = tile_id % 64
            
            # Convert alltiles position to tileset position
            # alltiles.nw layout:
            # Rows 0-31: Left half of tileset (columns 0-63)
            # Rows 32-63: Right half of tileset (columns 64-127)
            if alltiles_y < 32:
                # Top half of alltiles = left side of tileset
                tileset_x = alltiles_x
                tileset_y = alltiles_y
            else:
                # Bottom half of alltiles = right side of tileset
                tileset_x = alltiles_x + 64
                tileset_y = alltiles_y - 32
            
            mapping[tile_str] = (tileset_x, tileset_y)
        
        return mapping
    
    def tile_id_to_string(self, tile_id: int) -> str:
        """Convert tile ID to string representation"""
        if 0 <= tile_id < 4096:
            first_char = self.base64_chars[tile_id // 64]
            second_char = self.base64_chars[tile_id % 64]
            return first_char + second_char
        return "??"
    
    def string_to_tile_id(self, tile_str: str) -> int:
        """Convert tile string to ID"""
        if len(tile_str) == 2:
            first_idx = self.base64_chars.find(tile_str[0])
            second_idx = self.base64_chars.find(tile_str[1])
            if first_idx >= 0 and second_idx >= 0:
                return first_idx * 64 + second_idx
        return 0
    
    def get_tileset_position(self, tile_id: int) -> Tuple[int, int]:
        """Get tileset position for a tile ID"""
        tile_str = self.tile_id_to_string(tile_id)
        return self.string_to_position.get(tile_str, (0, 0))
    
    def get_tileset_position_from_string(self, tile_str: str) -> Tuple[int, int]:
        """Get tileset position for a tile string"""
        return self.string_to_position.get(tile_str, (0, 0))
    
    def parse_board_data(self, board_data: bytes) -> List[List[int]]:
        """Parse raw board data from server into 2D tile ID array"""
        tiles = []
        for y in range(64):
            row = []
            for x in range(64):
                idx = y * 64 + x
                if idx * 2 + 1 < len(board_data):
                    tile_id = struct.unpack('<H', board_data[idx*2:idx*2+2])[0]
                    row.append(tile_id)
                else:
                    row.append(0)
            tiles.append(row)
        return tiles


def load_graal_tiles(tileset_dir: str) -> Optional[TileMapping]:
    """Load Graal tile mapping from directory"""
    mapping_file = os.path.join(tileset_dir, "mytext.txt")
    
    tile_mapping = TileMapping()
    if tile_mapping.load_mapping(mapping_file):
        return tile_mapping
    return None