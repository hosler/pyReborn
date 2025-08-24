# PLO_PLAYERRIGHTS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 60
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Player rights and permissions

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| rights_level | GCHAR | Player rights/admin level |
| rights_data | VARIABLE_DATA | Specific permissions and capabilities |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(60)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
