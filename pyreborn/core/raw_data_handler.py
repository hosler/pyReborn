"""
Raw Data Handler - Handles raw data streams after PLO_RAWDATA
"""

import logging
from typing import Optional, Dict, Any, Callable
from .events import EventManager, EventType
from .board_collector import BoardCollector
from .cache_manager import CacheManager

logger = logging.getLogger(__name__)


class RawDataHandler:
    """Handles raw data streams that come after PLO_RAWDATA packets"""
    
    def __init__(self, event_manager: EventManager, level_manager=None, cache_manager: Optional[CacheManager] = None):
        """Initialize raw data handler
        
        Args:
            event_manager: Event manager for emitting events
            level_manager: Level manager for applying board data
            cache_manager: Optional cache manager for file storage
        """
        self.events = event_manager
        self.level_manager = level_manager
        self.cache_manager = cache_manager
        self.expected_size = 0
        self.buffer = b""
        self.active = False
        self.context = {}  # Store context like current level
        self.consumed_size = 0  # Track how much was consumed
        
        # Board collector for assembling BOARD text data
        self.board_collector = BoardCollector(event_manager)
        
        # Tile data comparison cache for debugging
        self.tile_data_cache = {}  # level_name -> {'plo_boardpacket': bytes, 'glevnw01': bytes}
        
        # Large file accumulator for multi-chunk files
        self.file_accumulator = {}  # filename -> {'chunks': [bytes], 'total_size': int, 'current_size': int, 'ended': bool}
        
        # Track current large file transfer
        self.current_large_file = None
        
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
        logger.debug(f"Raw data mode activated, expecting {size} bytes")
        
    def process_data(self, data: bytes) -> Optional[bytes]:
        """Process incoming data while in raw data mode
        
        Args:
            data: Raw data bytes
            
        Returns:
            Leftover bytes if any remain, empty bytes if exactly expected amount was consumed, 
            None if still collecting data
        """
        if not self.active:
            return data  # Return data to be processed normally
            
        # Special case: if buffer is empty and we have more data than expected,
        # only take what we need
        if len(self.buffer) == 0 and len(data) > self.expected_size:
            # Process only the expected amount
            self.buffer = data[:self.expected_size]
            leftover = data[self.expected_size:]
            logger.info(f"Raw data complete: {len(self.buffer)} bytes (had {len(data)}, returning {len(leftover)} as leftover)")
            self._handle_complete_data()
            self.consumed_size = self.expected_size
            self.active = False
            self.buffer = b""  # Clear buffer
            return leftover
            
        # Normal case: accumulate data
        self.buffer += data
        
        # Check if we have all expected data
        if len(self.buffer) >= self.expected_size:
            logger.info(f"Raw data complete: {len(self.buffer)} bytes (expected: {self.expected_size})")
            self._handle_complete_data()
            
            # Check if there's leftover data
            if len(self.buffer) > self.expected_size:
                leftover = self.buffer[self.expected_size:]
                logger.warning(f"{len(leftover)} bytes leftover after raw data")
                logger.debug(f"Leftover starts with: {leftover[:50].hex() if len(leftover) > 0 else 'none'}")
                logger.debug(f"Leftover as text: {repr(leftover[:50]) if len(leftover) > 0 else 'none'}")
                
                # Check if leftover starts with PLO_RAWDATA
                if len(leftover) > 0 and leftover[0] == 132:
                    logger.info("Leftover data starts with another PLO_RAWDATA packet")
                
                # This leftover should be processed normally
                self.consumed_size = self.expected_size
                self.active = False
                self.buffer = b""  # Clear buffer
                return leftover
            
            self.consumed_size = self.expected_size
            self.active = False
            self.buffer = b""  # Clear buffer
            # Return empty bytes to indicate we consumed exactly what we expected
            return b""
            
        return None  # Still collecting data
        
    def _handle_complete_data(self):
        """Handle the complete raw data buffer"""
        data = self.buffer[:self.expected_size]
        
        logger.debug(f"Handling complete raw data: {self.expected_size} bytes from buffer of {len(self.buffer)} bytes")
        logger.debug(f"First 50 bytes hex: {data[:50].hex()}")
        logger.debug(f"First 50 bytes text: {repr(data[:50])}")
        
        # Check what type of data this is
        if self.expected_size == 8194:  # PLO_BOARDPACKET size
            self._handle_board_packet_stream(data)
        elif self._looks_like_text_board_data(data):
            self._handle_text_board_stream(data)
        elif self._looks_like_file_packet(data) and not self._in_large_file_transfer():
            # Only look for FILE packets if we're NOT in a large file transfer
            self._handle_file_packet_stream(data)
        elif self._in_large_file_transfer():
            # During large file transfer, raw data IS the file content
            self._handle_large_file_chunk(data)
        else:
            # Unknown raw data type
            logger.warning(f"Unknown raw data type, size: {len(data)}")
            logger.debug(f"First 20 bytes: {data[:20].hex()}")
            
    def _handle_board_packet_stream(self, data: bytes):
        """Handle PLO_BOARDPACKET in raw data stream"""
        # Expected format: PLO_BOARDPACKET (1 byte) + board data (8192 bytes) + newline (1 byte)
        if len(data) >= 8193 and data[0] - 32 == 101:  # PLO_BOARDPACKET
            logger.info("Processing PLO_BOARDPACKET from raw stream")
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
                    logger.debug(f"PLO_BOARDPACKET first tiles: {first_tiles[:10]}")
                    
                    level.set_board_data(board_data)
                    logger.info(f"Applied {len(board_data)} bytes of board data to {level_name}")
                    
                    # Mark level as loaded
                    self.level_manager.loaded_levels.add(level_name)
                    logger.debug(f"Added {level_name} to loaded_levels")
                    
                    # Save for comparison debugging
                    self._save_tile_data_for_comparison(level_name, board_data, 'plo_boardpacket')
                    
                    # Emit event for UI updates
                    self.events.emit(EventType.LEVEL_BOARD_LOADED,
                                   level=level,
                                   board_data=board_data)
                else:
                    logger.error(f"Could not find level {level_name} to apply board data")
            else:
                logger.warning(f"No level manager available to apply board data")
                           
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
        logger.info("Processing text BOARD data from raw stream")
        
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
                    
            logger.info(f"Processed {board_count} BOARD lines")
            
        except Exception as e:
            logger.error(f"Error processing text board stream: {e}")
            
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
            logger.warning(f"Invalid BOARD line: {line[:50]}...")
            
    def _looks_like_file_packet(self, data: bytes) -> bool:
        """Check if data looks like a FILE packet"""
        # FILE packets start with PLO_FILE (102 - 32 = 70)
        if len(data) > 0 and data[0] - 32 == 102:
            return True
        return False
        
    def _handle_file_packet_stream(self, data: bytes):
        """Handle PLO_FILE packets in raw data stream - may contain multiple files"""
        logger.info(f"Processing FILE packet stream ({len(data)} bytes)")
        
        pos = 0
        files_processed = 0
        
        # Process all FILE packets in the stream
        while pos < len(data):
            # Check if we have a FILE packet at this position
            if pos + 7 > len(data):  # Not enough data
                break
                
            if data[pos] - 32 != 102:  # Not PLO_FILE
                # Look for next FILE packet
                found = False
                for i in range(pos + 1, len(data)):
                    if data[i] - 32 == 102:
                        pos = i
                        found = True
                        break
                if not found:
                    break
            
            # Process this FILE packet
            packet_data = data[pos:]
            bytes_consumed = self._handle_single_file_packet(packet_data)
            
            if bytes_consumed <= 0:
                break
                
            pos += bytes_consumed
            files_processed += 1
            
        logger.info(f"Processed {files_processed} files from stream, consumed {pos} of {len(data)} bytes")
        
        if pos < len(data):
            logger.warning(f"{len(data) - pos} bytes remaining in FILE stream after processing {files_processed} file(s)")
            # Debug what's left
            logger.debug(f"Remaining bytes start with: {data[pos:pos+50].hex() if pos < len(data) else 'none'}")
            logger.debug(f"Remaining bytes as text: {repr(data[pos:pos+50]) if pos < len(data) else 'none'}")
    
    def _handle_single_file_packet(self, data: bytes) -> int:
        """Handle a single PLO_FILE packet and return bytes consumed"""
        logger.debug("Processing single FILE packet from raw stream")
        
        # Debug: show raw data
        logger.debug(f"Raw data first 50 bytes hex: {data[:50].hex()}")
        logger.debug(f"Raw data first 50 bytes text: {repr(data[:50])}")
        
        if len(data) < 7:  # Minimum size for a FILE packet
            logger.error(f"FILE packet too small: {len(data)} bytes")
            return 0
            
        # FILE packet format (version 2.1+):
        # [PLO_FILE(1)] [modtime(5 bytes GInt5)] [filename_length(1)] [filename] [file_data]
        pos = 0
        
        # Skip PLO_FILE byte
        pos += 1
        
        # Read modTime (5 bytes - encoded as GInt5)
        if len(data) >= pos + 5:
            modtime_bytes = data[pos:pos+5]
            pos += 5
            logger.debug(f"ModTime (5 bytes GInt5): {modtime_bytes.hex()}")
        else:
            logger.error(f"Not enough data for modTime")
            return 0
            
        # Read filename length (encoded as GChar - subtract 32)
        if pos >= len(data):
            logger.error(f"Not enough data for filename length")
            return 0
            
        filename_length_encoded = data[pos]
        filename_length = filename_length_encoded - 32
        pos += 1
        logger.debug(f"Filename length: {filename_length} (encoded as 0x{filename_length_encoded:02x} = '{chr(filename_length_encoded) if 32 <= filename_length_encoded < 127 else '?'}')")
        
        # Read the filename
        if pos + filename_length > len(data):
            logger.error(f"Not enough data for filename (need {filename_length} bytes, have {len(data) - pos})")
            return 0
            
        filename_data = data[pos:pos + filename_length]
        filename = filename_data.decode('latin-1')
        pos += filename_length
        logger.debug(f"Extracted filename: '{filename}' (from pos {pos-len(filename)} to {pos})")
        logger.info(f"FILE: '{filename}'")
        
        # Find end of file data - look for next PLO_FILE or end of data
        file_end = len(data)
        for i in range(pos, len(data)):
            if i + 1 < len(data) and data[i] == ord('\n') and data[i+1] - 32 == 102:
                # Found newline followed by PLO_FILE
                file_end = i
                break
        
        # For GLEVNW01 files, they have a predictable size
        # Check if this is a GLEVNW01 file by looking ahead
        if b'GLEVNW01' in data[pos:pos+20]:
            # GLEVNW01 files are typically ~9363 bytes
            # Header (9) + 64 BOARD lines (~146 bytes each)
            expected_size = 9363  # Based on observed pattern
            if pos + expected_size < len(data):
                # Check if there's another FILE packet after expected size
                check_pos = pos + expected_size
                if check_pos < len(data) and data[check_pos] - 32 == 102:
                    file_end = pos + expected_size
                    logger.debug(f"Detected GLEVNW01 file with predictable size: {expected_size} bytes")
        
        # Extract file data
        file_data = data[pos:file_end]
        if file_data.endswith(b'\n'):
            file_data = file_data[:-1]
            
        logger.debug(f"File data range: {pos} to {file_end} ({file_end - pos} bytes)")
        logger.debug(f"Total data length: {len(data)} bytes")
            
        # Calculate total bytes consumed (including trailing newline if present)
        bytes_consumed = file_end + (1 if file_end < len(data) and data[file_end] == ord('\n') else 0)
        logger.debug(f"Bytes consumed: {bytes_consumed}")
            
        # Check if this file is part of a large file transfer
        if filename in self.file_accumulator:
            # This is a chunk of a large file
            self.accumulate_file_chunk(filename, file_data)
            logger.info(f"[LARGE FILE] Accumulated chunk for {filename}")
        else:
            # Regular file - save normally
            self._save_raw_file(filename, file_data)
            
            # Special logging for GMAP files
            if filename.endswith('.gmap'):
                logger.info(f"[GMAP] GMAP file detected in raw data handler: {filename}")
                logger.info(f"[GMAP] File size: {len(file_data)} bytes")
                logger.info(f"[GMAP] First 50 bytes: {file_data[:50]}")
            
            # Emit FILE_RECEIVED event with proper filename
            if hasattr(self, 'events'):
                # Use dict to ensure proper parameter passing
                self.events.emit(EventType.FILE_RECEIVED, {
                    'filename': filename,
                    'data': file_data
                })
            
        # Check if this is a GMAP level file
        if filename.endswith('.nw'):
            # Check if it's GLEVNW01 format (either with header or just BOARD lines)
            is_glevnw01 = (file_data.startswith(b'GLEVNW01') or 
                          b'BOARD ' in file_data[:100])  # Look for BOARD in first 100 bytes
            
            if is_glevnw01:
                logger.info(f"GLEVNW01 level file found")
                logger.debug(f"Level file size: {len(file_data)} bytes")
                self._handle_glevnw01_file(filename, file_data)
            else:
                logger.info(f"Unknown .nw file format, size: {len(file_data)} bytes")
                logger.debug(f"Data starts with: {file_data[:50]}")
        else:
            logger.info(f"Other file type, size: {len(file_data)} bytes")
            
        return bytes_consumed
            
    def _handle_glevnw01_file(self, filename: str, file_data: bytes):
        """Handle GLEVNW01 format level file"""
        from ..parsers.level_parser import LevelParser
        
        # Remove .nw extension to get level name
        level_name = filename
        
        logger.info(f"Processing GMAP segment file: {level_name}")
        logger.debug(f"File data size: {len(file_data)} bytes")
        logger.debug(f"First 100 chars: {repr(file_data[:100])}")
        
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
                logger.debug(f"GLEVNW01 first tiles: {first_tiles[:10]}")
                
                # Create/update level
                level = self.level_manager.get_or_create_level(level_name)
                level.set_board_data(board_bytes)
                
                # Store additional level data
                level.links = level_data['links']
                level.npcs = level_data['npcs']
                level.signs = level_data['signs']
                level.chests = level_data['chests']
                
                logger.info(f"Applied board data to {level_name}")
                logger.info(f"Found {len(level.links)} links, {len(level.npcs)} NPCs, {len(level.signs)} signs")
                
                # Mark level as loaded in level manager
                if hasattr(self, 'level_manager') and self.level_manager:
                    self.level_manager.loaded_levels.add(level_name)
                    logger.debug(f"Added {level_name} to loaded_levels")
                
                # Save for comparison debugging
                self._save_tile_data_for_comparison(level_name, board_bytes, 'glevnw01')
                
                # Emit event via events system
                if hasattr(self, 'events'):
                    self.events.emit(EventType.LEVEL_BOARD_LOADED,
                                   level=level,
                                   board_data=board_bytes)
            else:
                logger.warning(f"No level manager available to store board data")
        else:
            logger.error(f"Unexpected board data size: {len(board_bytes)} bytes (expected 8192)")
            
    def start_large_file(self, filename: str):
        """Start accumulating a large file sent in chunks
        
        Args:
            filename: Name of the file being received
        """
        logger.info(f"[LARGE FILE] Starting accumulation for: {filename}")
        self.file_accumulator[filename] = {
            'chunks': [],
            'total_size': 0,
            'current_size': 0,
            'ended': False
        }
        
        # Track that we're in a large file transfer
        self.current_large_file = filename
        
    def set_large_file_size(self, filename: str, size: int):
        """Set the expected total size of a large file
        
        Args:
            filename: Name of the file
            size: Total expected size in bytes
        """
        if filename in self.file_accumulator:
            self.file_accumulator[filename]['total_size'] = size
            logger.info(f"[LARGE FILE] {filename}: Expected size = {size:,} bytes")
    
    def accumulate_file_chunk(self, filename: str, chunk_data: bytes):
        """Add a chunk to a file being accumulated
        
        Args:
            filename: Name of the file
            chunk_data: Chunk data to add
        """
        if filename not in self.file_accumulator:
            # Start accumulation if not already started
            self.start_large_file(filename)
        
        file_info = self.file_accumulator[filename]
        file_info['chunks'].append(chunk_data)
        file_info['current_size'] += len(chunk_data)
        
        logger.info(f"[LARGE FILE] {filename}: Added chunk {len(file_info['chunks'])} "
                    f"({len(chunk_data):,} bytes, total: {file_info['current_size']:,} bytes)")
        
        # Check if we've received all data and the transfer has ended
        if (file_info['ended'] and 
            file_info['total_size'] > 0 and 
            file_info['current_size'] >= file_info['total_size']):
            logger.info(f"[LARGE FILE] {filename}: All data received, completing file")
            self.complete_large_file(filename)
    
    def mark_large_file_ended(self, filename: str):
        """Mark that the server has sent PLO_LARGEFILEEND for this file
        
        Args:
            filename: Name of the file
        """
        if filename not in self.file_accumulator:
            logger.warning(f"[LARGE FILE] No accumulation found for: {filename}")
            return
            
        file_info = self.file_accumulator[filename]
        file_info['ended'] = True
        logger.info(f"[LARGE FILE] {filename}: Transfer marked as ended")
        
        # Check if we already have all the data
        if (file_info['total_size'] > 0 and 
            file_info['current_size'] >= file_info['total_size']):
            logger.info(f"[LARGE FILE] {filename}: All data already received, completing file")
            self.complete_large_file(filename)
        else:
            # Allow completion even if slightly incomplete (up to 1% tolerance for protocol overhead)
            missing = file_info['total_size'] - file_info['current_size']
            tolerance = file_info['total_size'] * 0.01  # 1% tolerance
            
            if missing <= tolerance:
                logger.warning(f"[LARGE FILE] {filename}: Transfer ended with minor data loss "
                              f"({missing:,} bytes, {missing/file_info['total_size']*100:.2f}%), completing anyway")
                self.complete_large_file(filename)
            else:
                logger.error(f"[LARGE FILE] {filename}: Transfer ended but missing too much data "
                            f"({missing:,} bytes, {missing/file_info['total_size']*100:.2f}%)")
                # Still complete it so we don't block other downloads
                self.complete_large_file(filename)
    
    def complete_large_file(self, filename: str):
        """Complete a large file accumulation and save the result
        
        Args:
            filename: Name of the file to complete
        """
        if filename not in self.file_accumulator:
            logger.warning(f"[LARGE FILE] No accumulation found for: {filename}")
            return
            
        file_info = self.file_accumulator[filename]
        logger.info(f"[LARGE FILE] Completing {filename}: {len(file_info['chunks'])} chunks, "
                    f"{file_info['current_size']:,} bytes total")
        
        # Check if we received all expected data
        if file_info['total_size'] > 0 and file_info['current_size'] < file_info['total_size']:
            logger.error(f"[LARGE FILE] Incomplete file! Expected {file_info['total_size']:,} bytes, "
                        f"but only received {file_info['current_size']:,} bytes "
                        f"(missing {file_info['total_size'] - file_info['current_size']:,} bytes)")
            logger.warning(f"[LARGE FILE] Saving incomplete file anyway for debugging")
        
        # Combine all chunks
        complete_data = b''.join(file_info['chunks'])
        
        # Save the complete file
        self._save_raw_file(filename, complete_data)
        
        # Emit FILE_RECEIVED event for the complete file
        if hasattr(self, 'events'):
            self.events.emit(EventType.FILE_RECEIVED, {
                'filename': filename,
                'data': complete_data
            })
        
        # Clean up accumulator
        del self.file_accumulator[filename]
        
        # Clear large file tracking
        if self.current_large_file == filename:
            self.current_large_file = None
            
        logger.info(f"[LARGE FILE] Completed and saved: {filename}")
    
    def _save_raw_file(self, filename: str, file_data: bytes):
        """Save raw file data to disk for caching and inspection"""
        import os
        try:
            if self.cache_manager:
                # Use cache manager for organized storage
                cache_path = self.cache_manager.save_file(filename, file_data)
                logger.debug(f"Saved raw file via cache manager: {cache_path}")
            else:
                # Fallback to old method if no cache manager
                cache_dir = os.path.join(os.path.dirname(__file__), '..', 'raw_files_cache')
                os.makedirs(cache_dir, exist_ok=True)
                
                # Save raw file
                cache_path = os.path.join(cache_dir, filename)
                with open(cache_path, 'wb') as f:
                    f.write(file_data)
                logger.debug(f"Saved raw file: {cache_path}")
            
            # Also save as text for inspection if it looks like text
            if file_data.startswith(b'GLEVNW01'):
                try:
                    text_content = file_data.decode('latin-1')
                    text_path = str(cache_path) + '.txt'
                    with open(text_path, 'w', encoding='latin-1') as f:
                        f.write(text_content)
                    logger.debug(f"Saved text version: {text_path}")
                except:
                    pass
                    
        except Exception as e:
            logger.warning(f"Could not save file {filename}: {e}")
            
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
        logger.debug(f"Saved {source} tile data for {level_name} (first tiles: {[int.from_bytes(tile_data[i:i+2], 'little') for i in range(0, min(20, len(tile_data)), 2)]})")
        
        # If we have both versions, compare them
        if 'plo_boardpacket' in self.tile_data_cache[level_name] and 'glevnw01' in self.tile_data_cache[level_name]:
            self._compare_tile_data(level_name)
    
    def _in_large_file_transfer(self) -> bool:
        """Check if we're currently in a large file transfer"""
        return self.current_large_file is not None
    
    def _handle_large_file_chunk(self, data: bytes):
        """Handle raw data that is part of a large file transfer"""
        if not self.current_large_file:
            logger.warning("[LARGE FILE] Received chunk but no active large file transfer")
            return
            
        logger.info(f"[LARGE FILE] Processing {len(data):,} bytes of raw file data for {self.current_large_file}")
        
        # Debug the first chunk to find PNG signature
        if hasattr(self, '_first_chunk_debug') is False:
            self._first_chunk_debug = True
            logger.info(f"[LARGE FILE DEBUG] First chunk raw data:")
            logger.info(f"  First 100 bytes (hex): {data[:100].hex()}")
            logger.info(f"  First 100 bytes (repr): {repr(data[:100])}")
            # Look for PNG signature
            png_sig = b'\x89PNG\r\n\x1a\n'
            png_pos = data.find(png_sig)
            if png_pos >= 0:
                logger.info(f"  PNG signature found at position {png_pos}")
            else:
                logger.info(f"  PNG signature NOT found in first chunk!")
        
        # During large file transfers, each chunk comes with a FILE packet header
        # We need to strip this header to get the actual file data
        if len(data) > 45 and data[0] - 32 == 102:  # PLO_FILE
            # This is a FILE packet, extract just the file data
            # FILE packet format: [PLO_FILE(1)] [modtime(5)] [filename_len(1)] [filename] [data]
            pos = 7  # Skip PLO_FILE + modtime + filename_len
            filename_len = data[6] - 32  # GChar encoding - subtract 32
            pos += filename_len  # Skip filename
            
            # The rest is the actual file data
            actual_data = data[pos:]
            logger.debug(f"[LARGE FILE] Stripped FILE packet header ({pos} bytes), chunk size: {len(actual_data):,} bytes")
            
            # Check for trailing newline that might be part of the packet protocol
            if len(actual_data) > 0 and actual_data[-1] == 0x0A:  # Newline
                logger.debug(f"[LARGE FILE] Found trailing newline, removing it")
                actual_data = actual_data[:-1]
                logger.debug(f"[LARGE FILE] Final chunk size after newline removal: {len(actual_data):,} bytes")
            
            # Add just the file data to the accumulator
            self.accumulate_file_chunk(self.current_large_file, actual_data)
        else:
            # No FILE packet header, use data as-is
            logger.debug(f"[LARGE FILE] No FILE packet header found, using raw data")
            self.accumulate_file_chunk(self.current_large_file, data)
            
    def _compare_tile_data(self, level_name: str):
        """Compare PLO_BOARDPACKET vs GLEVNW01 tile data for the same level"""
        plo_data = self.tile_data_cache[level_name]['plo_boardpacket']
        glevnw01_data = self.tile_data_cache[level_name]['glevnw01']
        
        logger.debug(f"\nTILE DATA COMPARISON for {level_name}:")
        logger.debug(f"   PLO_BOARDPACKET: {len(plo_data)} bytes")
        logger.debug(f"   GLEVNW01:        {len(glevnw01_data)} bytes")
        
        if plo_data == glevnw01_data:
            logger.info(f"   Tile data MATCHES perfectly!")
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
                    logger.error(f"   Tile ({tile_x},{tile_y}): PLO={plo_tile}, GLEVNW01={glev_tile}")
                differences += 1
                
        if differences > 10:
            logger.debug(f"   ... and {differences - 10} more differences")
            
        logger.debug(f"   Total differences: {differences}/{len(plo_data)//2} tiles")
        
        # Show first few tile IDs from each
        logger.debug(f"   First 10 PLO tiles:      {[int.from_bytes(plo_data[i:i+2], 'little') for i in range(0, min(20, len(plo_data)), 2)]}")
        logger.debug(f"   First 10 GLEVNW01 tiles: {[int.from_bytes(glevnw01_data[i:i+2], 'little') for i in range(0, min(20, len(glevnw01_data)), 2)]}")
        logger.debug("")
        
    def clear_file_cache(self):
        """Clear the raw files cache directory"""
        import os
        import shutil
        
        try:
            if self.cache_manager:
                # Use cache manager to clear cache
                self.cache_manager.clear_cache()
            else:
                # Fallback to old method
                cache_dir = os.path.join(os.path.dirname(__file__), '..', 'raw_files_cache')
                if os.path.exists(cache_dir):
                    file_count = len([f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))])
                    logger.info(f"[CACHE] Clearing {file_count} files from cache directory: {cache_dir}")
                    shutil.rmtree(cache_dir)
                    os.makedirs(cache_dir, exist_ok=True)
                    logger.info(f"[CACHE] Cache directory cleared and recreated")
                else:
                    logger.debug(f"[CACHE] Cache directory doesn't exist: {cache_dir}")
                
            # Also clear in-memory tile data cache
            cache_entries = len(self.tile_data_cache)
            self.tile_data_cache.clear()
            logger.info(f"[CACHE] Cleared {cache_entries} in-memory tile cache entries")
            
        except Exception as e:
            logger.error(f"[CACHE] Error clearing cache: {e}")