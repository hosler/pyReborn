"""
Game Constants
"""

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)

# UI Colors
UI_BG = (20, 20, 30, 200)
UI_BORDER = (100, 100, 120)
UI_TEXT = (200, 200, 220)
UI_HIGHLIGHT = (100, 150, 200)
UI_ACCENT = (255, 200, 100)

# Game States
STATE_MENU = "menu"
STATE_CONNECTING = "connecting"
STATE_LOADING = "loading"  # New state: waiting for initial game data after login
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"

# Layers
LAYER_GROUND = 0
LAYER_OBJECTS = 1
LAYER_PLAYERS = 2
LAYER_EFFECTS = 3
LAYER_UI = 4

# Physics
PLAYER_SPEED = 4.0  # Tiles per second
ANIMATION_SPEED = 0.1  # Seconds per frame

# Network
MOVEMENT_SEND_RATE = 0.05  # Send movement every 50ms max
PROPERTY_SEND_RATE = 0.1   # Send property updates every 100ms max

# Debug
DEBUG_FONT_SIZE = 14
DEBUG_MARGIN = 10