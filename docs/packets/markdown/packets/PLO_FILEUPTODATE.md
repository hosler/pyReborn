# PLO_FILEUPTODATE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 45
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: File is up to date, no download needed

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| file_name | STRING_GCHAR_LEN | Name of file that's up to date |
| modification_time | GINT4 | Timestamp of current file version |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(45)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
