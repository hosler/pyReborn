# PLO_INVENTORYUPDATE

[← Back to Index](../index.md)

## Overview

- **Packet ID**: 78
- **Category**: unknown
- **Variable Length**: Yes
- **Description**: Inventory system update and management

## Fields

| Field | Type | Description |
|:------|:-----|:------------|
| inventory_slot | GCHAR | Slot number or inventory section |
| item_id | GSHORT | Unique identifier for the item |
| item_quantity | GCHAR | Number of items in slot |
| item_data | VARIABLE_DATA | Item properties and metadata |

## Implementation

❌ **Not implemented**

## Example Usage

```python
from pyreborn.protocol.packets import PACKET_REGISTRY

# Get packet structure
structure = PACKET_REGISTRY.get_structure(78)
print(f"Packet: {structure.name}")
print(f"Fields: {len(structure.fields)}")
```

## Related Packets

- [PLO_PLAYERMOVED](PLO_PLAYERMOVED.md)
- [PLO_NPCACTION](PLO_NPCACTION.md)
- [PLO_NPCDEL](PLO_NPCDEL.md)
- [PLO_HIDENPCS](PLO_HIDENPCS.md)
- [PLO_NPCDEL2](PLO_NPCDEL2.md)
