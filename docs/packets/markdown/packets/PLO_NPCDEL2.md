# PLO_NPCDEL2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 150
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Enhanced NPC deletion with options

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | NPC ID to remove |
| delete_options | VARIABLE_DATA | Enhanced deletion parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(150)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_ADDPLAYER](PLO_ADDPLAYER.md)
