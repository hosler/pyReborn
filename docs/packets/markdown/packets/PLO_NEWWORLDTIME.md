# PLO_NEWWORLDTIME

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 42
- **Category**: unknown
- **Variable Length**: No
- **Description**: Server heartbeat and world time synchronization packet (sent ~1/sec)

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| world_time | GINT5 | No description |

## Implementation

✅ **Custom parse() function implemented**

This packet has business logic processing.

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(42)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
