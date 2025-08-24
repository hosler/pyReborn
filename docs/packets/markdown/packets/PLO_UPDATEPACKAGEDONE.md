# PLO_UPDATEPACKAGEDONE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 106
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Update package download complete

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| package_name | STRING_GCHAR_LEN | Name of completed package |
| completion_status | GCHAR | Success/failure status |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(106)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
