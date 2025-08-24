# PLO_NPCMOVED

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 24
- **Category**: npcs
- **Variable Length**: No
- **Description**: NPC movement update

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GCHAR | NPC identifier |
| x | GCHAR | X coordinate |
| y | GCHAR | Y coordinate |
| direction | GCHAR | Movement direction |
| sprite | GCHAR | Sprite/animation frame |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(24)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_NPCWEAPONDEL](PLO_NPCWEAPONDEL.md)
- [PLO_NPCWEAPONADD](PLO_NPCWEAPONADD.md)
