# PLO_MOVE2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 189
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Enhanced player movement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of moving player |
| movement_data | VARIABLE_DATA | Enhanced movement information |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(189)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
- [PLO_MINIMAP](PLO_MINIMAP.md)
