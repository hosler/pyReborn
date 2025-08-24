#!/usr/bin/env python3
"""
PLO_BADDYPROPS (Packet 2) - Baddy (enemy/NPC) properties

This packet updates properties of baddies (enemies/hostile NPCs).
Contains movement, animation, and state information.

The packet format is:
- Baddy ID (GSHORT) - unique identifier for the baddy
- Baddy X (GSHORT) - X coordinate position
- Baddy Y (GSHORT) - Y coordinate position
- Baddy type (GCHAR) - baddy type/class identifier
- Baddy props (VARIABLE_DATA) - encoded properties (animation, health, etc.)
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


PLO_BADDYPROPS = PacketStructure(
    packet_id=2,
    name="PLO_BADDYPROPS",
    fields=[
        gshort_field("baddy_id", "Unique baddy identifier"),
        gshort_field("baddy_x", "Baddy X coordinate"),
        gshort_field("baddy_y", "Baddy Y coordinate"),
        gchar_field("baddy_type", "Baddy type/class"),
        variable_data_field("baddy_props", "Encoded baddy properties")
    ],
    description="Baddy (enemy/NPC) properties and state",
    variable_length=True
)


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BADDYPROPS packet from raw bytes
    
    Baddies are server-controlled NPCs in Reborn. 
    
    Traditional baddy format (46 bytes):
    - ID (3 bytes GINT3)
    - X position (1 byte GCHAR) - in half-tiles
    - Y position (1 byte GCHAR) - in half-tiles
    - Type (1 byte GCHAR)
    - Power (1 byte GCHAR)
    - Direction (1 byte GCHAR)
    - Mode/Animation (1 byte GCHAR)
    - Image string (remaining bytes)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        reader = PacketReader(data)
        
        # Read baddy ID (3 bytes)
        baddy_id = reader.read_gint3()
        
        # Read fixed properties
        x_pos = reader.read_gchar() / 2.0  # Half-tiles to tiles
        y_pos = reader.read_gchar() / 2.0  # Half-tiles to tiles
        baddy_type = reader.read_gchar()
        power = reader.read_gchar()
        direction = reader.read_gchar()
        mode = reader.read_gchar()
        
        # Rest is the image string
        image_string = reader.read_remaining().decode('ascii', errors='ignore')
        
        # Build properties dict
        properties = {
            'x': x_pos,
            'y': y_pos,
            'type': baddy_type,
            'power': power,
            'direction': direction,
            'mode': mode,
            'image': image_string
        }
        
        logger.info(f"Parsed baddy {baddy_id} at ({x_pos:.1f}, {y_pos:.1f}), type={baddy_type}, image='{image_string}'")
        
        return {
            'packet_id': PLO_BADDYPROPS.packet_id,
            'packet_name': PLO_BADDYPROPS.name,
            'parsed_data': {
                'baddy_id': baddy_id,
                'properties': properties
            },
            'fields': {
                'baddy_id': baddy_id,
                'baddy_x': x_pos,
                'baddy_y': y_pos,
                'baddy_type': baddy_type,
                'baddy_props': properties
            }
        }
    except Exception as e:
        logger.error(f"Error parsing baddy props: {e}")
        return {
            'packet_id': PLO_BADDYPROPS.packet_id,
            'packet_name': PLO_BADDYPROPS.name,
            'parsed_data': {},
            'fields': {}
        }
