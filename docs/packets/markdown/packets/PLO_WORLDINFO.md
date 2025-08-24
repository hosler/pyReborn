# PLO_WORLDINFO

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 63
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: World/server information and settings

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| world_name | STRING_GCHAR_LEN | Name of the world/server |
| world_data | VARIABLE_DATA | World settings, description, and info |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(63)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
