# pyreborn

A minimal Python client for Reborn servers. ~1,300 lines of code with no external dependencies.

## Installation

```bash
cd pyReborn
pip install -e .
```

## Quick Start

```python
from pyreborn import Client

# Connect and login
client = Client("localhost", 14900)
client.connect()
client.login("username", "password")

# Play the game
client.move(1, 0)   # Move right
client.say("Hello!")  # Chat

# Update loop (call regularly in your game loop)
client.update()

# Cleanup
client.disconnect()
```

## Context Manager

```python
with Client("localhost", 14900) as client:
    client.connect()
    client.login("username", "password")
    client.move(1, 0)
    # Auto-disconnect on exit
```

## Quick Connect

```python
from pyreborn import connect

client = connect("username", "password", "localhost", 14900)
if client:
    client.move(1, 0)
    client.disconnect()
```

## Pygame Example

```bash
python -m pyreborn.example_pygame username password
```

## API Reference

### Client

```python
client = Client(host="localhost", port=14900, version="2.22")

# Connection
client.connect() -> bool
client.disconnect()
client.connected -> bool
client.authenticated -> bool

# Authentication
client.login(username, password, timeout=5.0) -> bool

# Actions
client.move(dx, dy) -> bool    # dx/dy: -1, 0, or 1
client.say(message) -> bool

# Update (call in game loop)
client.update(timeout=0.01) -> List[Tuple[int, bytes]]

# Player state
client.x -> float
client.y -> float
client.level -> str
client.player -> Player  # Full player object

# Callbacks
client.on_chat = lambda player_id, message: print(f"{player_id}: {message}")
client.on_packet[packet_id] = lambda data: handle(data)
```

### Player

```python
player = client.player

player.account -> str
player.nickname -> str
player.x -> float
player.y -> float
player.level -> str
player.direction -> int  # 0=up, 1=left, 2=down, 3=right
player.hearts -> float
player.max_hearts -> float
player.rupees -> int
```

## File Structure

```
pyreborn/
├── __init__.py      # Exports
├── client.py        # Main Client class
├── protocol.py      # Socket, encryption, packet framing
├── packets.py       # Packet parsing and building
├── player.py        # Player dataclass
└── example_pygame.py
```

## Supported Versions

- 2.22 (recommended)
- 6.037
- 6.037_linux
