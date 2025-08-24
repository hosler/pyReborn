# PLO_ISLEADER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 10
- **Category**: core
- **Variable Length**: No
- **Description**: Player leadership status notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of the player |
| leader_status | GCHAR | 1 if player is leader, 0 if not |
| leadership_type | GCHAR | Type of leadership (guild, party, etc.) |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(10)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_OTHERPLPROPS](PLO_OTHERPLPROPS.md)
