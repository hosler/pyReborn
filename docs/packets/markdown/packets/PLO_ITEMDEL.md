# PLO_ITEMDEL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 23
- **Category**: unknown
- **Variable Length**: No
- **Description**: Remove item from level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Item X coordinate |
| y_coord | GCHAR | Item Y coordinate |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(23)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
