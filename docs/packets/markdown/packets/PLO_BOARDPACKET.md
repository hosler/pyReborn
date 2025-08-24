# PLO_BOARDPACKET

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 101
- **Category**: files
- **Variable Length**: No
- **Description**: Level board data (usually 8192 bytes)

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| board_data | FIXED_DATA | Board tile data (8192 bytes) |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(101)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_LARGEFILESTART](PLO_LARGEFILESTART.md)
- [PLO_FILE](PLO_FILE.md)
- [PLO_LARGEFILESIZE](PLO_LARGEFILESIZE.md)
- [PLO_RAWDATA](PLO_RAWDATA.md)
- [PLO_LARGEFILEEND](PLO_LARGEFILEEND.md)
