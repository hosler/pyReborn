# PyReborn

A Python client library for connecting to GServer (Graal Reborn) servers. Pure client implementation focused on server communication, level data handling, and game state management - designed for building bots and automation tools.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- 🔐 **ENCRYPT_GEN_5 support** - XOR-based stream cipher encryption
- 🎮 **Event-driven architecture** - Real-time player and level tracking
- 💬 **Full chat system** - Chat bubbles, messages, and communication
- 🗺️ **Level data parsing** - 64x64 tile arrays with tileset coordinate conversion
- 🤖 **Bot framework** - Easy-to-use API for automation and bot creation
- 📦 **Packet handling** - Complete Graal protocol implementation
- 🧵 **Multi-threaded** - Separate threads for sending/receiving with rate limiting
- 📚 **Type annotations** - Full type hint support with py.typed marker

## Quick Start

### Installation

```bash
cd pyReborn
pip install -e ".[dev]"
```

### Basic Connection

```python
from pyreborn.client import RebornClient

# Create client
client = RebornClient("localhost", 14900)

# Connect and login
if client.connect() and client.login("username", "password"):
    print("✅ Connected successfully!")
    
    # Set appearance and chat
    client.set_nickname("PyBot")
    client.set_chat("Hello from PyReborn!")
    
    # Move around
    client.move_to(30.5, 25.0)
    
    # Keep connection alive
    import time
    time.sleep(10)
    
    client.disconnect()
```

## Examples

See the [examples/](examples/) directory for complete, working examples:

### Basic Bot (`examples/bots/basic_bot.py`)
```python
from pyreborn.client import RebornClient

client = RebornClient("localhost", 14900)
if client.connect() and client.login("basicbot", "1234"):
    client.set_nickname("BasicBot")
    client.set_chat("Hello, I'm a basic bot!")
    client.move_to(30, 30)
    client.disconnect()
```

### Follower Bot (`examples/bots/follower_bot.py`)
```python
# Follows a target player and mimics their actions
python examples/bots/follower_bot.py SpaceManSpiff
```

### Level Snapshot (`examples/utilities/level_snapshot.py`)
```python
# Creates PNG snapshots of levels using tileset graphics
from pyreborn.client import RebornClient

client = RebornClient("localhost", 14900)
client.connect() and client.login("snapshotbot", "1234")

# Get level and create snapshot
level = client.level_manager.get_current_level()
tiles = level.get_board_tiles_array()  # 64x64 tile array
# ... render using tileset coordinates
```

### Player Tracker (`examples/utilities/player_tracker.py`)
```python
# Monitors and logs all player activity
python examples/utilities/player_tracker.py output.json
```

## Protocol Documentation

For detailed protocol implementation, see [GRAAL_PROTOCOL_GUIDE.md](docs/GRAAL_PROTOCOL_GUIDE.md).

### Key Protocol Features

- **ENCRYPT_GEN_5**: Partial packet encryption (first X bytes only)
- **Compression**: UNCOMPRESSED, ZLIB, BZ2 support
- **Packet Streaming**: Multiple packets per TCP read
- **Player Properties**: 80+ different property types
- **Real-time Updates**: Position, chat, actions, level changes

## API Reference

### RebornClient

Main client class for connecting to GServer.

```python
class RebornClient:
    def __init__(self, host: str, port: int = 14900)
    def connect() -> bool
    def login(account: str, password: str) -> bool
    def disconnect()
    
    # Movement
    def move_to(x: float, y: float)
    
    # Chat & Communication
    def set_chat(message: str)  # Chat bubble
    
    # Appearance
    def set_nickname(nickname: str)
    def set_body_image(image: str)
    def set_head_image(image: str)
    
    # Events
    events: EventManager  # Use events.subscribe(event_name, handler)
    
    # Managers
    level_manager: LevelManager
    session_manager: SessionManager
```

### Level Data

```python
class Level:
    name: str
    board_tiles_64x64: List[int]  # 4096 tile IDs (64x64)
    
    def get_board_tiles_array() -> List[int]
    def get_board_tiles_2d() -> List[List[int]]
    def get_board_tile_id(x: int, y: int) -> int
    
    @staticmethod
    def tile_to_tileset_coords(tile_id: int) -> Tuple[int, int, int, int]
        # Returns: (tx, ty, px, py) - tile coords and pixel coords
```

### Event System

```python
# Subscribe to events
client.events.subscribe('player_moved', my_handler)
client.events.subscribe('player_chat', my_handler)
client.events.subscribe('level_changed', my_handler)

# Event handlers receive event dict
def my_handler(event):
    player = event.get('player')
    message = event.get('message')
```

## Requirements

- Python 3.8+
- No external dependencies (uses only standard library)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Testing

```bash
# Run tests
pytest

# Basic connection test
python examples/test_connection.py

# Example bots
python examples/bots/basic_bot.py
python examples/bots/follower_bot.py SpaceManSpiff

# Utilities
python examples/utilities/level_snapshot.py
python examples/utilities/player_tracker.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- GServer development team for the original protocol
- OpenGraal community for protocol documentation
- Contributors to protocol reverse engineering efforts

## Troubleshooting

### Common Issues

**Connection fails:**
- Check server address and port
- Ensure server is running and accessible
- Verify firewall settings

**Login timeout:**
- Check username/password
- Verify account exists on server
- Check for server-side login restrictions

**Broken pipe errors:**
- Ensure login completes before sending actions
- Check encryption setup
- Verify packet format

**Can't see other players:**
- Check if players are in same level
- Verify packet decryption is working
- Check player property parsing

For more help, see the [troubleshooting guide](docs/TROUBLESHOOTING.md) or open an issue.

---

**PyReborn** - Bringing Python to the Graal universe! 🐍⚔️