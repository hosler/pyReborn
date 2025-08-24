# PLO_PLAYERFREEZE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 52
- **Category**: unknown
- **Variable Length**: No
- **Description**: Freeze player movement and actions

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player to freeze |
| freeze_duration | GSHORT | Freeze time in seconds |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(52)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
