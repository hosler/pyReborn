# PLO_CAMERACONTROL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 70
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Camera control and movement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| camera_command | GCHAR | Type of camera control |
| camera_x | GSHORT | Target X position for camera |
| camera_y | GSHORT | Target Y position for camera |
| camera_data | VARIABLE_DATA | Zoom, speed, and transition settings |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(70)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
