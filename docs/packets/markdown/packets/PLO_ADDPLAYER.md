# PLO_ADDPLAYER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 55
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Add new player to level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | Unique player identifier |
| account_name | STRING_GCHAR_LEN | Player account name |
| nickname | STRING_GCHAR_LEN | Player display nickname |
| level_name | STRING_GCHAR_LEN | Player's current level |
| x_coord | GCHAR | Player X coordinate |
| y_coord | GCHAR | Player Y coordinate |
| appearance_data | VARIABLE_DATA | Player appearance and properties |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(55)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
