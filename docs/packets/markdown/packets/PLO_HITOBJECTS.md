# PLO_HITOBJECTS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 46
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Objects hit by weapons/projectiles

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| hit_x | GCHAR | X position of hit |
| hit_y | GCHAR | Y position of hit |
| hit_type | GCHAR | Type of hit/weapon used |
| hit_data | VARIABLE_DATA | Additional hit information |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(46)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
