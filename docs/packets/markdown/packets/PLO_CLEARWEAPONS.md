# PLO_CLEARWEAPONS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 194
- **Category**: ui
- **Variable Length**: No
- **Description**: Clear all weapons from player inventory

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| clear_type | GCHAR | Type of weapon clearing |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(194)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
- [PLO_MINIMAP](PLO_MINIMAP.md)
