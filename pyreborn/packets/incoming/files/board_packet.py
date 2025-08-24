#!/usr/bin/env python3
"""
PLO_BOARDPACKET (Packet 101) - Board data (Registry Version)

This packet contains level board data, usually 8192 bytes representing
a 64x64 tile grid. Unlike PLO_LEVELBOARD, this data is uncompressed.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, fixed_data_field, PacketReader, parse_field
try:
    from ...utils.tile_validation import validate_tile_array, fix_tile_array, log_tile_statistics
except ImportError:
    # Fallback import for when running directly
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
    from pyreborn.utils.tile_validation import validate_tile_array, fix_tile_array, log_tile_statistics
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


PLO_BOARDPACKET = PacketStructure(
    packet_id=101,
    name="PLO_BOARDPACKET",
    fields=[
        fixed_data_field("board_data", 8192, "Board tile data (8192 bytes)")
    ],
    description="Level board data (usually 8192 bytes)"
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse board data with full business logic.
    
    This function processes level board data including:
    - Tile parsing and validation
    - Tile statistics and analysis
    - Identification of special tiles (water, collision, etc.)
    - Event determination based on board content
    
    Args:
        data: Raw packet data containing board_data field
    
    Returns:
        Dictionary with processed board data and events
    """
    try:
        board_data = data.get('board_data', b'')
        
        if not board_data:
            return {'error': 'No board data', 'tiles': [], 'events': []}
        
        logger.debug(f"🔍 PLO_BOARDPACKET parse() called with {len(board_data)} bytes of board_data")
        
        # Standard Reborn level is 64x64 tiles with 2 bytes per tile
        width = 64
        height = 64
        expected_size = width * height * 2  # 8192 bytes
        
        if len(board_data) < expected_size:
            logger.warning(f"Board data too small: {len(board_data)} < {expected_size}")
            # Pad with zeros if needed
            board_data = board_data + b'\x00' * (expected_size - len(board_data))
        
        # Parse tiles as 16-bit big-endian values (to match Preagonal implementation)
        # Preagonal uses: tileIndex = (byte2 << 8) + byte1
        tiles = []
        tile_stats = {
            'total': 0,
            'non_zero': 0,
            'walkable': 0,
            'blocking': 0,
            'water': 0,
            'special': 0,
            'invalid': 0
        }
        
        # Analyze tiles as we parse them
        first_10_tiles = []
        invalid_tiles = []
        
        # DIAGNOSTIC: Log first few bytes and calculations in detail (only in debug mode)
        if len(board_data) >= 20:
            logger.debug(f"🔍 DIAGNOSTIC: First 20 bytes of board_data: {' '.join(f'{b:02x}' for b in board_data[:20])}")
        
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 2
                
                # Parse as little-endian since raw data is pure tile data: byte1 + (byte2 << 8)
                byte1 = board_data[offset] if offset < len(board_data) else 0
                byte2 = board_data[offset + 1] if offset + 1 < len(board_data) else 0
                tile_id = byte1 + (byte2 << 8)
                
                # DIAGNOSTIC: Log first tile calculation in detail (debug only)
                if x == 0 and y == 0:
                    logger.debug(f"🔍 DIAGNOSTIC: First tile (0,0):")
                    logger.debug(f"    Offset: {offset}")
                    logger.debug(f"    Byte1: 0x{byte1:02x} ({byte1})")
                    logger.debug(f"    Byte2: 0x{byte2:02x} ({byte2})")
                    logger.debug(f"    Calculation: ({byte2} << 8) + {byte1} = {tile_id}")
                    logger.debug(f"    Expected from log: 3461")
                    logger.debug(f"    Match: {tile_id == 3461}")
                
                # Test alternative parsing methods for first tile (debug only)
                if x == 0 and y == 0:
                    alt1 = (byte1 << 8) + byte2  # Swap byte order
                    alt2 = int.from_bytes([byte1, byte2], 'little')
                    alt3 = int.from_bytes([byte1, byte2], 'big')
                    logger.debug(f"🔍 DIAGNOSTIC: Alternative calculations:")
                    logger.debug(f"    Alt1 (byte1<<8)+byte2: {alt1}")
                    logger.debug(f"    Alt2 little-endian: {alt2}")
                    logger.debug(f"    Alt3 big-endian: {alt3}")
                
                # Validate tile ID range (standard Reborn tilesets are typically 0-4095)
                if tile_id > 4095:
                    tile_stats['invalid'] += 1
                    if len(invalid_tiles) < 5:  # Log first 5 invalid tiles
                        invalid_tiles.append(f"({x},{y})={tile_id}")
                    # Clamp to valid range to prevent rendering issues
                    tile_id = tile_id & 0xFFF  # Keep only lower 12 bits (0-4095)
                
                tiles.append(tile_id)
                
                # Debug: log first 10 non-zero tiles
                if tile_id > 0 and len(first_10_tiles) < 10:
                    first_10_tiles.append(f"({x},{y})={tile_id}")
                
                # Collect statistics
                tile_stats['total'] += 1
                if tile_id != 0:
                    tile_stats['non_zero'] += 1
                    
                    # Analyze tile type (these are example ranges, actual values depend on tileset)
                    if tile_id < 512:  # Walkable tiles (grass, dirt, etc.)
                        tile_stats['walkable'] += 1
                    elif 512 <= tile_id < 1024:  # Blocking tiles (walls, trees)
                        tile_stats['blocking'] += 1
                    elif 1024 <= tile_id < 1536:  # Water tiles
                        tile_stats['water'] += 1
                    else:  # Special tiles
                        tile_stats['special'] += 1
        
        # Calculate board characteristics
        board_info = {
            'mostly_empty': tile_stats['non_zero'] < (tile_stats['total'] * 0.1),
            'has_water': tile_stats['water'] > 0,
            'has_blocking': tile_stats['blocking'] > 0,
            'density': tile_stats['non_zero'] / tile_stats['total'] if tile_stats['total'] > 0 else 0
        }
        
        # Determine events to emit
        events_to_emit = []
        
        # Always emit board data received event
        events_to_emit.append({
            'type': 'BOARD_DATA_RECEIVED',
            'data': {
                'width': width,
                'height': height,
                'tile_count': len(tiles),
                'statistics': tile_stats,
                'board_info': board_info
            }
        })
        
        # Emit level update event
        events_to_emit.append({
            'type': 'LEVEL_DATA_UPDATED',
            'data': {
                'update_type': 'board',
                'tile_count': len(tiles),
                'non_zero_tiles': tile_stats['non_zero']
            }
        })
        
        # Validate and fix tiles using the validation system
        validation_result = validate_tile_array(tiles)
        if not validation_result['valid']:
            logger.warning(f"⚠️ PLO_BOARDPACKET: Tile validation failed - {validation_result.get('error', 'Unknown error')}")
            tiles = fix_tile_array(tiles, clamp=True)
            logger.info(f"🔧 PLO_BOARDPACKET: Applied fixes to tile array")
        
        # Log comprehensive tile statistics
        log_tile_statistics(tiles, "PLO_BOARDPACKET")
        
        if first_10_tiles:
            logger.debug(f"🔍 First non-zero tiles: {', '.join(first_10_tiles)}")
        
        return {
            'tiles': tiles,  # Flat array for unified format
            'width': width,
            'height': height,
            'data_size': len(board_data),
            'statistics': tile_stats,
            'board_info': board_info,
            'events': events_to_emit
        }
        
    except Exception as e:
        logger.error(f"Error parsing board data: {e}")
        import traceback
        traceback.print_exc()
        # Return empty level on error
        return {
            'tiles': [0] * 4096,  # Flat array of 4096 zeros
            'width': 64,
            'height': 64,
            'data_size': 0,
            'error': str(e),
            'events': []
        }

# Keep the old function for backward compatibility
def parse_board_data(board_data: bytes) -> Dict[str, Any]:
    """
    Legacy function - calls the new parse() function for compatibility.
    """
    return parse({'board_data': board_data})

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BOARDPACKET packet from raw bytes using registry format"""
    logger.debug(f"🔍 PLO_BOARDPACKET parse_packet called with {len(data)} bytes")
    if len(data) > 0:
        # Log first 50 bytes to debug
        preview = ' '.join(f'{b:02x}' for b in data[:min(50, len(data))])
        logger.debug(f"🔍 First bytes: {preview}")
    
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BOARDPACKET.packet_id,
        'packet_name': PLO_BOARDPACKET.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BOARDPACKET.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply full business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
        if 'error' not in parsed_data:
            logger.debug(f"PLO_BOARDPACKET: {parsed_data.get('statistics', {}).get('non_zero', 0)} non-zero tiles")
    else:
        logger.warning("PLO_BOARDPACKET has no parsed data")
    
    return result