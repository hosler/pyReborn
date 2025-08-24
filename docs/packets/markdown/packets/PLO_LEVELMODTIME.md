# PLO_LEVELMODTIME

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 39
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Level modification timestamp for caching

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| level_name | STRING_GCHAR_LEN | Name of the level |
| modification_time | GINT4 | Unix timestamp of last modification |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(39)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
