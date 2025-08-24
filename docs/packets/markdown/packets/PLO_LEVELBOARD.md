# PLO_LEVELBOARD

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 0
- **Category**: core
- **Variable Length**: Yes
- **Description**: Unknown level-related data (not tile data)

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| compressed_length | GSHORT | Compressed data length |
| compressed_data | VARIABLE_DATA | Compressed level board data |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(0)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERWARP](PLO_PLAYERWARP.md)
- [PLO_BADDYPROPS](PLO_BADDYPROPS.md)
- [PLO_NPCPROPS](PLO_NPCPROPS.md)
- [PLO_LEVELSIGN](PLO_LEVELSIGN.md)
- [PLO_ISLEADER](PLO_ISLEADER.md)
