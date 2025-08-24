# PLO_ADMINMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 57
- **Category**: system
- **Variable Length**: Yes
- **Description**: Administrative message to players

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| admin_name | STRING_GCHAR_LEN | Name of the admin |
| message_content | STRING_GCHAR_LEN | Admin message text |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(57)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_RC_ADMINMESSAGE](PLO_RC_ADMINMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
