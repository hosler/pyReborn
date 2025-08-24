# PLO_LEVELLINK

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 1
- **Category**: core
- **Variable Length**: Yes
- **Description**: Level connection data for transitions

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| link_data | VARIABLE_DATA | No description |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(1)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
