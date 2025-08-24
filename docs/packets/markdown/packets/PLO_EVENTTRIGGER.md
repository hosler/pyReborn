# PLO_EVENTTRIGGER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 76
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Event system trigger and management

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| event_id | GSHORT | Unique identifier for the event |
| event_type | GCHAR | Category/type of event |
| event_data | VARIABLE_DATA | Event parameters and actions |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(76)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
