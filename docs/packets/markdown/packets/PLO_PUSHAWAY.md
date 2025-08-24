# PLO_PUSHAWAY

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 38
- **Category**: unknown
- **Variable Length**: No
- **Description**: Push away effect from explosions/impacts

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| target_player_id | GSHORT | ID of player being pushed (0 for self) |
| push_source_x | GCHAR | X coordinate of push source |
| push_source_y | GCHAR | Y coordinate of push source |
| push_force | GCHAR | Strength of the push effect |
| push_direction | GCHAR | Direction of the push |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(38)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
