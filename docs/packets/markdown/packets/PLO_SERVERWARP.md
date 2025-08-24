# PLO_SERVERWARP

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 178
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Server-initiated player warp/teleportation

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| level_name | STRING_GCHAR_LEN | Destination level name |
| x_position | GSHORT | Destination X coordinate |
| y_position | GSHORT | Destination Y coordinate |
| z_position | GCHAR | Destination Z layer |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(178)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
