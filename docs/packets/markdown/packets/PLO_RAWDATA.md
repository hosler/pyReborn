# PLO_RAWDATA

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 100
- **Category**: files
- **Variable Length**: No
- **Description**: Announces size of raw data in next packet

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| size | GINT3 | Size of following data |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(100)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_LARGEFILESTART](PLO_LARGEFILESTART.md)
- [PLO_FILE](PLO_FILE.md)
- [PLO_LARGEFILESIZE](PLO_LARGEFILESIZE.md)
- [PLO_LARGEFILEEND](PLO_LARGEFILEEND.md)
- [PLO_BOARDPACKET](PLO_BOARDPACKET.md)
