# PyReborn

A minimal Python client for Reborn servers. Zero external dependencies.

## Installation

```bash
pip install -e .
```

## Quick Start

```python
from pyreborn import Client

client = Client("localhost", 14900)
client.connect()
client.login("username", "password")

# Move around
client.move(1, 0)   # Move right
client.move(0, -1)  # Move up

# Chat
client.say("Hello!")

# Game loop
while client.connected:
    client.update(timeout=0.1)

client.disconnect()
```

## Examples

### Context Manager

```python
with Client("localhost", 14900) as client:
    client.connect()
    client.login("username", "password")
    client.move(1, 0)
    # Auto-disconnect on exit
```

### Quick Connect

```python
from pyreborn import connect

client = connect("username", "password", "localhost", 14900)
if client:
    client.say("Connected!")
    client.disconnect()
```

### Event Callbacks

```python
client.on_chat = lambda player_id, msg: print(f"{player_id}: {msg}")
client.on_hurt = lambda player_id, dmg, *_: print(f"Player {player_id} hurt!")
```

### Combat

```python
client.sword_attack(3)  # 0=up, 1=left, 2=down, 3=right
client.drop_bomb(1)     # Drop bomb with power 1
client.shoot(0)         # Shoot arrow up
```

### Listserver

```python
from pyreborn import connect_via_listserver

client = connect_via_listserver(
    listserver_host="listserver.example.com",
    listserver_port=14922,
    username="user",
    password="pass",
    server_name="My Server"
)
```

## Pygame Client

Run the included pygame game client:

```bash
python -m pyreborn.example_pygame username password
```

Or connect via listserver:

```bash
python -m pyreborn.example_pygame username password --listserver listserver.example.com
```

Controls:
- Arrow keys / WASD - Move
- Space / S - Sword attack
- A - Grab/pickup
- D - Use weapon
- Q - Toggle inventory
- Enter - Chat

## License

MIT License
