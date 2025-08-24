# PLO_BOARDLAYER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 107
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Board layer data for complex displays

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| layer_id | GCHAR | Board layer identifier |
| layer_data | VARIABLE_DATA | Encoded layer board content |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(107)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
