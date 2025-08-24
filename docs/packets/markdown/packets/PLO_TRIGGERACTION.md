# PLO_TRIGGERACTION

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 48
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Trigger activation notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| trigger_x | GCHAR | X position of trigger |
| trigger_y | GCHAR | Y position of trigger |
| action_type | GCHAR | Type of action triggered |
| action_data | VARIABLE_DATA | Action parameters and data |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(48)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
