# PLO_STATUSLIST

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 180
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Status list display (players, scores, etc.)

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| status_type | GCHAR | Type of status list |
| status_data | VARIABLE_DATA | Encoded status information |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(180)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
