# PLO_HORSEDEL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 18
- **Category**: core
- **Variable Length**: No
- **Description**: Remove horse from level

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Horse X coordinate for removal |
| y_coord | GCHAR | Horse Y coordinate for removal |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(18)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
