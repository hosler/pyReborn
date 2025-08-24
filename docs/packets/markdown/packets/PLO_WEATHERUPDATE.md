# PLO_WEATHERUPDATE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 64
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Weather system update

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| weather_type | GCHAR | Type of weather |
| weather_intensity | GCHAR | Intensity level of weather |
| weather_data | VARIABLE_DATA | Additional weather parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(64)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
