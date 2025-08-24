# PLO_GUILDINFO

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 61
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Guild information and member data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| guild_name | STRING_GCHAR_LEN | Name of the guild |
| guild_data | VARIABLE_DATA | Guild members, settings, and information |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(61)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
