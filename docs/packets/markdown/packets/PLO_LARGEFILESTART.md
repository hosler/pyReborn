# PLO_LARGEFILESTART

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 68
- **Category**: files
- **Variable Length**: Yes
- **Description**: Start of large file transfer

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| file_name | STRING_GCHAR_LEN | Name of the large file |
| total_file_size | GINT4 | Total size of file in bytes |
| chunk_size | GSHORT | Size of each chunk to follow |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(68)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_FILE](PLO_FILE.md)
- [PLO_LARGEFILESIZE](PLO_LARGEFILESIZE.md)
- [PLO_RAWDATA](PLO_RAWDATA.md)
- [PLO_LARGEFILEEND](PLO_LARGEFILEEND.md)
- [PLO_BOARDPACKET](PLO_BOARDPACKET.md)
