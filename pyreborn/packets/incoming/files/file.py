#!/usr/bin/env python3
"""
PLO_FILE (Packet 102) - File transfer

This packet handles file transfers from server to client. It has a complex
structure that includes filename, modification time, and file data.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
try:
    from ...utils.tile_validation import validate_tile_array, fix_tile_array, log_tile_statistics
except ImportError:
    # Fallback import for when running directly
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
    from pyreborn.utils.tile_validation import validate_tile_array, fix_tile_array, log_tile_statistics
from typing import Dict, Any
import struct
import logging

logger = logging.getLogger(__name__)


def parse_base64_position(c: str) -> int:
    """Parse a single base64 character to its position value"""
    if 'a' <= c <= 'z':
        return 26 + (ord(c) - ord('a'))
    elif 'A' <= c <= 'Z':
        return (ord(c) - ord('A'))
    elif '0' <= c <= '9':
        return 52 + (ord(c) - ord('0'))
    elif c == '+':
        return 62
    elif c == '/':
        return 63
    return 0


def parse_nw_level_tiles(content: bytes) -> Dict[str, Any]:
    """
    Parse tiles from a .nw level file content.
    
    NW format uses base64 encoding for tiles in BOARD sections:
    BOARD x y width layer base64_tile_data
    
    Each tile is 2 base64 characters: left and top
    tile_id = (left_value << 6) + top_value
    """
    try:
        # Decode content as text
        text_content = content.decode('utf-8', errors='replace')
        lines = text_content.split('\n')
        
        # Initialize 64x64 tile grid
        tiles = [0] * (64 * 64)
        tiles_found = 0
        
        for line in lines:
            line = line.strip()
            if not line.startswith('BOARD'):
                continue
                
            parts = line.split()
            if len(parts) < 6:
                continue
                
            try:
                x = int(parts[1])
                y = int(parts[2])  
                width = int(parts[3])
                layer = int(parts[4])
                tile_data = parts[5]
                
                # Only process layer 0 for now
                if layer != 0:
                    continue
                    
                # Validate bounds
                if not (0 <= x < 64 and 0 <= y < 64 and width > 0 and x + width <= 64):
                    continue
                    
                # Parse tile data (2 chars per tile)
                if len(tile_data) >= width * 2:
                    for i in range(width):
                        if (i * 2 + 1) < len(tile_data):
                            left_char = tile_data[i * 2]
                            top_char = tile_data[i * 2 + 1]
                            
                            # Calculate tile ID using same formula as GServer
                            left_val = parse_base64_position(left_char)
                            top_val = parse_base64_position(top_char)
                            tile_id = (left_val << 6) + top_val
                            
                            # Store in tile array
                            tile_index = (y * 64) + (x + i)
                            if 0 <= tile_index < len(tiles):
                                tiles[tile_index] = tile_id
                                tiles_found += 1
                                
            except (ValueError, IndexError) as e:
                logger.debug(f"Error parsing BOARD line '{line}': {e}")
                continue
        
        # Validate tiles using the validation system
        validation_result = validate_tile_array(tiles)
        if not validation_result['valid']:
            logger.warning(f"⚠️ NW Level: Tile validation failed - {validation_result.get('error', 'Unknown error')}")
            tiles = fix_tile_array(tiles, clamp=True)
            logger.info(f"🔧 NW Level: Applied fixes to tile array")
        
        # Log comprehensive tile statistics
        log_tile_statistics(tiles, "NW Level File")
        
        return {
            'tiles': tiles,
            'width': 64,
            'height': 64,
            'format': 'nw_level',
            'tiles_found': tiles_found,
            'validation': validation_result
        }
        
    except Exception as e:
        logger.error(f"Error parsing NW level tiles: {e}")
        return {
            'tiles': [0] * (64 * 64),
            'width': 64,
            'height': 64,
            'format': 'nw_level',
            'error': str(e)
        }


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)

def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)

def byte_field(name: str, description: str) -> PacketField:
    """Helper to create a BYTE field"""
    return PacketField(name, PacketFieldType.BYTE, description=description)

def fixed_data_field_local(name: str, size: int, description: str) -> PacketField:
    """Helper to create a FIXED_DATA field"""
    return PacketField(name, PacketFieldType.FIXED_DATA, size=size, description=description)

PLO_FILE = PacketStructure(
    packet_id=102,
    name="PLO_FILE",
    fields=[
        fixed_data_field_local("header", 6, "PLO_FILE header bytes"),
        variable_data_field("file_data_with_filename", "Filename and file content (null-terminated filename + content)")
    ],
    description="File transfer packet with embedded filename",
    variable_length=True
)


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FILE packet using structured approach"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FILE.packet_id,
        'packet_name': PLO_FILE.name,
        'fields': {}
    }
    
    try:
        # Parse structured fields using the registry parser
        for field in PLO_FILE.fields:
            result['fields'][field.name] = parse_field(reader, field, announced_size)
        
        # Extract filename and content from the structured data
        header = result['fields'].get('header', b'')
        file_data_with_filename = result['fields'].get('file_data_with_filename', b'')
        
        # Parse the filename (null-terminated) and content
        null_pos = file_data_with_filename.find(b'\x00')
        if null_pos != -1:
            filename = file_data_with_filename[:null_pos].decode('utf-8', errors='replace')
            file_content = file_data_with_filename[null_pos + 1:]
        else:
            # Fallback: try to find where content starts by known headers
            filename = 'unknown'
            file_content = file_data_with_filename
            
            # Try to extract filename by finding known content headers
            for header_bytes in [b'GRMAP001', b'GLEVNW01', b'GLVLNW01', b'\x89PNG']:
                header_pos = file_data_with_filename.find(header_bytes)
                if header_pos > 0:
                    filename_part = file_data_with_filename[:header_pos]
                    try:
                        filename = filename_part.decode('utf-8', errors='replace').strip()
                        file_content = file_data_with_filename[header_pos:]
                        break
                    except:
                        continue
        
        logger.info(f"📦 PLO_FILE structured parse: '{filename}' ({len(file_content)} bytes)")
        
        # Create parsed_data for backward compatibility
        result['parsed_data'] = {
            'filename': filename,
            'content': file_content,
            'size': len(file_content),
            'content_valid': True,  # Assume valid since it's properly structured
            'parsing_method': 'structured'
        }
        
        # If this is a .nw level file, parse the tiles
        if filename.endswith('.nw') and len(file_content) > 0:
            logger.info(f"🎯 PLO_FILE: Detected .nw level file '{filename}', parsing tiles...")
            tile_data = parse_nw_level_tiles(file_content)
            result['parsed_data']['level_tiles'] = tile_data
            
            # Add tile statistics
            non_zero_tiles = sum(1 for tile in tile_data.get('tiles', []) if tile > 0)
            result['parsed_data']['tile_stats'] = {
                'total_tiles': len(tile_data.get('tiles', [])),
                'non_zero_tiles': non_zero_tiles,
                'tiles_found': tile_data.get('tiles_found', 0)
            }
            logger.info(f"🎮 Level '{filename}': {non_zero_tiles} non-zero tiles parsed")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in structured PLO_FILE parsing: {e}")
        # Fallback to old parsing method
        logger.warning("Falling back to content-based parsing")
        result['fields'] = {'file_data': data}
        parsed_data = parse_legacy(result['fields'])
        if parsed_data:
            result['parsed_data'] = parsed_data
        return result


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse function for backward compatibility - delegates to structured parsing"""
    # This function exists for compatibility with old code that calls parse() directly
    # The new parse_packet() function handles structured parsing
    logger.warning("Using deprecated parse() function - consider using parse_packet() directly")
    return parse_legacy(data)


def parse_legacy(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse file transfer packet and extract file information.
    
    PLO_FILE packets come wrapped in PLO_RAWDATA. The format appears to be:
    - Some bytes of garbage/obfuscation
    - The actual filename 
    - File content (starting with known headers like GLEVNW01)
    
    We use a simple approach: search for known file extensions and headers.
    
    Args:
        data: Raw packet data containing file transfer data
    
    Returns:
        Dictionary containing:
            - filename: Name of the file
            - content: File content bytes
            - size: Size of file content
    """
    try:
        file_data = data.get('file_data', b'')
        
        if not file_data or len(file_data) < 1:
            return {'error': 'Insufficient file data'}
        
        # Debug logging
        logger.debug(f"PLO_FILE raw data ({len(file_data)} bytes): {file_data[:50].hex()}")
        logger.debug(f"PLO_FILE as text preview: {repr(file_data[:100])}")
        
        # Convert to text for searching
        text_data = file_data.decode('latin-1', errors='replace')
        
        # Known file headers that indicate start of content (text-based)
        known_text_headers = ['GLEVNW01', 'GRMAP001', 'GLVLNW01', 'GANI0001']
        # Known binary headers
        known_binary_headers = [b'\x89PNG', b'GIF89a', b'GIF87a']
        
        filename = ""
        content_start = -1
        
        # Strategy: Find known extensions and extract filename, plus handle PNG files specially
        # The server seems to send: [garbage bytes][filename][file content]
        
        # Special handling for PNG files - look for PNG signature first
        png_signature_pos = file_data.find(b'\x89PNG')
        if png_signature_pos != -1:
            logger.debug(f"Found PNG signature at position {png_signature_pos}")
            # For PNG files, content starts at the PNG signature
            content_start = png_signature_pos
            
            # Still try to find filename before the PNG data
            pre_png_data = text_data[:png_signature_pos]
            for ext in ['.png', '.gif', '.jpg', '.jpeg']:
                ext_pos = pre_png_data.find(ext)
                if ext_pos != -1:
                    # Work backwards to find start of filename
                    start_pos = ext_pos
                    while start_pos > 0:
                        char = pre_png_data[start_pos - 1]
                        if char.isalnum() or char in '_-':
                            start_pos -= 1
                        else:
                            break
                    
                    potential_filename = pre_png_data[start_pos:ext_pos + len(ext)]
                    # Clean obfuscation patterns
                    if potential_filename.startswith('cuB') and len(potential_filename) > 4:
                        potential_filename = potential_filename[4:]
                    elif potential_filename.startswith('uB') and len(potential_filename) > 3:
                        potential_filename = potential_filename[3:]
                    
                    if potential_filename and (potential_filename[0].isalnum() or potential_filename[0] == '_'):
                        filename = potential_filename
                        logger.debug(f"Found PNG filename: {filename}")
                        break
        
        # Search for common extensions (skip if we already found PNG content)
        if content_start == -1:
            for ext in ['.nw', '.gmap', '.png', '.gif', '.reborn', '.gani']:
                ext_pos = text_data.find(ext)
                if ext_pos != -1:
                    # Work backwards to find start of filename
                    # Skip any non-filename characters that might be part of obfuscation
                    start_pos = ext_pos
                    while start_pos > 0:
                        char = text_data[start_pos - 1]
                        # Valid filename chars: alphanumeric, underscore, hyphen
                        if char.isalnum() or char in '_-':
                            start_pos -= 1
                        else:
                            break
                    
                    # Extract the filename
                    potential_filename = text_data[start_pos:ext_pos + len(ext)]
                    
                    # Check for common obfuscation patterns and clean them
                    # Pattern: &cuB[char] followed by filename
                    if potential_filename.startswith('cuB') and len(potential_filename) > 4:
                        # Skip the cuB and following char
                        potential_filename = potential_filename[4:]
                        logger.debug(f"Stripped cuB obfuscation, filename now: {potential_filename}")
                    elif potential_filename.startswith('uB') and len(potential_filename) > 3:
                        # Another variant: uB[char]
                        potential_filename = potential_filename[3:]
                        logger.debug(f"Stripped uB obfuscation, filename now: {potential_filename}")
                    
                    # Validate it looks like a real filename
                    if potential_filename and (potential_filename[0].isalnum() or potential_filename[0] == '_'):
                        filename = potential_filename
                        logger.debug(f"Found filename: {filename} at position {start_pos}")
                    
                    # Find where content starts (look for known headers)
                    if content_start == -1:  # Only search if not already found
                        # Check text headers
                        for header in known_text_headers:
                            header_pos = text_data.find(header)
                            if header_pos != -1:
                                content_start = header_pos
                                logger.debug(f"Found content header {header} at position {header_pos}")
                                break
                        
                        # Check binary headers if no text header found
                        if content_start == -1:
                            for header in known_binary_headers:
                                header_pos = file_data.find(header)
                                if header_pos != -1:
                                    content_start = header_pos
                                    logger.debug(f"Found binary header {header} at position {header_pos}")
                                    break
                    
                    # If no header found, content starts after filename
                    if content_start == -1:
                        # Look for the filename in the data and content starts right after
                        filename_end = ext_pos + len(ext)
                        content_start = filename_end
                        logger.debug(f"No header found, content starts at {content_start}")
                    
                    break
        
        # Extract content
        if content_start != -1:
            content = file_data[content_start:]
        else:
            # Fallback: if we found a filename but no clear content start,
            # assume content is everything after the filename
            if filename:
                filename_pos = text_data.find(filename)
                if filename_pos != -1:
                    content_start = filename_pos + len(filename)
                    content = file_data[content_start:]
                else:
                    content = b''
            else:
                # No filename found at all
                content = file_data
        
        # Clean up the filename
        filename = filename.strip()
        
        # Validate extracted content
        content_valid = True
        if filename.endswith('.png') and len(content) > 8:
            if not content.startswith(b'\x89PNG'):
                logger.warning(f"PNG file {filename} doesn't start with PNG signature")
                content_valid = False
        elif filename.endswith('.gif') and len(content) > 6:
            if not content.startswith(b'GIF89a') and not content.startswith(b'GIF87a'):
                logger.warning(f"GIF file {filename} doesn't start with GIF signature")
                content_valid = False
        elif filename.endswith('.nw') and len(content) > 8:
            if not content.startswith(b'GLEVNW01') and not content.startswith(b'GLVLNW01'):
                logger.warning(f"NW file {filename} doesn't start with expected NW header")
                content_valid = False
        
        logger.debug(f"Parsed PLO_FILE: filename='{filename}', data_size={len(content)}, valid={content_valid}")
        if len(content) > 0:
            logger.debug(f"Content starts with: {content[:min(32, len(content))].hex()}")
        
        result = {
            'filename': filename if filename else 'unknown',
            'content': content,
            'size': len(content),
            'content_valid': content_valid,
            'content_start_pos': content_start
        }
        
        # If this is a .nw level file, parse the tiles for immediate use
        if filename.endswith('.nw') and len(content) > 0:
            logger.info(f"🎯 PLO_FILE: Detected .nw level file '{filename}', parsing tiles...")
            tile_data = parse_nw_level_tiles(content)
            result['level_tiles'] = tile_data
            
            # Add tile statistics for debugging
            non_zero_tiles = sum(1 for tile in tile_data.get('tiles', []) if tile > 0)
            result['tile_stats'] = {
                'total_tiles': len(tile_data.get('tiles', [])),
                'non_zero_tiles': non_zero_tiles,
                'tiles_found': tile_data.get('tiles_found', 0)
            }
            logger.info(f"🎮 Level '{filename}': {non_zero_tiles} non-zero tiles parsed")
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing file packet: {e}")
        return {'error': str(e)}