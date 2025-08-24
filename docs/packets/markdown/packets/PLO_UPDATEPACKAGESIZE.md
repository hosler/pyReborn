# PLO_UPDATEPACKAGESIZE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 105
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Update package size announcement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| package_name | STRING_GCHAR_LEN | Name of update package |
| package_size | GINT5 | Size of package in bytes |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(105)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
