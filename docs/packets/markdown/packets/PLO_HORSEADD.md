# PLO_HORSEADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 17
- **Category**: core
- **Variable Length**: No
- **Description**: Add horse to level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Horse X coordinate |
| y_coord | GCHAR | Horse Y coordinate |
| horse_type | GCHAR | Type/color of horse |
| direction | GCHAR | Direction horse is facing |
| owner_id | GSHORT | Player who owns the horse |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(17)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
