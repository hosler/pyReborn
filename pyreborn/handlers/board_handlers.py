"""
Board packet handlers for level tile data.
"""
import logging
import struct

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_board_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register board-related packet handlers."""
    
    def handle_board_packet(reader: PacketReader, state: GameState):
        """Handle board packet (level tiles)."""
        # Board packet format:
        # - Already read: packet ID (PLO_BOARDPACKET)
        # - Remaining: raw tile data (2 bytes per tile)
        
        # Board packet format varies - sometimes not full 8192 bytes
        available = reader.bytes_available()
        logger.info(f"Board packet received: {available} bytes available")
        
        if available < 2:
            logger.error(f"Board packet too small: {available} bytes")
            return None
            
        # Read all available tile data
        tile_data = reader.data[reader.pos:]
        
        # Check if there's a newline at the end
        if tile_data and tile_data[-1] == ord('\n'):
            tile_data = tile_data[:-1]  # Remove newline
            logger.debug("Removed trailing newline from board data")
            
        tile_bytes = (len(tile_data) // 2) * 2  # Make sure it's even
        
        # Convert to tile array
        tiles = []
        for i in range(0, tile_bytes, 2):
            tile_id = struct.unpack('<H', tile_data[i:i+2])[0]
            tiles.append(tile_id)
            
        # If we don't have full 4096 tiles, pad with zeros
        while len(tiles) < 4096:
            tiles.append(0)
            
        logger.info(f"Received board data: {len(tiles)} tiles")
        
        # Store in current level
        if state.current_level:
            state.current_level.tiles = tiles
            # Board is always 64x64
            state.current_level.width = 64
            state.current_level.height = 64
            logger.info(f"Level dimensions: 64x64")
            
            events.emit(EventType.LEVEL_BOARD_LOADED,
                level=state.current_level,
                tiles=tiles
            )
        else:
            # No current level yet - create a default one
            logger.warning("Received board data but no current level set - creating default level")
            from ..models.level import Level
            default_level = Level("onlinestartlocal")  # Common default level name
            
            default_level.tiles = tiles
            default_level.width = 64
            default_level.height = 64
            
            # Set as current level
            state.current_level = default_level
            state.level_cache[default_level.name] = default_level
            
            logger.info(f"Created default level: {default_level.name} (64x64)")
            
            events.emit(EventType.LEVEL_CHANGE,
                level_name=default_level.name,
                old_level=None,
                level=default_level
            )
            
            events.emit(EventType.LEVEL_BOARD_LOADED,
                level=default_level,
                tiles=tiles
            )
            
        return tiles
    
    # Register handler
    registry.register(ServerToPlayer.PLO_BOARDPACKET, handle_board_packet)