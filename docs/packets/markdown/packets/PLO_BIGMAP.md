# PLO_BIGMAP

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 171
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Big map (world overview) display data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| map_data | VARIABLE_DATA | Encoded big map information |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(171)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
- [PLO_MINIMAP](PLO_MINIMAP.md)
