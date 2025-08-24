# PLO_NPCWEAPONADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 33
- **Category**: npcs
- **Variable Length**: Yes
- **Description**: Add weapon to NPC

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | NPC that owns the weapon |
| weapon_name | STRING_GCHAR_LEN | Weapon identifier/script name |
| weapon_image | STRING_GCHAR_LEN | Weapon sprite/appearance |
| weapon_script | VARIABLE_DATA | Weapon behavior script |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(33)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_NPCWEAPONDEL](PLO_NPCWEAPONDEL.md)
- [PLO_NPCMOVED](PLO_NPCMOVED.md)
