# PLO_HIDENPCS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 151
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Hide NPCs from view

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| hide_options | VARIABLE_DATA | NPC hiding configuration and filters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(151)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
- [PLO_ADDPLAYER](PLO_ADDPLAYER.md)
