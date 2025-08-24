# PLO_MUSICCONTROL

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 65
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Music and sound control

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| music_type | GCHAR | Type of music/sound command |
| music_file | STRING_GCHAR_LEN | Music/sound file name |
| music_settings | VARIABLE_DATA | Volume, loop, and effect settings |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(65)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
