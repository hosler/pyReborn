#!/usr/bin/env python3
"""
PLO_EVENTTRIGGER (Packet 76) - Event system trigger

This packet triggers server-side events and actions.
Used for quest systems, scripted events, and dynamic content.

The packet format is:
- Event ID (GSHORT) - unique identifier for the event
- Event type (GCHAR) - category/type of event
- Event data (VARIABLE_DATA) - event parameters, conditions, and actions
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_EVENTTRIGGER = PacketStructure(
    packet_id=76,
    name="PLO_EVENTTRIGGER",
    fields=[
        gshort_field("event_id", "Unique identifier for the event"),
        gchar_field("event_type", "Category/type of event"),
        variable_data_field("event_data", "Event parameters and actions")
    ],
    description="Event system trigger and management",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_EVENTTRIGGER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_EVENTTRIGGER.packet_id,
        'packet_name': PLO_EVENTTRIGGER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_EVENTTRIGGER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
