# PyReborn API Quick Reference

## Basic Usage

```python
# Simple client
from pyreborn import Client
client = Client("localhost", 14900)
client.connect()
client.login("username", "password")
client.move(1, 0)
client.say("Hello!")
client.disconnect()

# Context manager (auto-cleanup)
with Client.session("localhost", 14900, "user", "pass") as client:
    client.move(1, 0)
    client.say("Hello!")
```

## Advanced Patterns

```python
# Fluent builder
from pyreborn.advanced_api import PresetBuilder
client = (PresetBuilder.development()
    .with_auto_reconnect(max_retries=3)
    .build_and_connect("user", "pass"))

# High-level actions
from pyreborn.advanced_api import enhance_with_actions
actions = enhance_with_actions(client)
actions.walk_to(10, 10)
actions.attack("north")
actions.explore("spiral")

# Async/await
from pyreborn.advanced_api import AsyncClient
async with AsyncClient("localhost", 14900) as client:
    await client.connect()
    await client.login("user", "pass")
    await client.move(1, 0)
```

## Packet Introspection

```python
# Strongly-typed enums
from pyreborn.protocol.packet_enums import IncomingPackets
packet_id = IncomingPackets.PLAYER_PROPS  # 9

# Packet discovery
from pyreborn import get_packet_info, search_packets
packet = get_packet_info(9)
level_packets = search_packets("level")
```

## Testing

```bash
# Test everything
python tests/bots/comprehensive_test_bot.py your_username your_password

# Test API examples  
python examples/api/complete_api_showcase.py
```

**See [README.md](README.md) for complete documentation and [CLAUDE.md](CLAUDE.md) for developer guide.**