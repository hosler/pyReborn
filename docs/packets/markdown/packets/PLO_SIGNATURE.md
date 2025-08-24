# PLO_SIGNATURE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 25
- **Category**: system
- **Variable Length**: Yes
- **Description**: Login signature confirmation

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| signature | VARIABLE_DATA | Login signature data |

## Implementation

✅ **parse_packet() function implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(25)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_DELPLAYER](PLO_DELPLAYER.md)
- [PLO_STARTMESSAGE](PLO_STARTMESSAGE.md)
- [PLO_SERVERTEXT](PLO_SERVERTEXT.md)
- [PLO_ADMINMESSAGE](PLO_ADMINMESSAGE.md)
- [PLO_PLAYERBAN](PLO_PLAYERBAN.md)
