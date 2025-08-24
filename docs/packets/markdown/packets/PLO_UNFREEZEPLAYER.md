# PLO_UNFREEZEPLAYER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 155
- **Category**: unknown
- **Variable Length**: No
- **Description**: Unfreeze a previously frozen player

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player to unfreeze |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(155)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
