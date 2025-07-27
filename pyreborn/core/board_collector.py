"""Board data collector for handling text-based board data from GMAP chunks"""

import logging
from typing import Dict, List, Optional, Tuple
from .events import EventType, EventManager

logger = logging.getLogger(__name__)


class BoardCollector:
    """Collects BOARD text rows and assembles them into complete board data"""
    
    def __init__(self, event_manager: Optional[EventManager] = None):
        self.event_manager = event_manager
        self.reset()
        
        # Subscribe to board data text events
        if self.event_manager:
            self.event_manager.subscribe(EventType.BOARD_DATA_TEXT, self._on_board_data_text)
        
    def reset(self):
        """Reset the collector for a new level"""
        self.board_rows: Dict[int, str] = {}  # y -> tile data
        self.expected_rows = 64
        self.level_name = None
        self.width = 64
        self.height = 64
        
    def set_target_level(self, level_name: str):
        """Set which level this board data is for"""
        self.level_name = level_name
        logger.debug(f"Board collector targeting level: {level_name}")
        
    def _on_board_data_text(self, **kwargs):
        """Handle board data text event"""
        x = kwargs.get('x', 0)
        y = kwargs.get('y', 0)
        width = kwargs.get('width', 64)
        height = kwargs.get('height', 0)
        data = kwargs.get('data', '')
        
        # Add this board row
        self.add_board_row(x, y, width, height, data)
        
    def add_board_row(self, x: int, y: int, width: int, height: int, data: str):
        """Add a board row from BOARD text format"""
        # BOARD format: "BOARD x y width height tile_data"
        # For GMAP chunks, x is always 0, y is the row number (0-63)
        # width is always 64, height is always 0 (single row)
        
        if y < 0 or y >= self.expected_rows:
            logger.warning(f"Invalid board row y={y}, expected 0-{self.expected_rows-1}")
            return
            
        self.board_rows[y] = data
        
        # Check if we have all rows
        if len(self.board_rows) == self.expected_rows:
            logger.info(f"Board data complete for {self.level_name}: {self.expected_rows} rows")
            self._process_complete_board()
            
    def _process_complete_board(self):
        """Process the complete board data once all rows are collected"""
        if not self.level_name:
            logger.error("No target level set for board data")
            return
            
        # Convert text data to tile IDs
        tiles = []
        for y in range(self.expected_rows):
            row_data = self.board_rows.get(y, "")
            row_tiles = self._decode_row_tiles(row_data)
            tiles.extend(row_tiles)
            
        # Emit event with complete board data
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_BOARD_COMPLETE,
                                  level=self.level_name,
                                  width=self.width,
                                  height=self.height,
                                  tiles=tiles)
        
        # Reset for next level
        self.reset()
        
    def _decode_row_tiles(self, row_data: str) -> List[int]:
        """Decode a row of tile data from base64-like encoding"""
        tiles = []
        
        # Each tile is encoded as 2 characters
        for i in range(0, len(row_data), 2):
            if i + 1 < len(row_data):
                char1 = row_data[i]
                char2 = row_data[i + 1]
                tile_id = self._decode_tile_chars(char1, char2)
                tiles.append(tile_id)
                
        # Pad to 64 tiles if needed
        while len(tiles) < 64:
            tiles.append(0)
            
        return tiles[:64]  # Ensure exactly 64 tiles
        
    def _decode_tile_chars(self, char1: str, char2: str) -> int:
        """Decode two characters into a tile ID using Graal's base64 encoding"""
        # Graal uses a custom base64-like encoding
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        try:
            index1 = base64_chars.index(char1)
            index2 = base64_chars.index(char2)
            return index1 * 64 + index2
        except ValueError:
            # Invalid character, return empty tile
            return 0