# PLO_LEVELSIGN

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 5
- **Category**: core
- **Variable Length**: Yes
- **Description**: Sign placement and text content

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | BYTE | X coordinate |
| y_coord | BYTE | Y coordinate |
| sign_text | STRING_GCHAR_LEN | Sign text content |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(5)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
- [PLO_OTHERPLPROPS](PLO_OTHERPLPROPS.md)
