# PLO_PLAYERWARP

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 14
- **Category**: core
- **Variable Length**: Yes
- **Description**: Player warp/teleport to new position

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player who warped (0 for self) |
| level_name | STRING_GCHAR_LEN | Destination level name |
| x_coord | GCHAR | New X coordinate |
| y_coord | GCHAR | New Y coordinate |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(14)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
- [PLO_OTHERPLPROPS](PLO_OTHERPLPROPS.md)
