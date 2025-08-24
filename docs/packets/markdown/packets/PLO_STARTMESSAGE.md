# PLO_STARTMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 41
- **Category**: system
- **Variable Length**: Yes
- **Description**: Server startup/welcome message

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| message_content | STRING_GCHAR_LEN | Server startup message |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(41)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
- [PLO_STAFFGUILDS](PLO_STAFFGUILDS.md)
