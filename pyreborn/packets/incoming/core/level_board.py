#!/usr/bin/env python3
"""
PLO_LEVELBOARD (Packet 0) - Unknown level-related data

This packet's exact purpose is unclear. It was originally thought to contain
level tile data, but that appears to be in PLO_BOARDPACKET (101) instead.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, gshort_field, variable_data_field, PacketReader, parse_field
from typing import Dict, Any, List
import zlib
import logging

logger = logging.getLogger(__name__)


PLO_LEVELBOARD = PacketStructure(
    packet_id=0,
    name="PLO_LEVELBOARD",
    fields=[
        gshort_field("compressed_length", "Compressed data length"),
        variable_data_field("compressed_data", "Compressed level board data")
    ],
    description="Unknown level-related data (not tile data)",
    variable_length=True
)


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse level board data and return structured level information.
    
    Args:
        data: Raw packet data from registry parser containing:
            - compressed_length: Size of compressed data
            - compressed_data: Compressed level tile data
    
    Returns:
        Dictionary containing:
            - tiles: 2D list of tile IDs (64x64)
            - width: Level width in tiles (64)
            - height: Level height in tiles (64)
            - compressed_size: Original compressed size
            - uncompressed_size: Size after decompression
    """
    try:
        compressed_length = data.get('compressed_length', 0)
        compressed_data = data.get('compressed_data', b'')
        
        # Handle empty level board (0 bytes = empty level)
        if len(compressed_data) == 0:
            logger.debug("Empty level board data (0 bytes) - creating empty 64x64 grid")
            # Create empty 64x64 tile grid
            tiles = [[0 for _ in range(64)] for _ in range(64)]
            return {
                'tiles': tiles,
                'width': 64,
                'height': 64,
                'compressed_size': 0,
                'uncompressed_size': 0,
                'decompression_method': 'empty'
            }
        
        # Decompress the level data
        decompressed = None
        decompression_method = "unknown"
        
        # Try multiple decompression methods
        for method, (func, args, desc) in [
            ("standard", (zlib.decompress, (compressed_data,), "standard zlib")),
            ("no_header", (zlib.decompress, (compressed_data, -zlib.MAX_WBITS), "zlib without header")),
            ("raw_deflate", (zlib.decompress, (compressed_data, -15), "raw deflate")),
        ]:
            try:
                decompressed = func(*args)
                decompression_method = desc
                logger.debug(f"Successfully decompressed using {desc}: {len(compressed_data)} -> {len(decompressed)} bytes")
                break
            except zlib.error as e:
                logger.debug(f"Failed {desc} decompression: {e}")
                continue
        
        if decompressed is None:
            # If all decompression methods fail, treat as uncompressed data
            logger.debug(f"Treating {len(compressed_data)} bytes as uncompressed data")
            decompressed = compressed_data
            decompression_method = "uncompressed"
        
        # Convert to 2D tile array
        tiles = []
        width = 64
        height = 64
        expected_size = width * height * 2  # 2 bytes per tile
        
        if len(decompressed) >= expected_size:
            # Parse tiles as 16-bit values
            for y in range(height):
                row = []
                for x in range(width):
                    offset = (y * width + x) * 2
                    tile_id = int.from_bytes(decompressed[offset:offset+2], 'little')
                    row.append(tile_id)
                tiles.append(row)
        else:
            logger.debug(f"Decompressed level data smaller than expected: {len(decompressed)} < {expected_size} - creating empty level")
            # Create empty level
            tiles = [[0 for _ in range(width)] for _ in range(height)]
        
        return {
            'tiles': tiles,
            'width': width,
            'height': height,
            'compressed_size': compressed_length,
            'uncompressed_size': len(decompressed),
            'decompression_method': decompression_method
        }
        
    except Exception as e:
        logger.error(f"Error parsing level board data: {e}")
        # Return empty level on error
        return {
            'tiles': [[0 for _ in range(64)] for _ in range(64)],
            'width': 64,
            'height': 64,
            'compressed_size': 0,
            'uncompressed_size': 0,
            'error': str(e)
        }


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELBOARD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELBOARD.packet_id,
        'packet_name': PLO_LEVELBOARD.name,
        'fields': {}
    }
    
    # Parse the raw fields first
    for field in PLO_LEVELBOARD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply custom parsing logic
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
        tile_count = len(parsed_data.get('tiles', []))
        # Only log meaningful board data (non-empty)
        if tile_count > 64:  # More than empty placeholder
            logger.info(f"🎮 REGISTRY: PLO_LEVELBOARD parsed compressed data -> {tile_count} tiles")
    
    return result