#!/usr/bin/env python3
"""
Tile ID validation utilities for pyReborn.

This module provides validation functions for tile IDs to ensure they are
within expected ranges and detect potential parsing issues.
"""

import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Standard Reborn tile ID ranges
MIN_TILE_ID = 0
MAX_TILE_ID = 4095  # Standard 12-bit tile ID range (0-4095)
SPECIAL_TILE_RANGES = {
    'walkable': (0, 511),      # Grass, dirt, etc.
    'blocking': (512, 1023),   # Walls, trees, etc.
    'water': (1024, 1535),     # Water tiles
    'special': (1536, 4095)    # Special tiles, decorations, etc.
}


def validate_tile_id(tile_id: int) -> Tuple[bool, str]:
    """
    Validate a single tile ID.
    
    Args:
        tile_id: The tile ID to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(tile_id, int):
        return False, f"Tile ID must be integer, got {type(tile_id)}"
    
    if tile_id < MIN_TILE_ID:
        return False, f"Tile ID {tile_id} below minimum {MIN_TILE_ID}"
    
    if tile_id > MAX_TILE_ID:
        return False, f"Tile ID {tile_id} above maximum {MAX_TILE_ID}"
    
    return True, ""


def clamp_tile_id(tile_id: int) -> int:
    """
    Clamp a tile ID to the valid range.
    
    Args:
        tile_id: The tile ID to clamp
        
    Returns:
        Clamped tile ID in valid range
    """
    if tile_id < MIN_TILE_ID:
        return MIN_TILE_ID
    elif tile_id > MAX_TILE_ID:
        return tile_id & 0xFFF  # Keep only lower 12 bits
    else:
        return tile_id


def categorize_tile(tile_id: int) -> str:
    """
    Categorize a tile ID based on standard Reborn ranges.
    
    Args:
        tile_id: The tile ID to categorize
        
    Returns:
        Category name ('walkable', 'blocking', 'water', 'special', 'invalid')
    """
    if tile_id < MIN_TILE_ID or tile_id > MAX_TILE_ID:
        return 'invalid'
    
    for category, (min_val, max_val) in SPECIAL_TILE_RANGES.items():
        if min_val <= tile_id <= max_val:
            return category
    
    return 'unknown'


def validate_tile_array(tiles: List[int], expected_size: int = 4096) -> Dict[str, Any]:
    """
    Validate an array of tile IDs.
    
    Args:
        tiles: List of tile IDs to validate
        expected_size: Expected number of tiles (default 4096 for 64x64)
        
    Returns:
        Dictionary with validation results and statistics
    """
    if not isinstance(tiles, list):
        return {
            'valid': False,
            'error': f"Tiles must be a list, got {type(tiles)}",
            'statistics': {}
        }
    
    if len(tiles) != expected_size:
        logger.warning(f"Unexpected tile array size: {len(tiles)} vs expected {expected_size}")
    
    stats = {
        'total': len(tiles),
        'valid': 0,
        'invalid': 0,
        'non_zero': 0,
        'categories': {category: 0 for category in SPECIAL_TILE_RANGES.keys()},
        'out_of_range': []
    }
    
    for i, tile_id in enumerate(tiles):
        is_valid, error_msg = validate_tile_id(tile_id)
        
        if is_valid:
            stats['valid'] += 1
            if tile_id > 0:
                stats['non_zero'] += 1
                category = categorize_tile(tile_id)
                if category in stats['categories']:
                    stats['categories'][category] += 1
        else:
            stats['invalid'] += 1
            if len(stats['out_of_range']) < 10:  # Limit logged invalid tiles
                stats['out_of_range'].append((i, tile_id, error_msg))
    
    # Calculate percentages
    if stats['total'] > 0:
        stats['valid_percentage'] = (stats['valid'] / stats['total']) * 100
        stats['density'] = (stats['non_zero'] / stats['total']) * 100
    else:
        stats['valid_percentage'] = 0
        stats['density'] = 0
    
    result = {
        'valid': stats['invalid'] == 0,
        'statistics': stats
    }
    
    if stats['invalid'] > 0:
        result['error'] = f"Found {stats['invalid']} invalid tile IDs"
        logger.warning(f"Tile validation: {stats['invalid']} invalid tiles out of {stats['total']}")
        for i, tile_id, error_msg in stats['out_of_range'][:5]:  # Log first 5
            logger.warning(f"  Invalid tile at index {i}: {error_msg}")
    
    return result


def fix_tile_array(tiles: List[int], clamp: bool = True) -> List[int]:
    """
    Fix an array of tile IDs by clamping or removing invalid values.
    
    Args:
        tiles: List of tile IDs to fix
        clamp: If True, clamp invalid tiles; if False, set them to 0
        
    Returns:
        Fixed list of tile IDs
    """
    fixed_tiles = []
    fixes_applied = 0
    
    for tile_id in tiles:
        if isinstance(tile_id, int) and MIN_TILE_ID <= tile_id <= MAX_TILE_ID:
            fixed_tiles.append(tile_id)
        else:
            if clamp and isinstance(tile_id, int):
                fixed_tile = clamp_tile_id(tile_id)
                fixed_tiles.append(fixed_tile)
            else:
                fixed_tiles.append(0)  # Default to empty tile
            fixes_applied += 1
    
    if fixes_applied > 0:
        logger.info(f"Fixed {fixes_applied} invalid tile IDs")
    
    return fixed_tiles


def log_tile_statistics(tiles: List[int], source: str = "Unknown") -> None:
    """
    Log detailed statistics about a tile array.
    
    Args:
        tiles: List of tile IDs to analyze
        source: Source of the tiles (e.g., "PLO_BOARDPACKET", "NW Level")
    """
    validation = validate_tile_array(tiles)
    stats = validation['statistics']
    
    logger.info(f"🎯 {source} Tile Statistics:")
    logger.info(f"  Total tiles: {stats['total']}")
    logger.info(f"  Valid tiles: {stats['valid']} ({stats['valid_percentage']:.1f}%)")
    logger.info(f"  Non-zero tiles: {stats['non_zero']} ({stats['density']:.1f}% density)")
    
    if stats['invalid'] > 0:
        logger.warning(f"  Invalid tiles: {stats['invalid']}")
    
    # Log category breakdown
    for category, count in stats['categories'].items():
        if count > 0:
            percentage = (count / stats['non_zero']) * 100 if stats['non_zero'] > 0 else 0
            logger.info(f"  {category.capitalize()}: {count} ({percentage:.1f}%)")