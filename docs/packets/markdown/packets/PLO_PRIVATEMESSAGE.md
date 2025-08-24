# PLO_PRIVATEMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 37
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Private message between players

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| sender_id | GSHORT | ID of player sending the message |
| message_text | VARIABLE_DATA | Private message content |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(37)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
