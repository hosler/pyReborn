# PLO_OTHERPLPROPS

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 8
- **Category**: core
- **Variable Length**: Yes
- **Description**: Other player properties update

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| player_id | GSHORT | ID of the player these properties belong to |
| properties_data | VARIABLE_DATA | Encoded player properties |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(8)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
