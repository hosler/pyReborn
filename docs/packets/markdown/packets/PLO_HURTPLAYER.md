# PLO_HURTPLAYER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 40
- **Category**: combat
- **Variable Length**: No
- **Description**: Player hurt/damage notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player who was hurt (0 for self) |
| damage_amount | GCHAR | Amount of damage taken |
| damage_type | GCHAR | Type of damage (sword, bomb, etc.) |
| source_x | GCHAR | X coordinate of damage source |
| source_y | GCHAR | Y coordinate of damage source |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(40)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_EXPLOSION](PLO_EXPLOSION.md)
- [PLO_RC_ADMINMESSAGE](PLO_RC_ADMINMESSAGE.md)
