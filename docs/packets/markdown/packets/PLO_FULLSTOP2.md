# PLO_FULLSTOP2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 177
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Enhanced full stop command with parameters

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| stop_type | GCHAR | Type of stop command |
| stop_data | VARIABLE_DATA | Additional stop parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(177)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
