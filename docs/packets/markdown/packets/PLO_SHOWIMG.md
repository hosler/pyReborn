# PLO_SHOWIMG

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 32
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Display image on client screen

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| image_name | STRING_GCHAR_LEN | Name/path of image to display |
| display_x | GSHORT | X coordinate for image display |
| display_y | GSHORT | Y coordinate for image display |
| display_options | VARIABLE_DATA | Additional display parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(32)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
