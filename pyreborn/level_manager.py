"""
Level Manager for handling level data, tiles, and assets
"""

import os
import gzip
import zlib
from typing import Dict, List, Optional, Tuple, Any, Callable
from .models.level import Level, Sign, Chest, LevelLink, NPC, Baddy
from .protocol.enums import ServerToPlayer


class LevelManager:
    """Manages level data, tiles, and asset requests"""
    
    def __init__(self, client):
        self.client = client
        self.current_level: Optional[Level] = None
        self.levels: Dict[str, Level] = {}  # Cache of loaded levels
        self.assets: Dict[str, bytes] = {}  # Downloaded assets
        self.pending_requests: Dict[str, List[Callable]] = {}  # File request callbacks
        
        # Asset cache directory (optional)
        self.cache_dir = None
        
        # Level file queue for requests
        self.requested_files = set()
        
        # Tile mapping for collision detection
        self.tile_mapping = None
        
    def set_cache_directory(self, cache_dir: str):
        """Set directory for caching downloaded assets"""
        self.cache_dir = cache_dir
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
    
    def handle_player_warp(self, x: float, y: float, level_name: str):
        """Handle player warping to a new level"""
        print(f"🚪 Warping to level: {level_name} at ({x}, {y})")
        
        # Create or get level
        if level_name not in self.levels:
            self.levels[level_name] = Level(level_name)
        
        old_level = self.current_level
        self.current_level = self.levels[level_name]
        
        # Update player position in new level
        if self.client.local_player:
            self.client.local_player.x = x
            self.client.local_player.y = y
            self.client.local_player.level = level_name
            
            # Add player to level
            self.current_level.add_player(self.client.local_player)
            
            # Remove from old level
            if old_level and self.client.local_player.id in old_level.players:
                old_level.remove_player(self.client.local_player.id)
        
        # Request level file if we don't have it
        level_file = f"{level_name}.nw"
        if level_file not in self.assets and level_file not in self.requested_files:
            self.request_file(level_file)
        
        # Update session manager
        if hasattr(self.client, 'session'):
            self.client.session.enter_level(self.current_level)
        
        # Emit level change event
        if hasattr(self.client, 'events'):
            from .events import EventType
            self.client.events.emit(EventType.LEVEL_ENTERED, level=self.current_level)
    
    def handle_level_name(self, name: str):
        """Handle level name packet"""
        if self.current_level:
            self.current_level.name = name
        print(f"📍 Current level: {name}")
    
    def handle_level_board(self, data: bytes):
        """Handle level board data (tile data)"""
        if not self.current_level:
            print("⚠️  Received level board data but no current level!")
            return
        
        try:
            # Parse level board format
            # Format varies but typically: [width][height][tile data...]
            if len(data) < 2:
                return
                
            width = data[0] - 32 if data[0] >= 32 else data[0]
            height = data[1] - 32 if data[1] >= 32 else data[1]
            
            # Sanity check
            if width <= 0 or height <= 0 or width > 1024 or height > 1024:
                print(f"⚠️  Invalid level dimensions: {width}x{height}")
                return
            
            self.current_level.width = width
            self.current_level.height = height
            
            # Initialize tiles array
            self.current_level.tiles = [[0] * width for _ in range(height)]
            
            # Parse tile data
            pos = 2
            for y in range(height):
                for x in range(width):
                    if pos + 1 < len(data):
                        # Tiles are typically 2 bytes each
                        tile_low = data[pos] - 32 if data[pos] >= 32 else data[pos]
                        tile_high = data[pos + 1] - 32 if data[pos + 1] >= 32 else data[pos + 1]
                        tile = tile_low | (tile_high << 8)
                        self.current_level.tiles[y][x] = tile
                        pos += 2
                    else:
                        break
            
            print(f"🗺️  Loaded level board: {width}x{height} tiles")
            
            # Emit level board loaded event
            if hasattr(self.client, 'events'):
                from .events import EventType
                self.client.events.emit(EventType.LEVEL_BOARD_LOADED, 
                                      level=self.current_level, 
                                      width=width, height=height)
            
        except Exception as e:
            print(f"❌ Error parsing level board: {e}")
    
    def handle_board_modify(self, x: int, y: int, width: int, height: int, tiles: List[int]):
        """Handle tile modification"""
        if not self.current_level:
            return
        
        # Apply tile changes
        tile_idx = 0
        for dy in range(height):
            for dx in range(width):
                if tile_idx < len(tiles):
                    new_x = x + dx
                    new_y = y + dy
                    if (0 <= new_x < self.current_level.width and 
                        0 <= new_y < self.current_level.height):
                        self.current_level.set_tile(new_x, new_y, tiles[tile_idx])
                    tile_idx += 1
        
        print(f"🔧 Modified tiles at ({x}, {y}) size {width}x{height}")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_tile_update(self.current_level.name, x, y, width, height)
        
        # Emit tile update event
        if hasattr(self.client, 'events'):
            from .events import EventType
            self.client.events.emit(EventType.TILES_UPDATED,
                                  level=self.current_level.name,
                                  x=x, y=y, width=width, height=height,
                                  tiles=tiles)
    
    def handle_level_sign(self, x: int, y: int, text: str):
        """Handle level sign"""
        if not self.current_level:
            return
        
        sign = Sign(x, y, text)
        self.current_level.signs.append(sign)
        print(f"📋 Added sign at ({x}, {y}): {text[:50]}...")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_level_object_added(
                self.current_level.name, "Sign", x, y, text
            )
        
        # Emit sign added event
        if hasattr(self.client, 'events'):
            from .events import EventType
            self.client.events.emit(EventType.LEVEL_SIGN_ADDED, 
                                  level=self.current_level.name,
                                  sign=sign, x=x, y=y, text=text)
    
    def handle_level_chest(self, x: int, y: int, item: int, sign_text: str):
        """Handle level chest"""
        if not self.current_level:
            return
        
        chest = Chest(x, y, item, sign_text)
        self.current_level.chests.append(chest)
        print(f"📦 Added chest at ({x}, {y}) with item {item}")
        
        # Log to session manager
        if hasattr(self.client, 'session'):
            self.client.session.log_level_object_added(
                self.current_level.name, "Chest", x, y, f"item {item}"
            )
        
        # Emit chest added event
        if hasattr(self.client, 'events'):
            from .events import EventType
            self.client.events.emit(EventType.LEVEL_CHEST_ADDED,
                                  level=self.current_level.name,
                                  chest=chest, x=x, y=y, item=item, sign_text=sign_text)
    
    def handle_level_link(self, data: bytes):
        """Handle level link"""
        if not self.current_level or len(data) < 10:
            return
        
        try:
            # Parse level link format
            # Simplified parsing - actual format is complex
            x = data[0] - 32 if data[0] >= 32 else data[0]
            y = data[1] - 32 if data[1] >= 32 else data[1]
            width = data[2] - 32 if data[2] >= 32 else data[2]
            height = data[3] - 32 if data[3] >= 32 else data[3]
            
            # Destination would be parsed from remaining data
            dest_level = "unknown"  # Would parse from data
            dest_x = 30.0  # Would parse from data
            dest_y = 30.0  # Would parse from data
            
            link = LevelLink(x, y, width, height, dest_level, dest_x, dest_y)
            self.current_level.links.append(link)
            print(f"🔗 Added level link at ({x}, {y}) size {width}x{height}")
            
            # Log to session manager
            if hasattr(self.client, 'session'):
                self.client.session.log_level_object_added(
                    self.current_level.name, "Link", x, y, f"to {dest_level}"
                )
            
            # Emit link added event
            if hasattr(self.client, 'events'):
                from .events import EventType
                self.client.events.emit(EventType.LEVEL_LINK_ADDED,
                                      level=self.current_level.name,
                                      link=link, x=x, y=y, width=width, height=height,
                                      dest_level=dest_level, dest_x=dest_x, dest_y=dest_y)
            
        except Exception as e:
            print(f"❌ Error parsing level link: {e}")
    
    def handle_file_data(self, filename: str, data: bytes):
        """Handle received file data"""
        print(f"📥 Received file: {filename} ({len(data)} bytes)")
        
        # Store in assets
        self.assets[filename] = data
        self.requested_files.discard(filename)
        
        # Save to cache if enabled
        if self.cache_dir:
            cache_path = os.path.join(self.cache_dir, filename)
            try:
                with open(cache_path, 'wb') as f:
                    f.write(data)
                print(f"💾 Cached file: {cache_path}")
            except Exception as e:
                print(f"❌ Failed to cache file: {e}")
        
        # Process level files
        if filename.endswith('.nw'):
            self.parse_level_file(filename, data)
        
        # Execute callbacks for this file
        if filename in self.pending_requests:
            for callback in self.pending_requests[filename]:
                try:
                    callback(filename, data)
                except Exception as e:
                    print(f"❌ Error in file callback: {e}")
            del self.pending_requests[filename]
    
    def parse_level_file(self, filename: str, data: bytes):
        """Parse a .nw level file"""
        try:
            # Level files can be compressed
            level_data = data
            
            # Try to decompress if it looks compressed
            if data.startswith(b'\\x1f\\x8b'):  # gzip magic
                level_data = gzip.decompress(data)
            elif data.startswith(b'BZ'):  # bzip2 magic
                import bz2
                level_data = bz2.decompress(data)
            
            # Parse level file format
            level_name = filename[:-3]  # Remove .nw extension
            if level_name not in self.levels:
                self.levels[level_name] = Level(level_name)
            
            level = self.levels[level_name]
            
            # Basic parsing - level file format is complex
            # This is a simplified version
            pos = 0
            if len(level_data) > 8:
                # Level files typically start with header
                # Format varies significantly between versions
                print(f"📄 Parsing level file: {filename}")
                
                # Try to extract basic info
                if level_data[0:4] == b'GRLV':  # Graal level magic
                    # Version info would be next
                    pos = 8
                
                # Would parse tiles, objects, NPCs, etc. here
                # This is very complex and version-dependent
                
            level.mod_time = os.path.getmtime(filename) if os.path.exists(filename) else 0
            print(f"✅ Parsed level file: {level_name}")
            
        except Exception as e:
            print(f"❌ Error parsing level file {filename}: {e}")
    
    def request_file(self, filename: str, callback: Optional[Callable] = None):
        """Request a file from the server"""
        if filename in self.requested_files:
            # Already requested, just add callback
            if callback:
                if filename not in self.pending_requests:
                    self.pending_requests[filename] = []
                self.pending_requests[filename].append(callback)
            return
        
        # Check cache first
        if self.cache_dir:
            cache_path = os.path.join(self.cache_dir, filename)
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'rb') as f:
                        data = f.read()
                    print(f"📂 Loaded from cache: {filename}")
                    if callback:
                        callback(filename, data)
                    return
                except Exception as e:
                    print(f"❌ Failed to load from cache: {e}")
        
        # Add callback
        if callback:
            if filename not in self.pending_requests:
                self.pending_requests[filename] = []
            self.pending_requests[filename].append(callback)
        
        # Send request to server
        from .protocol.packets import WantFilePacket
        packet = WantFilePacket(filename)
        self.client.queue_packet(packet.to_bytes())
        self.requested_files.add(filename)
        print(f"📤 Requested file: {filename}")
    
    def get_current_level(self) -> Optional[Level]:
        """Get the current level"""
        return self.current_level
    
    def get_level(self, name: str) -> Optional[Level]:
        """Get a level by name"""
        return self.levels.get(name)
    
    def get_tile(self, x: int, y: int, layer: int = 0) -> int:
        """Get tile at position in current level"""
        if self.current_level:
            return self.current_level.get_tile(x, y, layer)
        return 0
    
    def is_position_blocked(self, x: float, y: float) -> bool:
        """Check if a position is blocked by tiles"""
        if not self.current_level:
            return False
        
        # Get tile at position
        tile_x = int(x)
        tile_y = int(y)
        tile = self.get_tile(tile_x, tile_y)
        
        # Basic blocking logic - would need tile attribute data
        # Tiles 0-15 are typically passable, others may block
        return tile > 15  # Simplified logic
    
    def find_level_links_at(self, x: float, y: float) -> List[LevelLink]:
        """Find level links at a position"""
        if not self.current_level:
            return []
        
        links = []
        for link in self.current_level.links:
            if link.contains(x, y):
                links.append(link)
        return links
    
    def load_tile_mapping(self, tileset_dir: str) -> bool:
        """Load tile mapping for collision detection"""
        try:
            from .tile_mapping import load_graal_tiles
            self.tile_mapping = load_graal_tiles(tileset_dir)
            if self.tile_mapping:
                print(f"🗺️  Loaded tile mapping from: {tileset_dir}")
                return True
            else:
                print(f"❌ Failed to load tile mapping")
                return False
        except Exception as e:
            print(f"❌ Error loading tile mapping: {e}")
            return False
    
    def is_position_blocked_by_tiles(self, x: float, y: float) -> bool:
        """Check if position is blocked using tile mapping data"""
        if not self.current_level or not self.tile_mapping:
            return self.is_position_blocked(x, y)  # Fallback to basic logic
        
        # Get tile at position
        tile_x = int(x)
        tile_y = int(y)
        
        if (0 <= tile_x < self.current_level.width and 
            0 <= tile_y < self.current_level.height and
            self.current_level.tiles):
            
            tile_id = self.current_level.tiles[tile_y][tile_x]
            if isinstance(tile_id, int):
                # Convert numeric tile ID to string format if needed
                tile_id = self._convert_numeric_to_tile_id(tile_id)
            
            # Check with tile mapping
            return self.tile_mapping.is_tile_blocking(str(tile_id))
        
        return False
    
    def analyze_current_level_tiles(self) -> Dict[str, Any]:
        """Analyze tiles in current level"""
        if not self.current_level or not self.current_level.tiles or not self.tile_mapping:
            return {"error": "No level data or tile mapping"}
        
        # Convert tiles to string format if needed
        tile_array = []
        for row in self.current_level.tiles:
            string_row = []
            for tile in row:
                if isinstance(tile, int):
                    tile_id = self._convert_numeric_to_tile_id(tile)
                    string_row.append(tile_id)
                else:
                    string_row.append(str(tile))
            tile_array.append(string_row)
        
        # Use tile mapping to analyze
        analysis = self.tile_mapping.analyze_tiles(tile_array)
        analysis["level_name"] = self.current_level.name
        
        return analysis
    
    def _convert_numeric_to_tile_id(self, tile_num: int) -> str:
        """Convert numeric tile ID to 2-character string format"""
        # This is a simplified conversion - the real Graal encoding is more complex
        # For now, use a basic mapping
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        if tile_num < len(chars) * len(chars):
            first_char = chars[tile_num // len(chars)]
            second_char = chars[tile_num % len(chars)]
            return first_char + second_char
        return "AA"  # Default fallback
    
    def get_level_summary(self) -> Dict[str, Any]:
        """Get summary of level manager state"""
        summary = {
            "current_level": self.current_level.name if self.current_level else None,
            "loaded_levels": len(self.levels),
            "cached_assets": len(self.assets),
            "pending_requests": len(self.pending_requests),
            "tile_mapping_loaded": self.tile_mapping is not None,
            "level_details": {
                name: {
                    "size": f"{level.width}x{level.height}",
                    "players": len(level.players),
                    "npcs": len(level.npcs),
                    "signs": len(level.signs),
                    "chests": len(level.chests),
                    "links": len(level.links)
                }
                for name, level in self.levels.items()
            }
        }
        
        # Add tile mapping info if available
        if self.tile_mapping:
            summary["tile_mapping_tiles"] = len(self.tile_mapping.tiles)
        
        return summary