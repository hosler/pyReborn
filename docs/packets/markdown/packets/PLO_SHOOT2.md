# PLO_SHOOT2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 191
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Enhanced player shooting

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| shooter_id | GSHORT | ID of player shooting |
| shoot_data | VARIABLE_DATA | Enhanced shooting information |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(191)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
- [PLO_MINIMAP](PLO_MINIMAP.md)
