# PLO_DEFAULTWEAPON

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 43
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Default weapon assignment for player

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| weapon_name | STRING_GCHAR_LEN | Name of default weapon |
| weapon_script | VARIABLE_DATA | Default weapon code/script |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(43)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
