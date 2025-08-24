# PLO_NPCBYTECODE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 131
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: NPC compiled bytecode for scripting

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| npc_id | GSHORT | Unique NPC identifier |
| bytecode_data | VARIABLE_DATA | Compiled NPC script bytecode |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(131)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
