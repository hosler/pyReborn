# PLO_EXPLOSION

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 36
- **Category**: combat
- **Variable Length**: Yes
- **Description**: Explosion visual effect

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| explosion_x | GSHORT | X coordinate of explosion center |
| explosion_y | GSHORT | Y coordinate of explosion center |
| explosion_type | GCHAR | Type/power of explosion |
| explosion_data | VARIABLE_DATA | Additional explosion parameters |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(36)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_RC_ADMINMESSAGE](PLO_RC_ADMINMESSAGE.md)
- [PLO_HURTPLAYER](PLO_HURTPLAYER.md)
