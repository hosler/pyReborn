# PLO_ACHIEVEMENTUNLOCK

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 72
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Achievement unlock notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| achievement_id | GSHORT | Unique achievement identifier |
| achievement_name | STRING_GCHAR_LEN | Display name of achievement |
| achievement_data | VARIABLE_DATA | Description, rewards, and metadata |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(72)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
