# PLO_PLAYERKICK

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 53
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Kick player from server

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| kick_reason | STRING_GCHAR_LEN | Reason for kicking player |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(53)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
