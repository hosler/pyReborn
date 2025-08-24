# PLO_RPGWINDOW

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 179
- **Category**: ui
- **Variable Length**: Yes
- **Description**: RPG window/interface display

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| window_type | GCHAR | Type of RPG window to display |
| window_x | GSHORT | X coordinate for window |
| window_y | GSHORT | Y coordinate for window |
| window_data | VARIABLE_DATA | Window content and configuration |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(179)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
