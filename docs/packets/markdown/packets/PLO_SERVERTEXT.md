# PLO_SERVERTEXT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 82
- **Category**: system
- **Variable Length**: Yes
- **Description**: Server text message/announcement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| message_type | GCHAR | Type of server message |
| message_content | STRING_GCHAR_LEN | Server message text |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(82)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
- [PLO_STAFFGUILDS](PLO_STAFFGUILDS.md)
