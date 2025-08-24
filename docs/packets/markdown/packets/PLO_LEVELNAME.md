# PLO_LEVELNAME

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 6
- **Category**: core
- **Variable Length**: Yes
- **Description**: Current level name

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| level_name | VARIABLE_DATA | Null-terminated level name |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(6)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
