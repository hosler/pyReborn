# PLO_GMAPWARP2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 49
- **Category**: movement
- **Variable Length**: Yes
- **Description**: GMAP warp with world coordinates and segment positions

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x2 | GCHAR | World X coordinate |
| y2 | GCHAR | World Y coordinate |
| z_plus_50 | GCHAR | Z coordinate + 50 |
| gmaplevelx | GCHAR | GMAP segment X (map_x) |
| gmaplevely | GCHAR | GMAP segment Y (map_y) |
| gmap_name | VARIABLE_DATA | GMAP filename |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(49)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

*No directly related packets.*
