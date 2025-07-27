# PyReborn

A pure Python client library for connecting to Reborn servers. PyReborn provides a complete implementation of the Reborn protocol with a modern v2 architecture, allowing you to create bots, automation tools, and custom clients.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Features

- 🚀 **Pure Python** - No external dependencies, just standard library
- 🔐 **Full Protocol Support** - Complete implementation including ENCRYPT_GEN_5 encryption
- 🎮 **Event-Driven Architecture** - React to game events with simple callbacks
- 🧩 **Modern v2 Architecture** - Clean, maintainable codebase with proper packet handling
- 📦 **Type Hints** - Full type annotation support
- 🎯 **High-Level API** - Simple methods for movement, chat, and game actions
- 🗺️ **Level Management** - Parse and interact with game levels including GMAP support
- 🤖 **Bot-Friendly** - Designed specifically for creating game bots
- 📁 **File Transfer** - Download and process tilesets and other game assets

## Installation

### From PyPI (when published)
```bash
pip install pyreborn
```

### From Source
```bash
git clone https://github.com/yourusername/pyreborn.git
cd pyreborn
pip install -e .
```

### Development Installation
```bash
pip install -e ".[dev]"
```

## Quick Start

### Basic Connection
```python
from pyreborn import RebornClient

# Connect to server
client = RebornClient("localhost", 14900)
if client.connect() and client.login("username", "password"):
    print("Connected!")
    
    # Set your appearance
    client.set_nickname("MyBot")
    client.set_chat("Hello, world!")
    
    # Move around
    client.move_to(30, 30)
    
    # Stay connected for a bit
    import time
    time.sleep(5)
    
    client.disconnect()
```

### Event Handling
```python
from pyreborn import RebornClient

client = RebornClient("localhost", 14900)

# Subscribe to events
def on_player_moved(event):
    player = event['player']
    print(f"{player.name} moved to ({player.x}, {player.y})")

def on_chat(event):
    player = event['player']
    message = event['message']
    print(f"{player.name}: {message}")

client.events.subscribe('player_moved', on_player_moved)
client.events.subscribe('player_chat', on_chat)

# Connect and run
if client.connect() and client.login("bot", "password"):
    # Keep running until disconnected
    while client.connected:
        time.sleep(0.1)
```

## Core Concepts

### The Client
The `RebornClient` is your main interface to the game server. It handles:
- Connection management
- Authentication
- Packet encoding/decoding
- Event dispatching
- Game state management

### Events
PyReborn uses an event-driven architecture. Common events include:
- `player_joined` - A player entered the level
- `player_left` - A player left the level
- `player_moved` - A player moved
- `player_chat` - A player sent a chat message
- `level_changed` - You entered a new level
- `private_message` - You received a PM

### Players
Player objects represent other players in the game:
```python
player.name      # Account name
player.nickname  # Display name
player.x, player.y  # Position
player.level     # Current level
player.hearts    # Health
```

### Levels
Level objects provide access to tile data:
```python
level = client.level_manager.get_current_level()
tiles = level.get_board_tiles_array()  # Flat array of tile IDs
tiles_2d = level.get_board_tiles_2d()  # 2D array [y][x]
```

## Example Bots

### Echo Bot
Repeats everything said in chat:
```python
from pyreborn import RebornClient

client = RebornClient("localhost", 14900)

def on_chat(event):
    message = event['message']
    client.set_chat(f"Echo: {message}")

client.events.subscribe('player_chat', on_chat)

if client.connect() and client.login("echobot", "password"):
    client.set_nickname("EchoBot")
    while client.connected:
        time.sleep(0.1)
```

### Follow Bot
Follows a specific player:
```python
from pyreborn import RebornClient
import time

client = RebornClient("localhost", 14900)
target_player = "PlayerName"

def on_player_moved(event):
    player = event['player']
    if player.name == target_player:
        # Move to their position with slight offset
        client.move_to(player.x + 1, player.y)

client.events.subscribe('player_moved', on_player_moved)

if client.connect() and client.login("followbot", "password"):
    client.set_nickname("FollowBot")
    while client.connected:
        time.sleep(0.1)
```

### Patrol Bot
Patrols between waypoints:
```python
from pyreborn import RebornClient
import time
import threading

client = RebornClient("localhost", 14900)

waypoints = [(30, 30), (40, 30), (40, 40), (30, 40)]
current_waypoint = 0

def patrol():
    global current_waypoint
    while client.connected:
        target = waypoints[current_waypoint]
        client.move_to(target[0], target[1])
        current_waypoint = (current_waypoint + 1) % len(waypoints)
        time.sleep(3)

if client.connect() and client.login("patrolbot", "password"):
    client.set_nickname("PatrolBot")
    
    # Start patrol in background
    patrol_thread = threading.Thread(target=patrol)
    patrol_thread.daemon = True
    patrol_thread.start()
    
    while client.connected:
        time.sleep(0.1)
```

## Advanced Usage

### Custom Packet Handlers
```python
from pyreborn import RebornClient

class CustomClient(RebornClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def handle_custom_packet(self, packet):
        # Handle your custom packet type
        pass
```

### Level Analysis
```python
# Get current level
level = client.level_manager.get_current_level()

# Access tile data
for y in range(64):
    for x in range(64):
        tile_id = level.get_tile_at(x, y)
        if tile_id > 0:  # Non-empty tile
            # Convert to tileset coordinates
            tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
            print(f"Tile at ({x},{y}) uses tileset tile ({tx},{ty})")

# Find all players on current level
for player in client.session_manager.get_players_on_level(level.name):
    print(f"{player.name} is at ({player.x}, {player.y})")
```

### Threading and Async
```python
import threading

def background_task(client):
    while client.connected:
        # Do something periodically
        client.set_chat("Still running!")
        time.sleep(10)

# Start background task
thread = threading.Thread(target=background_task, args=(client,))
thread.daemon = True
thread.start()
```

## API Reference

### RebornClient

#### Connection Methods
- `connect() -> bool` - Connect to server
- `disconnect()` - Disconnect from server
- `login(account: str, password: str) -> bool` - Authenticate
- Keep connection alive with `while client.connected: time.sleep(0.1)`

#### Player Actions
- `move(dx: float, dy: float)` - Move relative to current position
- `move_to(x: float, y: float)` - Move to absolute position
- `set_chat(message: str)` - Set chat bubble
- `set_nickname(nickname: str)` - Set display name
- `say(message: str)` - Send chat message

#### Combat Actions
- `take_bomb()` - Pick up a bomb
- `take_bow()` - Pick up a bow  
- `take_sword()` - Pick up a sword
- `throw_bomb()` - Throw a bomb
- `shoot_arrow()` - Shoot an arrow

#### Game Actions
- `warp_to(x: float, y: float, level: str)` - Warp to level
- `play_sound(filename: str)` - Play a sound effect
- `set_player_prop(prop_id: int, value)` - Set player property

### EventManager

- `subscribe(event_name: str, handler: Callable)` - Subscribe to event
- `unsubscribe(event_name: str, handler: Callable)` - Unsubscribe
- `emit(event_name: str, data: dict)` - Emit an event

### Common Events

| Event | Data | Description |
|-------|------|-------------|
| `connected` | `{}` | Connected to server |
| `login_success` | `{}` | Login successful |
| `player_joined` | `{player}` | Player joined level |
| `player_left` | `{player}` | Player left level |
| `player_moved` | `{player, old_x, old_y}` | Player moved |
| `player_chat` | `{player, message}` | Chat message |
| `level_changed` | `{old_level, new_level}` | Changed levels |
| `private_message` | `{from_player, message}` | Received PM |

## Examples Directory

The `examples/` directory contains many more examples:

- `bots/` - Fun and useful bots
  - `echo_bot.py` - Repeats chat messages
  - `follow_bot.py` - Follows players
  - `patrol_bot.py` - Patrols waypoints
  - `guard_bot.py` - Guards an area
  - `trader_bot.py` - Simple trading system
  - `quest_bot.py` - Gives quests
  - `dance_bot.py` - Dances around

- `games/` - Mini-games and interactive examples  
  - `pygame_client.py` - Full Pygame client
  - `tag_game.py` - Play tag with bots
  - `maze_solver.py` - Solves mazes

- `utilities/` - Useful tools
  - `server_monitor.py` - Monitor server activity
  - `player_tracker.py` - Track player movements
  - `level_mapper.py` - Generate level maps
  - `chat_logger.py` - Log all chat

- `advanced/` - Advanced examples
  - `multi_bot_coordinator.py` - Coordinate multiple bots
  - `custom_protocol.py` - Extend the protocol
  - `plugin_system.py` - Plugin architecture

## Troubleshooting

### Connection Issues
- Ensure server is running: `docker-compose ps`
- Check server logs: `docker-compose logs -f reborn-server`
- Verify credentials in `CLAUDE.md`

### Encryption Desync
- The client maintains 50ms rate limiting to prevent desync
- Don't send packets too quickly
- Let the client handle rate limiting

### Missing Players
- Players may be on different levels
- Use `session_manager.get_all_players()` for all online players
- Subscribe to `player_joined`/`player_left` events

## Development

### Running Tests
```bash
pytest
```

### Code Style
```bash
black pyreborn/
flake8 pyreborn/
mypy pyreborn/
```

### Building
```bash
python -m build
```

## Architecture

PyReborn follows a layered architecture:

1. **Network Layer** - Raw socket communication
2. **Protocol Layer** - Packet encoding/decoding, encryption
3. **Session Layer** - Connection state, authentication
4. **Game Layer** - Players, levels, game state
5. **API Layer** - High-level client methods
6. **Event Layer** - Event system for extensibility

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Reborn team for the server implementation
- Original developers for the protocol
- Community members who documented the protocol

## Resources

- [Reborn](https://www.reborn.com/)
- [Protocol Documentation](https://github.com/xtjoeytx/reborn-serverlist/wiki)
- [Reborn Server Source](https://github.com/xtjoeytx/RebornServer-v2)