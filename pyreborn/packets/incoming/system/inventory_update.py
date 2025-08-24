#!/usr/bin/env python3
"""
PLO_INVENTORYUPDATE (Packet 78) - Inventory system update

This packet updates player inventory contents and status.
Used for item management, storage, and equipment systems.

The packet format is:
- Inventory slot (GCHAR) - slot number or inventory section
- Item ID (GSHORT) - unique identifier for the item
- Item quantity (GCHAR) - number of items in slot
- Item data (VARIABLE_DATA) - item properties, stats, and metadata
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_INVENTORYUPDATE = PacketStructure(
    packet_id=78,
    name="PLO_INVENTORYUPDATE",
    fields=[
        gchar_field("inventory_slot", "Slot number or inventory section"),
        gshort_field("item_id", "Unique identifier for the item"),
        gchar_field("item_quantity", "Number of items in slot"),
        variable_data_field("item_data", "Item properties and metadata")
    ],
    description="Inventory system update and management",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_INVENTORYUPDATE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_INVENTORYUPDATE.packet_id,
        'packet_name': PLO_INVENTORYUPDATE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_INVENTORYUPDATE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
