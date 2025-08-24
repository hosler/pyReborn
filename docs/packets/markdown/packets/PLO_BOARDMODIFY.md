# PLO_BOARDMODIFY

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 7
- **Category**: core
- **Variable Length**: Yes
- **Description**: Level board tile modification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| modify_x | GCHAR | X coordinate of modification |
| modify_y | GCHAR | Y coordinate of modification |
| tile_data | VARIABLE_DATA | New tile information |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(7)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
