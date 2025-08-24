# PLO_QUESTUPDATE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 77
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Quest system update and progress

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| quest_id | GSHORT | Unique identifier for the quest |
| quest_status | GCHAR | Current quest status |
| quest_progress | GCHAR | Progress percentage or step |
| quest_data | VARIABLE_DATA | Objectives, rewards, and description |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(77)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
