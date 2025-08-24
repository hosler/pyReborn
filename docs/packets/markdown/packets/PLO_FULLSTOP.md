# PLO_FULLSTOP

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 176
- **Category**: ui
- **Variable Length**: No
- **Description**: Full stop command for player movement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| stop_type | GCHAR | Type of stop command |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(176)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
