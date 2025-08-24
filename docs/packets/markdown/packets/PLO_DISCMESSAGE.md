# PLO_DISCMESSAGE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 16
- **Category**: core
- **Variable Length**: Yes
- **Description**: Disconnect notification with reason

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| disconnect_reason | VARIABLE_DATA | Message explaining disconnection |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(16)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
