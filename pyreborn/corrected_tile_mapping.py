"""
Corrected Server Tile ID to Tileset Position Mapping
Based on the proper server to tileset conversion algorithm
"""

def get_corrected_tile_position(tile_id):
    """Get corrected tileset position for a server tile ID
    
    The server stores tiles as indices 0-4095 (64x64 grid)
    The tileset image is arranged as 128x32 tiles
    
    Algorithm:
    - tx = Math.floor(index / 512)*16 + index % 16
    - ty = Math.floor(index / 16) % 32
    
    Where index is the server tile ID (0-4095)
    """
    if tile_id < 0 or tile_id >= 4096:
        return (0, 0)  # Default to first tile for invalid IDs
    
    # Apply the conversion algorithm
    tx = (tile_id // 512) * 16 + (tile_id % 16)
    ty = (tile_id // 16) % 32
    
    return (tx, ty)


# Create reverse mapping for tileset position to server tile ID
def get_server_tile_id_from_tileset(tx, ty):
    """Convert tileset position back to server tile ID
    
    This is the reverse of the above algorithm.
    We need to find which server tile ID maps to this tileset position.
    """
    # Since the mapping isn't 1-to-1, we need to iterate through all possible
    # server tile IDs and find which one maps to this position
    for tile_id in range(4096):
        if get_corrected_tile_position(tile_id) == (tx, ty):
            return tile_id
    return 0  # Default to 0 if no mapping found


# For backwards compatibility with existing code
CORRECTED_SERVER_TILE_MAPPING = {}

# Pre-generate the mapping for common tiles if needed
# This is optional but can speed up lookups for frequently used tiles
for tile_id in range(4096):
    CORRECTED_SERVER_TILE_MAPPING[tile_id] = get_corrected_tile_position(tile_id)