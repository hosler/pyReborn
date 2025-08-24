# PLO_DELPLAYER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 56
- **Category**: system
- **Variable Length**: No
- **Description**: Remove player from level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of player to remove from level |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(56)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
- [PLO_STAFFGUILDS](PLO_STAFFGUILDS.md)
