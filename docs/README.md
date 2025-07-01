# PyReborn Documentation

This directory contains technical documentation for the PyReborn client library.

## Available Documentation

### [GRAAL_PROTOCOL_GUIDE.md](GRAAL_PROTOCOL_GUIDE.md)
Comprehensive guide to the Graal Reborn protocol implementation including:
- Connection setup and encryption
- Packet structure and encoding
- Login process
- Player properties and chat system
- Complete packet reference

## Quick References

### Basic API Usage
```python
from pyreborn.client import RebornClient

client = RebornClient("localhost", 14900)
if client.connect() and client.login("username", "password"):
    # Basic actions
    client.set_nickname("MyBot")
    client.set_chat("Hello!")
    client.move_to(30, 30)
    
    # Event handling
    client.events.subscribe('player_moved', my_handler)
    
    # Level data
    level = client.level_manager.get_current_level()
    tiles = level.get_board_tiles_array()  # 64x64 tile array
    
    client.disconnect()
```

### Event System
```python
def on_player_moved(event):
    player = event.get('player')
    print(f"Player {player.name} moved to ({player.x}, {player.y})")

def on_player_chat(event):
    player = event.get('player')
    message = event.get('message')
    print(f"{player.name}: {message}")

client.events.subscribe('player_moved', on_player_moved)
client.events.subscribe('player_chat', on_player_chat)
```

### Level Data Access
```python
level = client.level_manager.get_current_level()

# Get tile data
tiles_1d = level.get_board_tiles_array()  # Flat array [0..4095]
tiles_2d = level.get_board_tiles_2d()     # 2D array [y][x]
tile_id = level.get_board_tile_id(x, y)   # Single tile

# Convert tile ID to tileset coordinates
tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
# tx, ty = tile position in tileset
# px, py = pixel position in tileset (tx*16, ty*16)
```

## Examples

Complete working examples are available in the [examples/](../examples/) directory:

- **Basic Bot** - Simple movement and chat
- **Follower Bot** - Follows and mimics target player  
- **Level Snapshot** - Creates PNG images of levels using tileset graphics
- **Player Tracker** - Monitors and logs player activity

## Protocol Details

The Graal protocol uses:
- **ENCRYPT_GEN_5**: XOR-based partial packet encryption
- **+32 Encoding**: All bytes offset by 32 to avoid control characters
- **Compression**: UNCOMPRESSED (≤55 bytes), ZLIB (>55 bytes), optional BZ2
- **Board Data**: 8192 bytes representing 64×64 tiles (2 bytes per tile)
- **Rate Limiting**: 50ms minimum interval between sends to prevent desync

## Architecture

PyReborn follows an event-driven architecture:
1. **RebornClient** - Main API interface
2. **Protocol Layer** - Packet encoding/decoding with encryption
3. **Event System** - Pub/sub pattern for game events
4. **Managers** - SessionManager and LevelManager for state
5. **Threading** - Separate send/receive threads with queues

For more technical details, see the protocol guide and source code.