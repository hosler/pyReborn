# PLO_UNKNOWN198

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 198
- **Category**: ui
- **Variable Length**: Yes
- **Description**: Unknown packet type 198

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| unknown_data | VARIABLE_DATA | Packet data of unknown format |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(198)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_MOVE2](PLO_MOVE2.md)
- [PLO_CLEARWEAPONS](PLO_CLEARWEAPONS.md)
- [PLO_SHOOT2](PLO_SHOOT2.md)
- [PLO_BIGMAP](PLO_BIGMAP.md)
- [PLO_GHOSTMODE](PLO_GHOSTMODE.md)
