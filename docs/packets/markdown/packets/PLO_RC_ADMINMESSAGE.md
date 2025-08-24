# PLO_RC_ADMINMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 35
- **Category**: combat
- **Variable Length**: Yes
- **Description**: Remote Control admin message

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| message_content | STRING_GCHAR_LEN | Admin message text |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(35)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_EXPLOSION](PLO_EXPLOSION.md)
- [PLO_HURTPLAYER](PLO_HURTPLAYER.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
