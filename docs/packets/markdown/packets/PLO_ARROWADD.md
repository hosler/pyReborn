# PLO_ARROWADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 19
- **Category**: core
- **Variable Length**: No
- **Description**: Add arrow projectile to level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Arrow starting X coordinate |
| y_coord | GCHAR | Arrow starting Y coordinate |
| direction | GCHAR | Arrow direction (0-3: down,left,up,right) |
| speed | GCHAR | Arrow velocity |
| owner_id | GSHORT | Player ID who fired the arrow |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(19)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
