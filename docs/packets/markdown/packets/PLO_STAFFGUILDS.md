# PLO_STAFFGUILDS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 47
- **Category**: system
- **Variable Length**: Yes
- **Description**: Staff guilds and member information

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| guild_data | VARIABLE_DATA | Encoded staff guild information |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(47)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
