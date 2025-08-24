# PLO_BOMBDEL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 12
- **Category**: core
- **Variable Length**: No
- **Description**: Delete bomb at coordinates

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | COORDINATE | X coordinate |
| y_coord | COORDINATE | Y coordinate |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(12)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
