# PLO_RC_CHAT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 74
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Remote Control admin chat message

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| admin_name | STRING_GCHAR_LEN | Name of RC admin |
| chat_message | STRING_GCHAR_LEN | Admin chat message |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(74)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
