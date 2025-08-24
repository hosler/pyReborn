# PLO_FREEZEPLAYER2

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 154
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Enhanced freeze player with options

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player to freeze |
| freeze_options | VARIABLE_DATA | Freeze type and duration settings |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(154)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
