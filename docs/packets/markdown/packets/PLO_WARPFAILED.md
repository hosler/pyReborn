# PLO_WARPFAILED

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 15
- **Category**: core
- **Variable Length**: Yes
- **Description**: Warp attempt failed notification

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| error_message | VARIABLE_DATA | Reason why the warp failed |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(15)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
