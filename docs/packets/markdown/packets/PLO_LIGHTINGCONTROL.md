# PLO_LIGHTINGCONTROL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 66
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Lighting and visual effects control

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| lighting_type | GCHAR | Type of lighting effect |
| light_intensity | GCHAR | Brightness/intensity level |
| lighting_data | VARIABLE_DATA | Color, position, and effect parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(66)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
