# PLO_GHOSTICON

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 174
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Ghost mode icon display

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| icon_x | GSHORT | X coordinate for icon display |
| icon_y | GSHORT | Y coordinate for icon display |
| icon_type | GCHAR | Type or ID of icon |
| icon_data | VARIABLE_DATA | Icon configuration data |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(174)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
