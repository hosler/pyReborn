# PLO_LARGEFILESIZE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 84
- **Category**: files
- **Variable Length**: Yes
- **Description**: Large file size announcement

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| file_name | STRING_GCHAR_LEN | Name of the large file |
| file_size | GINT5 | Size of file in bytes (5-byte integer) |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(84)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_LARGEFILESTART](PLO_LARGEFILESTART.md)
- [PLO_FILE](PLO_FILE.md)
- [PLO_RAWDATA](PLO_RAWDATA.md)
- [PLO_LARGEFILEEND](PLO_LARGEFILEEND.md)
- [PLO_BOARDPACKET](PLO_BOARDPACKET.md)
