# PLO_LARGEFILEEND

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 69
- **Category**: files
- **Variable Length**: Yes
- **Description**: End of large file transfer

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| file_name | STRING_GCHAR_LEN | Name of the completed file |
| checksum | GINT4 | File checksum for verification |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(69)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_LARGEFILESTART](PLO_LARGEFILESTART.md)
- [PLO_FILE](PLO_FILE.md)
- [PLO_LARGEFILESIZE](PLO_LARGEFILESIZE.md)
- [PLO_RAWDATA](PLO_RAWDATA.md)
- [PLO_BOARDPACKET](PLO_BOARDPACKET.md)
