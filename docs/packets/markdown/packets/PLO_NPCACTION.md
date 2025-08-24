# PLO_NPCACTION

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 26
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: NPC action/animation

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | NPC unique identifier |
| action_type | GCHAR | Type of action being performed |
| action_data | VARIABLE_DATA | Additional action parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(26)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
- [PLO_ADDPLAYER](PLO_ADDPLAYER.md)
