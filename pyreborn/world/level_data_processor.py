"""
Unified Level Data Processor

Handles both PLO_BOARDPACKET and downloaded file data, ensuring all level data
is stored in the same unified format: List[int] of 4096 tile IDs.

This eliminates the dual format problem where packets and files created 
different internal representations.
"""

import logging
import struct
from typing import List, Union, Optional, Dict, Any
from enum import Enum


logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Source of level data"""
    PLO_BOARDPACKET = "packet"  # Binary packet from server
    DOWNLOADED_FILE = "file"    # Text file downloaded from server


class LevelDataProcessor:
    """Unified processor for all level data sources"""
    
    # Reborn's base64-like encoding characters
    BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def process_level_data(self, data: Union[bytes, str, List[str]], 
                          source: DataSource, 
                          level_name: str = "") -> List[int]:
        """
        Process level data from any source into unified format
        
        Args:
            data: Raw level data (format depends on source)
            source: Type of data source
            level_name: Level name for logging
            
        Returns:
            List of 4096 tile IDs (always 64x64 tiles)
        """
        self.logger.debug(f"Processing {source.value} data for level: {level_name}")
        
        try:
            if source == DataSource.PLO_BOARDPACKET:
                return self._process_packet_data(data)
            elif source == DataSource.DOWNLOADED_FILE:
                return self._process_file_data(data, level_name)
            else:
                raise ValueError(f"Unknown data source: {source}")
                
        except Exception as e:
            self.logger.error(f"Failed to process {source.value} data for {level_name}: {e}")
            # Return empty board as fallback
            return [0] * 4096
    
    def _process_packet_data(self, data: bytes) -> List[int]:
        """
        Process PLO_BOARDPACKET binary data
        
        Args:
            data: Binary board data (variable length, 2 bytes per tile)
            
        Returns:
            List of tile IDs (padded to 4096 if needed)
        """
        if len(data) == 0:
            self.logger.warning("Empty board packet data")
            return [0] * 4096
            
        # Decode binary data - little-endian 16-bit unsigned integers
        tiles = []
        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                tile_id = struct.unpack('<H', data[i:i+2])[0]
                tiles.append(tile_id)
            
        # Pad or truncate to exactly 4096 tiles
        if len(tiles) < 4096:
            tiles.extend([0] * (4096 - len(tiles)))
        elif len(tiles) > 4096:
            tiles = tiles[:4096]
            
        self.logger.debug(f"Processed packet data: {len(tiles)} tiles, "
                         f"{sum(1 for t in tiles if t > 0)} non-zero")
        return tiles
    
    def _process_file_data(self, data: Union[str, List[str]], level_name: str) -> List[int]:
        """
        Process downloaded file data (GLEVNW01 format)
        
        Args:
            data: File content as string or list of lines
            level_name: Level name for logging
            
        Returns:
            List of 4096 tile IDs
        """
        if isinstance(data, str):
            lines = data.strip().split('\n')
        else:
            lines = data
            
        if not lines:
            self.logger.warning(f"Empty file data for {level_name}")
            return [0] * 4096
            
        # Check for GLEVNW01 format
        start_line = 0
        if lines and lines[0].strip() == 'GLEVNW01':
            start_line = 1
            self.logger.debug(f"Processing GLEVNW01 format for {level_name}")
        
        # Collect board rows
        board_tiles_by_row = {}
        
        for i in range(start_line, len(lines)):
            line = lines[i].strip()
            
            if line.startswith('BOARD '):
                # BOARD x y width height data
                parts = line.split(None, 5)
                if len(parts) >= 6:
                    x = int(parts[1])
                    y = int(parts[2])
                    width = int(parts[3])
                    height = int(parts[4])
                    board_data = parts[5]
                    
                    # For GLEVNW01: height=0, width=64, each line is one row
                    if height == 0 and width == 64 and 0 <= y < 64:
                        row_tiles = self._decode_board_string(board_data)
                        board_tiles_by_row[y] = row_tiles
        
        # Convert to flat array of exactly 4096 tiles
        tiles = []
        for y in range(64):
            if y in board_tiles_by_row:
                row_tiles = board_tiles_by_row[y]
                # Ensure exactly 64 tiles per row
                if len(row_tiles) < 64:
                    row_tiles.extend([0] * (64 - len(row_tiles)))
                elif len(row_tiles) > 64:
                    row_tiles = row_tiles[:64]
                tiles.extend(row_tiles)
            else:
                # Missing row, fill with zeros
                tiles.extend([0] * 64)
        
        self.logger.debug(f"Processed file data for {level_name}: {len(tiles)} tiles, "
                         f"{sum(1 for t in tiles if t > 0)} non-zero")
        return tiles
    
    def _decode_board_string(self, board_str: str) -> List[int]:
        """
        Decode GLEVNW01 board string using intelligent format detection
        
        Handles the mixed format seen in downloaded files:
        - Two-character format (A9A+A5A6...)
        - Slash-separated format (/f/f/f/...)
        - Mixed content
        
        Args:
            board_str: Encoded board string
            
        Returns:
            List of 64 tile IDs
        """
        if not board_str:
            return [0] * 64
            
        # Strategy 1: Try two-character format first
        two_char_tiles = self._try_two_character_format(board_str)
        if two_char_tiles and sum(1 for t in two_char_tiles if t > 0) > 0:
            return two_char_tiles
            
        # Strategy 2: Try slash-separated format
        slash_tiles = self._try_slash_separated_format(board_str)
        if slash_tiles and sum(1 for t in slash_tiles if t > 0) > 0:
            return slash_tiles
            
        # Strategy 3: Return empty tiles if all fails
        self.logger.warning(f"Failed to decode board string: {repr(board_str[:50])}")
        return [0] * 64
    
    def _try_two_character_format(self, board_str: str) -> Optional[List[int]]:
        """Try to decode as two-character format (A9A+A5A6...)"""
        try:
            # Look for continuous two-character pairs
            two_char_portion = ""
            i = 0
            while i < len(board_str) - 1:
                char1 = board_str[i]
                char2 = board_str[i + 1]
                
                # Accept characters that are base64 OR printable ASCII (for extended formats)
                if ((char1 in self.BASE64_CHARS or char1.isprintable()) and 
                    (char2 in self.BASE64_CHARS or char2.isprintable())):
                    two_char_portion += char1 + char2
                    i += 2
                else:
                    break
            
            if len(two_char_portion) >= 10:  # At least 5 tiles worth
                return self._decode_two_character_string(two_char_portion)
                
        except Exception as e:
            self.logger.debug(f"Two-character format failed: {e}")
            
        return None
    
    def _try_slash_separated_format(self, board_str: str) -> Optional[List[int]]:
        """Try to decode as slash-separated format (/f/f/f/...)"""
        try:
            if '/' in board_str:
                return self._decode_slash_separated_string(board_str)
        except Exception as e:
            self.logger.debug(f"Slash-separated format failed: {e}")
            
        return None
    
    def _decode_two_character_string(self, board_str: str) -> List[int]:
        """Decode two-character format: A9A+A5A6... (2 chars per tile)"""
        tiles = []
        
        # Process pairs of characters
        for i in range(0, len(board_str) - 1, 2):
            char1 = board_str[i]
            char2 = board_str[i + 1]
            
            # Try to decode characters, with fallback for extended characters
            try:
                if char1 in self.BASE64_CHARS and char2 in self.BASE64_CHARS:
                    # Standard base64 decoding
                    val1 = self.BASE64_CHARS.index(char1)
                    val2 = self.BASE64_CHARS.index(char2)
                    tile_id = val1 * 64 + val2
                else:
                    # Extended character handling - map to ASCII values
                    val1 = ord(char1) % 64 if char1 not in self.BASE64_CHARS else self.BASE64_CHARS.index(char1)
                    val2 = ord(char2) % 64 if char2 not in self.BASE64_CHARS else self.BASE64_CHARS.index(char2)
                    tile_id = val1 * 64 + val2
                    
                # Ensure tile ID is in valid range
                tile_id = tile_id % 4096
                tiles.append(tile_id)
            except:
                # Last resort fallback
                tiles.append(0)
                
        # Pad to 64 tiles
        while len(tiles) < 64:
            tiles.append(0)
            
        return tiles[:64]
    
    def _decode_slash_separated_string(self, board_str: str) -> List[int]:
        """Decode slash-separated format: /f/f/f/..."""
        # Remove leading/trailing slashes and split
        clean_str = board_str.strip('/')
        if not clean_str:
            return [0] * 64
            
        parts = clean_str.split('/')
        tiles = []
        
        for part in parts:
            if part in self.BASE64_CHARS:
                tile_id = self.BASE64_CHARS.index(part)
                tiles.append(tile_id)
            else:
                tiles.append(0)
                
        # Pad to 64 tiles
        while len(tiles) < 64:
            tiles.append(0)
            
        return tiles[:64]
    
    def create_empty_level_data(self) -> List[int]:
        """Create empty level data (4096 zeros)"""
        return [0] * 4096
    
    def validate_level_data(self, tiles: List[int]) -> bool:
        """Validate that level data is in correct format"""
        return (isinstance(tiles, list) and 
                len(tiles) == 4096 and
                all(isinstance(t, int) and 0 <= t <= 65535 for t in tiles))