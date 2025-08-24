# PLO_BADDYPROPS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 2
- **Category**: core
- **Variable Length**: Yes
- **Description**: Baddy (enemy/NPC) properties and state

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| baddy_id | GSHORT | Unique baddy identifier |
| baddy_x | GSHORT | Baddy X coordinate |
| baddy_y | GSHORT | Baddy Y coordinate |
| baddy_type | GCHAR | Baddy type/class |
| baddy_props | VARIABLE_DATA | Encoded baddy properties |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(2)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
- [PLO_OTHERPLPROPS](PLO_OTHERPLPROPS.md)
