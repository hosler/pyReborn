# PLO_GHOSTMODE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 170
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Ghost mode notification and configuration

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| ghost_state | GCHAR | Ghost mode state or type |
| ghost_data | VARIABLE_DATA | Ghost mode configuration |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(170)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_MINIMAP](PLO_MINIMAP.md)
