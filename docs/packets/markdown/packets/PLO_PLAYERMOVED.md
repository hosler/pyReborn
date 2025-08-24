# PLO_PLAYERMOVED

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 165
- **Category**: unknown
- **Variable Length**: No
- **Description**: Player movement update

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GCHAR | Player identifier |
| x | GCHAR | X coordinate |
| y | GCHAR | Y coordinate |
| direction | GCHAR | Movement direction |
| sprite | GCHAR | Sprite/animation frame |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(165)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
- [PLO_ADDPLAYER](PLO_ADDPLAYER.md)
