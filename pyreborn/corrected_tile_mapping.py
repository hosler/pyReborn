"""
Corrected Server Tile ID to Tileset Position Mapping
Based on real server data analysis
"""

# Start with the most critical mappings we know for sure
CORRECTED_SERVER_TILE_MAPPING = {
    # Tile 2047 is grass (39.7% of level) - should be at grass position
    2047: (0, 0),  # Grass - most common tile
    
    # Tile 192 is also grass (position 0,0 should be grass per user)
    192: (0, 0),   # Grass - same as 2047
    193: (1, 0),   # Likely grass variant (adjacent to 192)
    
    # Water tiles (from bottom area analysis) - try water section around row 12-14
    322: (0, 12),  # Primary water tile (312 times, bottom area)
    398: (1, 12),  # Secondary water tile (119 times, bottom area) 
    323: (2, 12),  # Water variant
    324: (3, 12),  # Water variant
    338: (4, 12),  # Water variant
    469: (0, 13),  # Water variant
    470: (1, 13),  # Water variant
    485: (2, 13),  # Water variant
    486: (3, 13),  # Water variant
    
    # Terrain tiles (from stone area analysis)
    0: (0, 8),     # Stone/concrete (164 times)
    1: (1, 8),     # Stone/concrete (161 times)
    48: (2, 8),    # Stone/concrete (152 times)
    49: (3, 8),    # Stone/concrete (152 times)
    16: (8, 0),    # Terrain (1.2%)
    2: (9, 0),     # Basic terrain
    3: (10, 0),    # Basic terrain
    18: (11, 0),   # Terrain
    19: (12, 0),   # Terrain
    
    # More tiles based on pattern from debug data
    11: (13, 0),   # AL
    12: (14, 0),   # AM
    13: (15, 0),   # AN
    14: (16, 0),   # AO
    24: (17, 0),   # AY
    25: (18, 0),   # AZ
}

def get_corrected_tile_position(tile_id):
    """Get corrected tileset position for a server tile ID"""
    if tile_id in CORRECTED_SERVER_TILE_MAPPING:
        return CORRECTED_SERVER_TILE_MAPPING[tile_id]
    
    # For unknown tiles, fall back to a safe default or use old algorithm
    # This is temporary until we map all tiles properly
    if tile_id < 2048:
        # First half - use row-based mapping
        x = tile_id % 64
        y = tile_id // 64
        return (x, y)
    else:
        # Second half - offset to right side of tileset
        tile_id_offset = tile_id - 2048
        x = 64 + (tile_id_offset % 64)
        y = tile_id_offset // 64
        return (x, y)