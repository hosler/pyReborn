# PLO_TIMEOUTWARNING

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 54
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Player timeout warning

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| warning_message | STRING_GCHAR_LEN | Timeout warning text |
| timeout_seconds | GSHORT | Seconds until timeout |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(54)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
