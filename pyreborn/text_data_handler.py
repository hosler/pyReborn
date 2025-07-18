"""
Text Data Handler - Handles raw text data that isn't part of the packet system
"""

from typing import Optional, Dict, Any, Callable
from .events import EventManager, EventType


class TextDataHandler:
    """Handles text-based data that shouldn't go through the packet system"""
    
    def __init__(self, event_manager: EventManager):
        """Initialize text data handler
        
        Args:
            event_manager: Event manager for emitting events
        """
        self.events = event_manager
        self.handlers: Dict[str, Callable] = {
            "BOARD": self._handle_board_text,
            # Add more text handlers here as needed
        }
        
    def check_for_text_data(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Check if data is text-based (not a packet)
        
        Args:
            data: Raw data to check
            
        Returns:
            Parsed result if text data, None if it should be processed as packet
        """
        if not data:
            return None
            
        # Try to decode as text
        try:
            text = data.decode('latin-1')
        except:
            return None
            
        # Check if it starts with a known text command
        for prefix, handler in self.handlers.items():
            if text.startswith(prefix + " "):
                return handler(text)
                
        return None
        
    def _handle_board_text(self, text: str) -> Dict[str, Any]:
        """Handle BOARD text data
        
        Format: BOARD x y width height tile_data...
        
        Args:
            text: BOARD text line
            
        Returns:
            Parsed board data
        """
        # Debug: show what we're parsing
        if text.startswith("BOARD"):
            print(f"🔍 Parsing BOARD text: {text[:60]}...")
        
        parts = text.split(' ', 5)
        
        if len(parts) < 5:
            print(f"⚠️ Invalid BOARD format: {text[:50]}...")
            return {"type": "invalid_board_data", "raw": text}
            
        try:
            # Skip "BOARD" prefix
            x = int(parts[1])
            y = int(parts[2])
            width = int(parts[3])
            height = int(parts[4])
            tile_data = parts[5] if len(parts) > 5 else ""
            
            print(f"   Parsed: x={x}, y={y}, width={width}, height={height}, data_len={len(tile_data)}")
            
            # Emit board data text event
            self.events.emit(EventType.BOARD_DATA_TEXT,
                           x=x, y=y, width=width, height=height, 
                           data=tile_data, raw_data=text)
            
            return {
                "type": "board_data_text",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "data": tile_data
            }
        except ValueError as e:
            print(f"⚠️ Error parsing BOARD data: {e}")
            return {"type": "invalid_board_data", "raw": text}