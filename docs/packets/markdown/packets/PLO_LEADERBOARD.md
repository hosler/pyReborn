# PLO_LEADERBOARD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 73
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Player leaderboard and ranking data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| leaderboard_type | GCHAR | Type of leaderboard |
| player_count | GCHAR | Number of players in leaderboard |
| leaderboard_data | VARIABLE_DATA | Ranked player data and statistics |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(73)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
