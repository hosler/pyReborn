# PLO_PARTICLEEFFECT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 67
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Particle effects system

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| effect_type | GCHAR | Type of particle effect |
| effect_x | GSHORT | X coordinate for effect |
| effect_y | GSHORT | Y coordinate for effect |
| effect_data | VARIABLE_DATA | Particle parameters and settings |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(67)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
