"""
Raw Data Handler - Handles raw data streams after PLO_RAWDATA
"""

from typing import Optional, Dict, Any, Callable
from .events import EventManager, EventType
from .board_collector import BoardCollector


class RawDataHandler:
    """Handles raw data streams that come after PLO_RAWDATA packets"""
    
    def __init__(self, event_manager: EventManager, level_manager=None):
        """Initialize raw data handler
        
        Args:
            event_manager: Event manager for emitting events
            level_manager: Level manager for applying board data
        """
        self.events = event_manager
        self.level_manager = level_manager
        self.expected_size = 0
        self.buffer = b""
        self.active = False
        self.context = {}  # Store context like current level
        
        # Board collector for assembling BOARD text data
        self.board_collector = BoardCollector(event_manager)
        
        # Tile data comparison cache for debugging
        self.tile_data_cache = {}  # level_name -> {'plo_boardpacket': bytes, 'glevnw01': bytes}
        
    def start_raw_data(self, size: int, context: Dict[str, Any] = None):
        """Start collecting raw data of specified size
        
        Args:
            size: Expected size in bytes
            context: Optional context (e.g., current level)
        """
        self.expected_size = size
        self.buffer = b""
        self.active = True
        self.context = context or {}
        print(f"🔄 Raw data mode activated, expecting {size} bytes")
        
    def process_data(self, data: bytes) -> Optional[bytes]:
        """Process incoming data while in raw data mode
        
        Args:
            data: Raw data bytes
            
        Returns:
            None if all data was consumed, leftover bytes if any remain
        """
        if not self.active:
            return data  # Return data to be processed normally
            
        # Add to buffer
        self.buffer += data
        
        # Check if we have all expected data
        if len(self.buffer) >= self.expected_size:
            print(f"✅ Raw data complete: {len(self.buffer)} bytes")
            self._handle_complete_data()
            
            # Check if there's leftover data
            if len(self.buffer) > self.expected_size:
                leftover = self.buffer[self.expected_size:]
                print(f"⚠️ {len(leftover)} bytes leftover after raw data")
                # This leftover should be processed normally
                self.active = False
                return leftover
            
            self.active = False
            
        return None  # All data was consumed
        
    def _handle_complete_data(self):
        """Handle the complete raw data buffer"""
        data = self.buffer[:self.expected_size]
        
        # Check what type of data this is
        if self.expected_size == 8194:  # PLO_BOARDPACKET size
            self._handle_board_packet_stream(data)
        elif self._looks_like_text_board_data(data):
            self._handle_text_board_stream(data)
        elif self._looks_like_file_packet(data):
            self._handle_file_packet_stream(data)
        else:
            # Unknown raw data type
            print(f"❓ Unknown raw data type, size: {len(data)}")
            print(f"   First 20 bytes: {data[:20].hex()}")
            
    def _handle_board_packet_stream(self, data: bytes):
        """Handle PLO_BOARDPACKET in raw data stream"""
        # Expected format: PLO_BOARDPACKET (1 byte) + board data (8192 bytes) + newline (1 byte)
        if len(data) >= 8193 and data[0] - 32 == 101:  # PLO_BOARDPACKET
            print("📦 Processing PLO_BOARDPACKET from raw stream")
            board_data = data[1:8193]  # Skip packet ID, take 8192 bytes
            
            # Get current level name from context
            level_name = self.context.get('level', 'unknown')
            
            # Apply board data directly to the level
            if self.level_manager and level_name != 'unknown':
                level = self.level_manager.get_level(level_name)
                if level:
                    # Debug: show first few tile IDs
                    first_tiles = []
                    for i in range(0, min(20, len(board_data)), 2):
                        tile_id = int.from_bytes(board_data[i:i+2], 'little')
                        first_tiles.append(tile_id)
                    print(f"   📋 PLO_BOARDPACKET first tiles: {first_tiles[:10]}")
                    
                    level.set_board_data(board_data)
                    print(f"✅ Applied {len(board_data)} bytes of board data to {level_name}")
                    
                    # Save for comparison debugging
                    self._save_tile_data_for_comparison(level_name, board_data, 'plo_boardpacket')
                    
                    # Emit event for UI updates
                    self.events.emit(EventType.LEVEL_BOARD_LOADED,
                                   level=level,
                                   board_data=board_data)
                else:
                    print(f"❌ Could not find level {level_name} to apply board data")
            else:
                print(f"⚠️ No level manager available to apply board data")
                           
    def _looks_like_text_board_data(self, data: bytes) -> bool:
        """Check if data looks like text-based BOARD data"""
        try:
            # Try to decode first line
            newline_pos = data.find(b'\n')
            if newline_pos > 0:
                first_line = data[:newline_pos].decode('latin-1')
                return first_line.startswith("BOARD ")
        except:
            pass
        return False
        
    def _handle_text_board_stream(self, data: bytes):
        """Handle text-based BOARD data stream"""
        print("📝 Processing text BOARD data from raw stream")
        
        # Split into lines and process each BOARD line
        try:
            text = data.decode('latin-1')
            lines = text.split('\n')
            
            board_count = 0
            for line in lines:
                line = line.strip()
                if line.startswith("BOARD "):
                    board_count += 1
                    self._process_board_line(line)
                    
            print(f"✅ Processed {board_count} BOARD lines")
            
        except Exception as e:
            print(f"❌ Error processing text board stream: {e}")
            
    def _process_board_line(self, line: str):
        """Process a single BOARD text line"""
        parts = line.split(' ', 5)
        
        if len(parts) < 5:
            return
            
        try:
            x = int(parts[1])
            y = int(parts[2])
            width = int(parts[3])
            height = int(parts[4])
            tile_data = parts[5] if len(parts) > 5 else ""
            
            # Emit board data text event
            self.events.emit(EventType.BOARD_DATA_TEXT,
                           x=x, y=y, width=width, height=height,
                           data=tile_data)
                           
        except ValueError:
            print(f"⚠️ Invalid BOARD line: {line[:50]}...")
            
    def _looks_like_file_packet(self, data: bytes) -> bool:
        """Check if data looks like a FILE packet"""
        # FILE packets start with PLO_FILE (102 - 32 = 70)
        if len(data) > 0 and data[0] - 32 == 102:
            return True
        return False
        
    def _handle_file_packet_stream(self, data: bytes):
        """Handle PLO_FILE packet in raw data stream"""
        print("📁 Processing FILE packet from raw stream")
        
        # Debug: show raw data
        print(f"   Raw data first 50 bytes hex: {data[:50].hex()}")
        print(f"   Raw data first 50 bytes text: {repr(data[:50])}")
        
        if len(data) < 7:  # Minimum size for a FILE packet
            print(f"❌ FILE packet too small: {len(data)} bytes")
            return
            
        # Based on debug analysis, this server uses a non-standard FILE packet format
        # The pattern appears to be: [PLO_FILE(1)] [modtime(5)] [unknown_byte] [filename] [file_data]
        # where filename is not length-prefixed but null-terminated or ends at a pattern
        pos = 0
        
        # Skip PLO_FILE byte
        pos += 1
        
        # Use 5-byte modTime based on pattern analysis
        if len(data) >= pos + 5:
            modtime_bytes = data[pos:pos+5]
            pos += 5
            print(f"   Using 5-byte modTime: {modtime_bytes.hex()}")
        else:
            print(f"   ❌ Not enough data for modTime")
            return
            
        # Skip the unknown byte (seems to be constant 2b)
        if pos < len(data):
            unknown_byte = data[pos]
            pos += 1
            print(f"   Unknown byte: 0x{unknown_byte:02x}")
        
        # Now find the filename by looking for the .nw pattern
        nw_pos = data.find(b'.nw', pos)
        if nw_pos == -1:
            print(f"   ❌ Could not find .nw pattern in filename")
            return
            
        # Work backwards from .nw to find the start of the filename
        filename_start = pos
        for i in range(nw_pos - 1, pos - 1, -1):
            char = data[i:i+1]
            if not (char.isalnum() or char in b'-_.'):
                filename_start = i + 1
                break
                
        filename_data = data[filename_start:nw_pos+3]
        filename = filename_data.decode('latin-1')
        
        # Set position after filename
        pos = nw_pos + 3
        print(f"   Extracted filename: '{filename}' (from position {filename_start} to {nw_pos+3})")
        print(f"📄 FILE: '{filename}'")
        
        # Rest is file data (minus trailing newline)
        file_data = data[pos:]
        if file_data.endswith(b'\n'):
            file_data = file_data[:-1]
            
        # Save raw file data for caching and inspection
        self._save_raw_file(filename, file_data)
        
        # Emit FILE_RECEIVED event with proper filename
        if hasattr(self, 'events'):
            # Fix the filename issue - it's coming through as 'unknown' in the event
            # because the file handler in client.py doesn't properly extract the filename
            self.events.emit(EventType.FILE_RECEIVED,
                           filename=filename,
                           data=file_data)
            
        # Check if this is a GMAP level file
        if filename.endswith('.nw'):
            # Check if it's GLEVNW01 format (either with header or just BOARD lines)
            is_glevnw01 = (file_data.startswith(b'GLEVNW01') or 
                          b'BOARD ' in file_data[:100])  # Look for BOARD in first 100 bytes
            
            if is_glevnw01:
                print(f"   ✅ GLEVNW01 level file found")
                print(f"   Level file size: {len(file_data)} bytes")
                self._handle_glevnw01_file(filename, file_data)
            else:
                print(f"   📦 Unknown .nw file format, size: {len(file_data)} bytes")
                print(f"   Data starts with: {file_data[:50]}")
        else:
            print(f"   📦 Other file type, size: {len(file_data)} bytes")
            
    def _handle_glevnw01_file(self, filename: str, file_data: bytes):
        """Handle GLEVNW01 format level file"""
        from .level_parser import LevelParser
        
        # Remove .nw extension to get level name
        level_name = filename
        
        print(f"🗺️ Processing GMAP segment file: {level_name}")
        
        # Parse the full level file
        parser = LevelParser()
        level_data = parser.parse(file_data)
        
        # Extract board data
        board_bytes = level_data['board_data']
        
        if len(board_bytes) == 8192:  # 64x64 tiles * 2 bytes each
            if self.level_manager:
                # Debug: show first few tile IDs
                first_tiles = []
                for i in range(0, min(20, len(board_bytes)), 2):
                    tile_id = int.from_bytes(board_bytes[i:i+2], 'little')
                    first_tiles.append(tile_id)
                print(f"   📋 GLEVNW01 first tiles: {first_tiles[:10]}")
                
                # Create/update level
                level = self.level_manager.get_or_create_level(level_name)
                level.set_board_data(board_bytes)
                
                # Store additional level data
                level.links = level_data['links']
                level.npcs = level_data['npcs']
                level.signs = level_data['signs']
                level.chests = level_data['chests']
                
                print(f"   ✅ Applied board data to {level_name}")
                print(f"   📍 Found {len(level.links)} links, {len(level.npcs)} NPCs, {len(level.signs)} signs")
                
                # Save for comparison debugging
                self._save_tile_data_for_comparison(level_name, board_bytes, 'glevnw01')
                
                # Emit event via events system
                if hasattr(self, 'events'):
                    self.events.emit(EventType.LEVEL_BOARD_LOADED,
                                   level=level,
                                   board_data=board_bytes)
            else:
                print(f"   ⚠️ No level manager available to store board data")
        else:
            print(f"   ❌ Unexpected board data size: {len(board_bytes)} bytes (expected 8192)")
            
    def _save_raw_file(self, filename: str, file_data: bytes):
        """Save raw file data to disk for caching and inspection"""
        import os
        try:
            # Create cache directory
            cache_dir = os.path.join(os.path.dirname(__file__), '..', 'raw_files_cache')
            os.makedirs(cache_dir, exist_ok=True)
            
            # Save raw file
            cache_path = os.path.join(cache_dir, filename)
            with open(cache_path, 'wb') as f:
                f.write(file_data)
            print(f"   💾 Saved raw file: {cache_path}")
            
            # Also save as text for inspection if it looks like text
            if file_data.startswith(b'GLEVNW01'):
                try:
                    text_content = file_data.decode('latin-1')
                    text_path = cache_path + '.txt'
                    with open(text_path, 'w', encoding='latin-1') as f:
                        f.write(text_content)
                    print(f"   📝 Saved text version: {text_path}")
                except:
                    pass
                    
        except Exception as e:
            print(f"   ⚠️ Could not save file {filename}: {e}")
            
    def _decode_board_string(self, tile_str: str) -> bytes:
        """Decode BOARD tile string to binary format"""
        # Each tile is 2 characters using base 64 encoding
        board_data = bytearray()
        
        # Graal's base64 character set
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        for i in range(0, len(tile_str), 2):
            if i + 1 < len(tile_str):
                # Convert 2 characters to tile ID using base 64
                char1 = tile_str[i]
                char2 = tile_str[i + 1]
                
                idx1 = base64_chars.find(char1)
                idx2 = base64_chars.find(char2)
                
                if idx1 >= 0 and idx2 >= 0:
                    # Graal tile ID format: first_char * 64 + second_char
                    tile_id = idx1 * 64 + idx2
                else:
                    # Invalid character, use tile 0
                    tile_id = 0
                
                # Store as little-endian 16-bit
                board_data.extend(tile_id.to_bytes(2, 'little'))
                
        return bytes(board_data)
        
    def _save_tile_data_for_comparison(self, level_name: str, tile_data: bytes, source: str):
        """Save tile data for comparison debugging
        
        Args:
            level_name: Name of the level
            tile_data: 8192 bytes of tile data 
            source: Either 'plo_boardpacket' or 'glevnw01'
        """
        if level_name not in self.tile_data_cache:
            self.tile_data_cache[level_name] = {}
            
        self.tile_data_cache[level_name][source] = tile_data
        print(f"💾 Saved {source} tile data for {level_name} (first tiles: {[int.from_bytes(tile_data[i:i+2], 'little') for i in range(0, min(20, len(tile_data)), 2)]})")
        
        # If we have both versions, compare them
        if 'plo_boardpacket' in self.tile_data_cache[level_name] and 'glevnw01' in self.tile_data_cache[level_name]:
            self._compare_tile_data(level_name)
            
    def _compare_tile_data(self, level_name: str):
        """Compare PLO_BOARDPACKET vs GLEVNW01 tile data for the same level"""
        plo_data = self.tile_data_cache[level_name]['plo_boardpacket']
        glevnw01_data = self.tile_data_cache[level_name]['glevnw01']
        
        print(f"\n🔍 TILE DATA COMPARISON for {level_name}:")
        print(f"   PLO_BOARDPACKET: {len(plo_data)} bytes")
        print(f"   GLEVNW01:        {len(glevnw01_data)} bytes")
        
        if plo_data == glevnw01_data:
            print(f"   ✅ Tile data MATCHES perfectly!")
            return
            
        # Find differences
        differences = 0
        for i in range(0, min(len(plo_data), len(glevnw01_data)), 2):
            plo_tile = int.from_bytes(plo_data[i:i+2], 'little') if i+1 < len(plo_data) else 0
            glev_tile = int.from_bytes(glevnw01_data[i:i+2], 'little') if i+1 < len(glevnw01_data) else 0
            
            if plo_tile != glev_tile:
                if differences < 10:  # Show first 10 differences
                    tile_x = (i // 2) % 64
                    tile_y = (i // 2) // 64
                    print(f"   ❌ Tile ({tile_x},{tile_y}): PLO={plo_tile}, GLEVNW01={glev_tile}")
                differences += 1
                
        if differences > 10:
            print(f"   ... and {differences - 10} more differences")
            
        print(f"   Total differences: {differences}/{len(plo_data)//2} tiles")
        
        # Show first few tile IDs from each
        print(f"   First 10 PLO tiles:      {[int.from_bytes(plo_data[i:i+2], 'little') for i in range(0, min(20, len(plo_data)), 2)]}")
        print(f"   First 10 GLEVNW01 tiles: {[int.from_bytes(glevnw01_data[i:i+2], 'little') for i in range(0, min(20, len(glevnw01_data)), 2)]}")
        print()
        
    def clear_file_cache(self):
        """Clear the raw files cache directory"""
        import os
        import shutil
        
        try:
            cache_dir = os.path.join(os.path.dirname(__file__), '..', 'raw_files_cache')
            if os.path.exists(cache_dir):
                file_count = len([f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))])
                print(f"[CACHE] Clearing {file_count} files from cache directory: {cache_dir}")
                shutil.rmtree(cache_dir)
                os.makedirs(cache_dir, exist_ok=True)
                print(f"[CACHE] Cache directory cleared and recreated")
            else:
                print(f"[CACHE] Cache directory doesn't exist: {cache_dir}")
                
            # Also clear in-memory tile data cache
            cache_entries = len(self.tile_data_cache)
            self.tile_data_cache.clear()
            print(f"[CACHE] Cleared {cache_entries} in-memory tile cache entries")
            
        except Exception as e:
            print(f"[CACHE] Error clearing cache: {e}")