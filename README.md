# pyReborn

A Python library for connecting to GServer (Graal Reborn servers) with full protocol support.

## Features

- ✅ Full encryption support (ENCRYPT_GEN_5)
- ✅ Packet parsing and handling
- ✅ Player tracking and properties
- ✅ Chat and messaging
- ✅ Movement and animations
- ✅ Combat (bombs, arrows)
- ✅ Session management
- ✅ Event-driven architecture
- ✅ Packet buffering for bots

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/pyReborn.git
cd pyReborn

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

```python
from pyreborn import GraalClient, EventType

# Create client
client = GraalClient("localhost", 14900)

# Handle events
@client.on(EventType.CHAT_MESSAGE)
def on_chat(player_id, message):
    print(f"Player {player_id}: {message}")

# Connect and play
if client.connect():
    client.login("account", "password")
    client.say("Hello world!")
    
    # Keep running
    import time
    time.sleep(60)
    
client.disconnect()
```

## Advanced Usage

### Player Tracking
```python
@client.on(EventType.OTHER_PLAYER_UPDATE)
def on_player_update(player):
    print(f"Player {player.nickname} at ({player.x}, {player.y})")
```

### Session Management
```python
# Get session statistics
summary = client.get_session_summary()
print(f"Players seen: {summary['total_players']}")

# Search for players
players = client.find_players_by_name("John")

# Get chat history
recent_chat = client.get_recent_chat(limit=10)
```

### Combat
```python
# Drop bombs
client.drop_bomb(x=30, y=30, power=3, timer=55)

# Shoot arrows
client.shoot_arrow()

# Advanced projectiles
client.shoot_projectile_v2(angle=45, speed=20, gravity=8, gani="arrow.gani")
```

### Packet Buffering (for bots)
```python
# Process packets in your own loop
while client.has_buffered_packets():
    packet = client.get_buffered_packet(timeout=0.1)
    if packet:
        # Process packet
        pass
```

## Event Types

- `CONNECTED` - Connected to server
- `DISCONNECTED` - Disconnected from server
- `LOGIN_SUCCESS` - Login successful
- `LOGIN_FAILED` - Login failed
- `PLAYER_PROPS_UPDATE` - Local player updated
- `OTHER_PLAYER_UPDATE` - Other player updated
- `PLAYER_ADDED` - New player joined
- `PLAYER_REMOVED` - Player left
- `CHAT_MESSAGE` - Chat message received
- `PRIVATE_MESSAGE` - PM received
- `LEVEL_ENTERED` - Entered new level
- `BOMB_ADDED` - Bomb placed
- `BOMB_EXPLODED` - Bomb exploded
- `RAW_PACKET_RECEIVED` - Raw packet (advanced)

## Examples

See the `examples/` directory for more examples:
- `simple_bot.py` - Basic connection and chat
- `movement_bot.py` - Movement patterns
- `sword_bot.py` - Combat bot
- `full_demo.py` - All features demonstration

## Protocol Documentation

See `PACKET_ANALYSIS.md` for detailed protocol information and findings.

## Development

### Running Tests
```bash
python -m pytest tests/
```

### Debug Mode
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

## License

MIT License - See LICENSE file for details.

## Credits

Based on the GServer protocol by the OpenGraal team.