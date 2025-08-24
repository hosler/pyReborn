# PLO_ITEMADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 22
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Add item to level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Item X coordinate |
| y_coord | GCHAR | Item Y coordinate |
| item_type | STRING_GCHAR_LEN | Item type/sprite identifier |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(22)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
