# PLO_PLAYERBAN

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 58
- **Category**: system
- **Variable Length**: Yes
- **Description**: Ban player from server

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| ban_duration | GINT4 | Ban duration in seconds |
| ban_reason | STRING_GCHAR_LEN | Reason for the ban |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(58)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_STAFFGUILDS](PLO_STAFFGUILDS.md)
