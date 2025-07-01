# PyReborn Examples

This directory contains example scripts demonstrating PyReborn functionality.

## Feature Demonstrations

### feature_demo.py
Comprehensive demonstration of all PyReborn features:
- Connection and authentication
- Movement patterns and positioning
- Chat bubble system
- Appearance customization (heads, bodies, nickname)
- Event handling system demonstration
- Level data access and tile information
- Player tracking and session management
- Tileset coordinate conversion

**Usage:**
```bash
cd examples
python feature_demo.py
```

### interactive_demo.py
Interactive bot that responds to player commands:
- **Commands**: help, follow me, stop, dance, stats
- **Movement patterns**: circle, square, random
- **Tile inspection**: Check tile IDs at coordinates
- **Chat responses**: Responds to greetings and mentions
- **Real-time following**: Follows players who request it

**Usage:**
```bash
cd examples
python interactive_demo.py
```

**In-game commands:**
- `help` - Show all available commands
- `follow me` - Bot will follow you around
- `move circle` - Move in a circle pattern
- `dance` - Perform a dance animation
- `tile 30,30` - Check tile at coordinates

## Bots

### basic_bot.py
Demonstrates fundamental PyReborn features:
- Connecting and logging in
- Moving around the level
- Setting nickname and chat messages

**Usage:**
```bash
cd examples/bots
python basic_bot.py
```

### follower_bot.py
Advanced bot that follows a target player and mimics their actions:
- Follows player movement
- Copies chat messages
- Mimics appearance changes
- Handles level changes

**Usage:**
```bash
cd examples/bots
python follower_bot.py <target_player_name>
```

**Example:**
```bash
python follower_bot.py SpaceManSpiff
```

## Utilities

### level_snapshot.py
Creates PNG snapshots of Graal levels using actual tileset graphics:
- Downloads level board data
- Renders using Pics1formatwithcliffs.png tileset
- Provides level statistics
- Saves 1024x1024 pixel images

**Usage:**
```bash
cd examples/utilities
python level_snapshot.py [output_name]
```

**Requirements:**
- PIL/Pillow: `pip install Pillow`
- Pics1formatwithcliffs.png in project root

### player_tracker.py
Monitors and logs all player activity in real-time:
- Tracks player joins/leaves
- Logs movement and chat
- Provides session summaries
- Saves data to JSON

**Usage:**
```bash
cd examples/utilities
python player_tracker.py [output_file.json]
```

## Legacy Examples

The `examples/` root directory contains older examples for reference:
- `test_connection.py` - Basic connection test
- `simple_demo.py` - Simple client demonstration

## Running Examples

1. Make sure PyReborn is installed:
   ```bash
   cd pyReborn
   pip install -e .
   ```

2. Start the GServer:
   ```bash
   docker-compose up -d
   ```

3. Run any example script from its directory

## Server Requirements

All examples expect:
- **Server**: localhost:14900
- **Account**: Any valid account (examples use various bot names)
- **Password**: 1234

## Creating Your Own Bots

Use the examples as starting points for your own bots. Key patterns:

1. **Basic Structure:**
   ```python
   from pyreborn.client import RebornClient
   
   client = RebornClient("localhost", 14900)
   client.connect()
   client.login("botname", "1234")
   # ... bot logic ...
   client.disconnect()
   ```

2. **Event Handling:**
   ```python
   client.events.subscribe('player_moved', my_handler)
   client.events.subscribe('player_chat', my_chat_handler)
   ```

3. **Level Data:**
   ```python
   level = client.level_manager.get_current_level()
   tiles = level.get_board_tiles_array()  # 64x64 tile array
   ```

See the main PyReborn documentation for complete API reference.