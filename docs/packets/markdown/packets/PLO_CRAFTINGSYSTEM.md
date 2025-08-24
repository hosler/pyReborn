# PLO_CRAFTINGSYSTEM

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 81
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Item crafting and creation system

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| crafting_type | GCHAR | Type of crafting operation |
| recipe_id | GSHORT | Identifier for crafting recipe |
| crafting_data | VARIABLE_DATA | Materials, results, and parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(81)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
