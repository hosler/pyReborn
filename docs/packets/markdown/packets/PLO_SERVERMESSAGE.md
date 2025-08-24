# PLO_SERVERMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 92
- **Category**: system
- **Variable Length**: Yes
- **Description**: Server message/notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| message | VARIABLE_DATA | Server message text |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(92)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
