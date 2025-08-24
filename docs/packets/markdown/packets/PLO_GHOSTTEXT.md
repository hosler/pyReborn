# PLO_GHOSTTEXT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 173
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Ghost mode text display

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| text_x | GSHORT | X coordinate for text display |
| text_y | GSHORT | Y coordinate for text display |
| text_content | STRING_GCHAR_LEN | Ghost text content |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(173)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
