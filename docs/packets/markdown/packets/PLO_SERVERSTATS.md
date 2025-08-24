# PLO_SERVERSTATS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 59
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Server performance and usage statistics

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| stats_data | VARIABLE_DATA | Encoded server statistics |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(59)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
