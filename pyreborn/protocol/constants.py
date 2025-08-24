"""
Protocol constants for PyReborn
"""

# Level dimensions
LEVEL_WIDTH = 64
LEVEL_HEIGHT = 64
LEVEL_TILES_COUNT = LEVEL_WIDTH * LEVEL_HEIGHT  # 4096

# Board data
BOARD_DATA_SIZE = LEVEL_TILES_COUNT * 2  # 8192 bytes (2 bytes per tile)
TILE_BYTES = 2

# GMAP segment size (each segment is one level)
GMAP_SEGMENT_SIZE = LEVEL_WIDTH  # 64 tiles per segment

# File types
GMAP_FILE_EXTENSION = '.gmap'
LEVEL_FILE_EXTENSION = '.nw'
TILESET_FILE_EXTENSION = '.png'

# Default values
DEFAULT_TILESET = 'pics1.png'
DEFAULT_HEALTH = 3.0

# Base64 encoding for tiles (standard Reborn encoding)
BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

# Protocol magic strings
LEVEL_FILE_HEADER = b'GLEVNW01'
LEVEL_FILE_MAGIC = b'GRLV'

# Text command prefixes  
BOARD_COMMAND = "BOARD"