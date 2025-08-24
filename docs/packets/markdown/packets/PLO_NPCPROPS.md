# PLO_NPCPROPS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 3
- **Category**: core
- **Variable Length**: Yes
- **Description**: NPC properties update

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| properties | VARIABLE_DATA | Encoded NPC properties |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(3)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
- [PLO_OTHERPLPROPS](PLO_OTHERPLPROPS.md)
