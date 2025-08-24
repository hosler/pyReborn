# PLO_PROFILE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 75
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Player profile data and statistics

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| profile_data | VARIABLE_DATA | Encoded player profile information |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(75)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
