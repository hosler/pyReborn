# PLO_SCRIPTENGINE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 71
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Script engine control and management

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| script_command | GCHAR | Type of script operation |
| script_name | STRING_GCHAR_LEN | Name/identifier of script |
| script_data | VARIABLE_DATA | Script code, parameters, and context |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(71)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
