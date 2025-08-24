# PLO_BADDYHURT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 27
- **Category**: unknown
- **Variable Length**: No
- **Description**: Baddy hurt/damage notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| baddy_id | GSHORT | ID of baddy that was hurt |
| damage_amount | GCHAR | Amount of damage taken |
| damage_type | GCHAR | Type of damage (sword, bomb, etc.) |
| remaining_health | GCHAR | Baddy's health after damage |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(27)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
