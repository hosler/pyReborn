# PLO_THROWCARRIED

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 21
- **Category**: unknown
- **Variable Length**: No
- **Description**: Throw carried object projectile

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Throw starting X coordinate |
| y_coord | GCHAR | Throw starting Y coordinate |
| direction | GCHAR | Direction of throw |
| object_type | GCHAR | Type of object being thrown |
| thrower_id | GSHORT | Player ID who threw the object |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(21)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
