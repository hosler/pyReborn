# PLO_LEVELCHEST

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 4
- **Category**: core
- **Variable Length**: Yes
- **Description**: Chest placement and contents

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | BYTE | X coordinate (pixels/2) |
| y_coord | BYTE | Y coordinate (pixels/2) |
| item | BYTE | Item/chest type |
| sign_text | STRING_GCHAR_LEN | Sign text for chest |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(4)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
