"""
Unified Stream Processor - Handles all incoming data streams
Replaces RawDataHandler, TextDataHandler, and BoardCollector
"""

import logging
from typing import Optional, Dict, Any, List, Set, Tuple
from dataclasses import dataclass
from .events import EventManager, EventType
from ..protocol.constants import (LEVEL_WIDTH, LEVEL_HEIGHT, BOARD_DATA_SIZE, BASE64_CHARS, 
                         LEVEL_FILE_HEADER, BOARD_COMMAND)

logger = logging.getLogger(__name__)


@dataclass
class ProcessedData:
    """Result of stream processing"""
    data_type: str  # 'file', 'board_complete', 'text_command'
    content: Any
    metadata: Dict[str, Any] = None


class StreamProcessor:
    """Unified processor for all incoming data streams"""
    
    def __init__(self, event_manager: EventManager, level_manager=None, cache_manager=None, packet_analyzer=None):
        """Initialize stream processor
        
        Args:
            event_manager: Event manager for emitting events
            level_manager: Level manager for applying board data
            cache_manager: Optional cache manager for file storage
            packet_analyzer: Optional packet analyzer for debugging
        """
        self.events = event_manager
        self.level_manager = level_manager
        self.cache_manager = cache_manager
        self.packet_analyzer = packet_analyzer
        
        # Raw data stream state
        self.expected_size = 0
        self.buffer = b""
        self.active = False
        self.context = {}
        self.consumed_size = 0
        
        # Board collection state
        self.board_rows: Dict[int, str] = {}  # y -> tile data
        self.expected_rows = LEVEL_HEIGHT
        self.target_level = None
        self.board_width = LEVEL_WIDTH
        self.board_height = LEVEL_HEIGHT
        
        # File accumulation for large files
        self.file_accumulator = {}  # filename -> {'chunks': [bytes], 'total_size': int, 'current_size': int}
        self.current_large_file = None
        
        # Text command handlers
        self.text_handlers = {
            BOARD_COMMAND: self._handle_board_text,
            # Add more text handlers as needed
        }
        
    def start_raw_data(self, size: int, context: Dict[str, Any] = None):
        """Start collecting raw data of specified size"""
        self.expected_size = size
        self.buffer = b""
        self.active = True
        self.context = context or {}
        self.consumed_size = 0
        logger.debug(f"Started raw data collection: {size} bytes expected")
        
    def process_data(self, data: bytes) -> Optional[bytes]:
        """Process incoming data stream
        
        Returns:
            Leftover bytes that couldn't be processed, or None if all processed
        """
        if not self.active:
            return data
            
        # Add to buffer
        self.buffer += data
        self.consumed_size += len(data)
        
        logger.debug(f"Raw data: {len(self.buffer)}/{self.expected_size} bytes")
        
        # Check if we have enough data
        if len(self.buffer) >= self.expected_size:
            # Extract the expected amount
            raw_data = self.buffer[:self.expected_size]
            leftover = self.buffer[self.expected_size:]
            
            # Process the raw data
            self._process_raw_data(raw_data)
            
            # Check if we should continue accumulating (for PLO_RAWDATA continuation)
            should_continue = self.context.get('continue_accumulation', False)
            announced_total = self.context.get('announced_total_size')
            
            if should_continue and announced_total and announced_total > self.expected_size:
                # Continue accumulating the remaining data
                remaining_size = announced_total - self.expected_size
                logger.debug(f"[STREAM_PROCESSOR] Continuing accumulation: {remaining_size} bytes remaining of {announced_total} total")
                
                # Start new accumulation phase for remaining data
                self.expected_size = remaining_size
                self.buffer = leftover if leftover else b""
                self.consumed_size = len(self.buffer)  # Track what we already have
                self.context = {'type': 'rawdata_continuation', 'original_announced_size': announced_total}
                # Keep self.active = True to continue accumulating
                
                return None  # Don't return leftover, we're continuing to accumulate
            else:
                # Normal completion - reset state
                self.active = False
                self.buffer = b""
                self.expected_size = 0
                self.consumed_size = 0
                
                return leftover if leftover else None
            
        return None
        
    def check_for_text_data(self, data: bytes) -> Optional[ProcessedData]:
        """Check if data is text-based command (not a packet)
        
        Returns:
            ProcessedData if text command, None if should be processed as packet
        """
        if not data:
            return None
            
        # Try to decode as text
        try:
            text = data.decode('latin-1')
        except:
            return None
            
        # Check for known text commands
        for prefix, handler in self.text_handlers.items():
            if text.startswith(prefix + " "):
                result = handler(text)
                if result:
                    return ProcessedData(
                        data_type='text_command',
                        content=result,
                        metadata={'command': prefix, 'raw_text': text}
                    )
                    
        return None
        
    def set_board_target_level(self, level_name: str):
        """Set which level board data is being collected for"""
        self.target_level = level_name
        self.board_rows = {}
        logger.debug(f"Board collector targeting level: {level_name}")
        
    def _process_raw_data(self, data: bytes):
        """Process complete raw data"""
        try:
            # Check context for what type of data this is
            context_type = self.context.get('type', 'unknown')
            logger.debug(f"[STREAM_PROCESSOR] Processing {len(data)} bytes with context_type='{context_type}'")
            
            if context_type == 'file':
                # This is file data
                filename = self.context.get('filename', 'unknown.dat')
                logger.debug(f"[STREAM_PROCESSOR] Processing as file: {filename}")
                self._handle_file_data(filename, data)
                
            elif context_type == 'board_packet':
                # This is board packet data (8192 bytes) - reduced logging
                # logger.debug(f"[STREAM_PROCESSOR] Processing as board packet")
                self._handle_board_packet_data(data)
                
            elif context_type == 'rawdata_continuation':
                # This is the remaining data from PLO_RAWDATA after board processing
                original_size = self.context.get('original_announced_size', 0)
                logger.debug(f"[STREAM_PROCESSOR] Processing rawdata continuation: {len(data)} bytes (original announcement: {original_size})")
                self._handle_rawdata_continuation(data)
                
            else:
                # Try to detect data type
                logger.debug(f"[STREAM_PROCESSOR] Detecting data type: {len(data)} bytes, starts with: {data[:20]}")
                
                if len(data) == BOARD_DATA_SIZE or len(data) == BOARD_DATA_SIZE + 2:
                    # Likely board data (8192 bytes or 8194 with headers)
                    # Extract the actual board data if needed
                    if len(data) == BOARD_DATA_SIZE + 2:
                        # Skip 1 byte header and 1 byte footer
                        board_data = data[1:-1]
                    else:
                        board_data = data
                    self._handle_board_packet_data(board_data)
                elif len(data) > 10 and data.startswith(b'GRMAP'):
                    # This is a GMAP file - extract filename from context or data
                    logger.info(f"[STREAM_PROCESSOR] Detected GRMAP data, routing to GMAP handler")
                    self._handle_gmap_file(data)
                elif self._detect_plo_file_packet(data):
                    # This looks like a PLO_FILE packet with embedded filename
                    logger.info(f"[STREAM_PROCESSOR] Detected PLO_FILE packet, parsing filename and content")
                    self._handle_plo_file_packet(data)
                elif len(data) > 100 and LEVEL_FILE_HEADER in data[:20]:
                    # Likely level file
                    filename = self.context.get('filename', 'level.nw')
                    self._handle_file_data(filename, data)
                else:
                    # Generic file data
                    filename = self.context.get('filename', 'data.bin')
                    logger.debug(f"[STREAM_PROCESSOR] Using fallback filename: {filename}")
                    self._handle_file_data(filename, data)
                    
        except Exception as e:
            logger.error(f"Error processing raw data: {e}")
            
    def _handle_file_data(self, filename: str, data: bytes):
        """Handle complete file data"""
        logger.info(f"Processed file: {filename} ({len(data)} bytes)")
        
        # Cache if enabled
        if self.cache_manager:
            try:
                self.cache_manager.cache_file(filename, data)
            except Exception as e:
                logger.warning(f"Failed to cache file {filename}: {e}")
        
        # Emit file received event
        logger.debug(f"[STREAM_PROCESSOR] About to emit FILE_RECEIVED: filename={repr(filename)} (type: {type(filename)}), data_len={len(data)}")
        self.events.emit(EventType.FILE_RECEIVED, {'filename': filename, 'data': data})
        
    def _handle_board_packet_data(self, data: bytes):
        """Handle board packet data - raw 8192 bytes of tile data (64x64 tiles x 2 bytes each)"""
        if len(data) != BOARD_DATA_SIZE:
            logger.warning(f"Expected {BOARD_DATA_SIZE} bytes for board data, got {len(data)}")
            return
            
        logger.info(f"Processing board packet data: {len(data)} bytes (64x64 tiles)")
        
        # Convert raw bytes to tile array (2 bytes per tile)
        tiles = []
        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                # Big endian: first byte is high, second byte is low
                tile_id = (data[i] << 8) | data[i + 1]
                tiles.append(tile_id)
            else:
                tiles.append(0)  # Fallback for odd bytes
        
        logger.debug(f"Converted to {len(tiles)} tiles, first few: {tiles[:10]}")
        
        # Apply directly to level manager if available
        if self.level_manager:
            self.level_manager.handle_board_packet(data, tiles)
        
        # Emit board loaded event
        self.events.emit(EventType.LEVEL_BOARD_LOADED, {'data': data, 'tiles': tiles, 'target_level': self.target_level, 'width': LEVEL_WIDTH, 'height': LEVEL_HEIGHT})
        
        # Analyze as PLO_BOARDPACKET if analyzer is available
        if self.packet_analyzer and self.packet_analyzer.enabled:
            parsed_fields = {
                'type': 'board_data',
                'size': len(data),
                'tiles': len(tiles),
                'first_10_tiles': tiles[:10],
                'target_level': self.target_level
            }
            
            self.packet_analyzer.analyze_packet(
                raw_encrypted=b"",  # Not available in stream processor
                raw_decrypted=b'\x85' + data,  # 101 + 32 = 133 = 0x85
                packet_id=101,  # PLO_BOARDPACKET
                packet_data=data,
                handler_name="stream_processor.handle_board_packet",
                handler_result=parsed_fields,
                handler_error=None,
                parsed_fields=parsed_fields,
                is_text=False,
                is_raw=True,
                stream_context=None
            )
        
    def _handle_board_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Handle BOARD text command: 'BOARD x y width height tile_data'"""
        try:
            parts = text.split(' ', 5)
            if len(parts) != 6:
                logger.warning(f"Invalid BOARD format: {text[:100]}")
                return None
                
            _, x_str, y_str, width_str, height_str, tile_data = parts
            
            x = int(x_str)
            y = int(y_str) 
            width = int(width_str)
            height = int(height_str)
            
            # Add this row to our collection
            self.board_rows[y] = tile_data
            
            # Emit individual board row event
            self.events.emit(EventType.BOARD_DATA_TEXT,
                           {'x': x, 'y': y, 'width': width, 'height': height, 'data': tile_data})
            
            # Check if we have all rows (0-63)
            if len(self.board_rows) >= self.expected_rows:
                if all(row in self.board_rows for row in range(self.expected_rows)):
                    # We have complete board data
                    complete_tiles = self._assemble_complete_board()
                    if complete_tiles:
                        # Apply to level manager
                        if self.level_manager and self.target_level:
                            self.level_manager.handle_board_complete(
                                self.target_level, 
                                self.board_width, 
                                self.board_height, 
                                complete_tiles
                            )
                        
                        # Reset for next level
                        self.board_rows = {}
                        
                        return {
                            'type': 'board_complete',
                            'level': self.target_level,
                            'width': self.board_width,
                            'height': self.board_height,
                            'tiles': complete_tiles
                        }
            
            return {
                'type': 'board_row',
                'x': x, 'y': y, 'width': width, 'height': height,
                'data': tile_data,
                'rows_collected': len(self.board_rows),
                'rows_expected': self.expected_rows
            }
            
        except Exception as e:
            logger.error(f"Error parsing BOARD text: {e}")
            return None
            
    def _assemble_complete_board(self) -> Optional[List[int]]:
        """Assemble complete board from collected rows"""
        try:
            tiles = []
            
            for y in range(self.board_height):
                if y not in self.board_rows:
                    logger.error(f"Missing board row {y}")
                    return None
                    
                row_data = self.board_rows[y]
                
                # Parse tile data (64 tiles per row)
                for i in range(0, len(row_data), 2):
                    if i + 1 < len(row_data):
                        # Convert 2-character tile ID to numeric value
                        char1 = ord(row_data[i])
                        char2 = ord(row_data[i + 1])
                        tile_id = char1 + (char2 << 8)
                        tiles.append(tile_id)
                    else:
                        tiles.append(0)  # Default tile
                        
            return tiles
            
        except Exception as e:
            logger.error(f"Error assembling board data: {e}")
            return None
            
    def reset(self):
        """Reset all state"""
        self.active = False
        self.buffer = b""
        self.expected_size = 0
        self.consumed_size = 0
        self.board_rows = {}
        self.target_level = None
        self.file_accumulator = {}
        self.current_large_file = None
        
    def start_large_file(self, filename: str):
        """Start accumulating a large file transfer"""
        logger.debug(f"Starting large file transfer: {filename}")
        self.file_accumulator[filename] = {
            'chunks': [],
            'total_size': 0,
            'current_size': 0,
            'started': True
        }
        
    def accumulate_file_chunk(self, filename: str, chunk: bytes):
        """Add a chunk to large file accumulator"""
        if filename not in self.file_accumulator:
            self.start_large_file(filename)
            
        accumulator = self.file_accumulator[filename]
        accumulator['chunks'].append(chunk)
        accumulator['current_size'] += len(chunk)
        logger.debug(f"Added chunk to {filename}: {len(chunk)} bytes (total: {accumulator['current_size']})")
        
    def finalize_large_file(self, filename: str) -> Optional[bytes]:
        """Finalize large file and return complete data"""
        if filename not in self.file_accumulator:
            logger.warning(f"Attempted to finalize unknown large file: {filename}")
            return None
            
        accumulator = self.file_accumulator[filename]
        complete_data = b''.join(accumulator['chunks'])
        
        # Clean up
        del self.file_accumulator[filename]
        
        logger.info(f"Finalized large file: {filename} ({len(complete_data)} bytes)")
        
        # Process as normal file
        self._handle_file_data(filename, complete_data)
        return complete_data
    
    def _detect_plo_file_packet(self, data: bytes) -> bool:
        """Detect if this data contains a PLO_FILE packet"""
        if len(data) < 10:
            return False
        
        # Try to parse as a length-prefixed packet
        # The format might be: [length_bytes]filename[file_content]
        try:
            # Check if this could be a length-prefixed filename
            # Look for common file extensions in the first 50 bytes after potential length prefix
            for start_offset in range(1, 8):  # Try different length prefix sizes
                if start_offset >= len(data):
                    continue
                    
                check_data = data[start_offset:start_offset + 50]
                try:
                    text_data = check_data.decode('latin-1', errors='replace')
                    if any(ext in text_data for ext in ['.gmap', '.png', '.nw', '.txt', '.gani']):
                        return True
                except:
                    continue
        except:
            pass
        
        return False
    
    def _handle_plo_file_packet(self, data: bytes):
        """Parse PLO_FILE packet and extract filename and data"""
        try:
            logger.debug(f"[PLO_FILE] Analyzing packet: {len(data)} bytes")
            logger.debug(f"[PLO_FILE] First 20 bytes: {data[:20]}")
            logger.debug(f"[PLO_FILE] As hex: {data[:20].hex()}")
            
            # Try to find the filename by looking for extensions
            filename = 'unknown'
            file_data = data
            
            # Examine the structure more carefully
            # Log each byte and look for patterns
            for i in range(min(15, len(data))):
                byte_val = data[i]
                logger.debug(f"[PLO_FILE] Byte {i}: {byte_val} (0x{byte_val:02x}) '{chr(byte_val) if 32 <= byte_val <= 126 else '?'}'")
                
            # Try different approaches to find the filename
            text_repr = data.decode('latin-1', errors='replace')
            logger.debug(f"[PLO_FILE] As text: {repr(text_repr[:50])}")
            
            # Look for file extensions in the data
            for ext in ['.gmap', '.png', '.nw', '.txt', '.gani']:
                if ext in text_repr:
                    ext_pos = text_repr.find(ext)
                    logger.debug(f"[PLO_FILE] Found {ext} at position {ext_pos}")
                    
                    # Try to extract filename by working backwards from extension
                    start_pos = ext_pos
                    while start_pos > 0 and (text_repr[start_pos - 1].isalnum() or text_repr[start_pos - 1] in '._-'):
                        start_pos -= 1
                    
                    end_pos = ext_pos + len(ext)
                    potential_filename = text_repr[start_pos:end_pos]
                    logger.debug(f"[PLO_FILE] Potential filename: '{potential_filename}'")
                    
                    # Check if this looks like a valid filename
                    if potential_filename and not any(ord(c) < 32 for c in potential_filename):
                        filename = potential_filename
                        
                        # Now find where the file content starts
                        if ext == '.gmap' and b'GRMAP' in data:
                            grmap_pos = data.find(b'GRMAP')
                            file_data = data[grmap_pos:]
                            logger.debug(f"[PLO_FILE] GMAP content starts at byte {grmap_pos}")
                        elif ext == '.png' and b'\x89PNG' in data:
                            png_pos = data.find(b'\x89PNG')
                            file_data = data[png_pos:]
                            logger.debug(f"[PLO_FILE] PNG content starts at byte {png_pos}")
                        else:
                            # Try to guess where content starts after filename
                            filename_end_pos = data.find(filename.encode('latin-1')) + len(filename)
                            file_data = data[filename_end_pos:]
                            logger.debug(f"[PLO_FILE] Generic content starts at byte {filename_end_pos}")
                        
                        break
            
            logger.info(f"[PLO_FILE] Final result: filename='{filename}' content={len(file_data)} bytes")
            self._handle_file_data(filename, file_data)
            
        except Exception as e:
            logger.error(f"Error parsing PLO_FILE packet: {e}")
            # Fallback to unknown file
            self._handle_file_data('unknown', data)
    
    def _handle_rawdata_continuation(self, data: bytes):
        """Handle the remaining data from PLO_RAWDATA after board processing"""
        original_size = self.context.get('original_announced_size', 0)
        logger.info(f"[STREAM_PROCESSOR] Handling rawdata continuation: {len(data)} bytes (original announcement: {original_size})")
        
        # This continuation data could be level files, NPC data, or other content
        # For now, just log it and emit an event
        logger.debug(f"[STREAM_PROCESSOR] Continuation data preview: {data[:50]}")
        
        # Emit event for continuation data
        self.events.emit(EventType.FILE_RECEIVED, {'filename': 'rawdata_continuation.bin', 'data': data})
    
    def _handle_gmap_file(self, data: bytes):
        """Handle GMAP file data"""
        # Check for requested GMAP files to get the correct filename
        filename = 'unknown.gmap'
        
        # Check if there's a pending GMAP request we can match this to
        # Look for .gmap files in recent requests
        if hasattr(self, 'level_manager') and self.level_manager:
            # Check if the level manager has any pending GMAP requests
            if hasattr(self.level_manager, '_pending_file_requests'):
                for req_filename in self.level_manager._pending_file_requests:
                    if req_filename.endswith('.gmap'):
                        filename = req_filename
                        break
        
        # Also check the client's file request tracker
        if hasattr(self, '_client_ref'):
            client = self._client_ref()
            if client and hasattr(client, 'file_request_tracker'):
                tracker = client.file_request_tracker
                pending_files = tracker.get_pending_files()
                for req_filename in pending_files:
                    if req_filename.endswith('.gmap'):
                        filename = req_filename
                        break
        
        logger.info(f"[GMAP_FILE] Detected GMAP file: '{filename}' ({len(data)} bytes)")
        self._handle_file_data(filename, data)