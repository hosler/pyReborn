# PLO_BOMBADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 11
- **Category**: core
- **Variable Length**: No
- **Description**: Add bomb to level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Bomb X coordinate |
| y_coord | GCHAR | Bomb Y coordinate |
| bomb_power | GCHAR | Explosive power/radius |
| bomb_timer | GCHAR | Time until detonation |
| owner_id | GSHORT | Player ID who placed the bomb |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(11)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
