# PLO_NPCWEAPONDEL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 34
- **Category**: npcs
- **Variable Length**: Yes
- **Description**: Remove weapon from NPC

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | NPC that owned the weapon |
| weapon_name | STRING_GCHAR_LEN | Weapon identifier to remove |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(34)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_NPCMOVED](PLO_NPCMOVED.md)
- [PLO_NPCWEAPONADD](PLO_NPCWEAPONADD.md)
