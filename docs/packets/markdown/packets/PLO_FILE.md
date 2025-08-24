# PLO_FILE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 102
- **Category**: files
- **Variable Length**: Yes
- **Description**: File transfer packet (needs special handling)

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| file_data | VARIABLE_DATA | File transfer data (complex structure) |

## Implementation

✅ **Custom parse() function implemented**

This packet has business logic processing.

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(102)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PROFILE](PLO_PROFILE.md)
- [PLO_LARGEFILESTART](PLO_LARGEFILESTART.md)
- [PLO_FILEUPTODATE](PLO_FILEUPTODATE.md)
- [PLO_LARGEFILESIZE](PLO_LARGEFILESIZE.md)
- [PLO_RAWDATA](PLO_RAWDATA.md)
