# PLO_NPCSERVERADDR

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 79
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: NPC server address and port

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_server_ip | STRING_GCHAR_LEN | IP address of NPC server |
| npc_server_port | GSHORT | Port number for NPC server |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(79)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
