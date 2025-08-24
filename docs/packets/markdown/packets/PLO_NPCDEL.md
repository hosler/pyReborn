# PLO_NPCDEL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 29
- **Category**: unknown
- **Variable Length**: No
- **Description**: Delete NPC from level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | NPC unique identifier to remove |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(29)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
- [PLO_ADDPLAYER](PLO_ADDPLAYER.md)
