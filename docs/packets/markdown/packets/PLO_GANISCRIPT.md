# PLO_GANISCRIPT

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 134
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: GANI animation script data

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| gani_name | STRING_GCHAR_LEN | Name of GANI animation |
| script_data | VARIABLE_DATA | Animation script and timing data |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(134)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
