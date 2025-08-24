# PLO_FIRESPY

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 20
- **Category**: core
- **Variable Length**: No
- **Description**: Fire spy projectile

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| x_coord | GCHAR | Firespy starting X coordinate |
| y_coord | GCHAR | Firespy starting Y coordinate |
| direction | GCHAR | Direction of travel |
| fire_power | GCHAR | Fire power/intensity |
| owner_id | GSHORT | Player ID who fired the firespy |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(20)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
