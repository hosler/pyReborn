# PLO_MINIMAP

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 172
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Minimap display data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| minimap_data | VARIABLE_DATA | Encoded minimap information |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(172)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
