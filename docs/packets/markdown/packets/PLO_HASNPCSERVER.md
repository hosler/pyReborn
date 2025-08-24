# PLO_HASNPCSERVER

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 44
- **Category**: unknown
- **Variable Length**: No
- **Description**: NPC server availability status

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| has_npc_server | GCHAR | 1 if NPC server available, 0 if not |
| npc_server_version | GCHAR | Version of the NPC server |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(44)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
