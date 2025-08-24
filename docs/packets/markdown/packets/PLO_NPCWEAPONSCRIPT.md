# PLO_NPCWEAPONSCRIPT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 140
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: NPC weapon script data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| weapon_name | STRING_GCHAR_LEN | Name of NPC weapon |
| script_data | VARIABLE_DATA | Weapon script and behavior code |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(140)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
