# PLO_TOALL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 13
- **Category**: core
- **Variable Length**: Yes
- **Description**: Public chat message to all players

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| sender_id | GSHORT | ID of player sending the message |
| message_text | VARIABLE_DATA | Public chat message content |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(13)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
