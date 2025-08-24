# PLO_NC_CLASSADD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 163
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: NPC-Control class addition

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| class_name | STRING_GCHAR_LEN | Name of NPC class |
| class_data | VARIABLE_DATA | Class definition and methods |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(163)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
