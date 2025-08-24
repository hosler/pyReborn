# PLO_FLAGSET

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 28
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Set server flag for global state

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| flag_name | STRING_GCHAR_LEN | Name of the flag being set |
| flag_value | VARIABLE_DATA | Value assigned to the flag |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(28)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
