#!/usr/bin/env python3
"""
PLO_CAMERACONTROL (Packet 70) - Camera control and movement

This packet controls camera position and movement.
Used for cinematic effects, focus changes, and view manipulation.

The packet format is:
- Camera command (GCHAR) - type of camera control
- Camera X (GSHORT) - target X position for camera
- Camera Y (GSHORT) - target Y position for camera
- Camera data (VARIABLE_DATA) - zoom, speed, and transition settings
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


PLO_CAMERACONTROL = PacketStructure(
    packet_id=70,
    name="PLO_CAMERACONTROL",
    fields=[
        gchar_field("camera_command", "Type of camera control"),
        gshort_field("camera_x", "Target X position for camera"),
        gshort_field("camera_y", "Target Y position for camera"),
        variable_data_field("camera_data", "Zoom, speed, and transition settings")
    ],
    description="Camera control and movement",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_CAMERACONTROL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_CAMERACONTROL.packet_id,
        'packet_name': PLO_CAMERACONTROL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_CAMERACONTROL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
