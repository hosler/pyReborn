#!/usr/bin/env python3
"""
PLO_NPCPROPS (Packet 3) - NPC properties

This packet contains NPC property updates, including position,
appearance, and behavior data.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
from typing import Dict, Any


PLO_NPCPROPS = PacketStructure(
    packet_id=3,
    name="PLO_NPCPROPS",
    fields=[
        variable_data_field("properties", "Encoded NPC properties")
    ],
    description="NPC properties update",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCPROPS packet from raw bytes"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        reader = PacketReader(data)
        
        # Read NPC ID (3 bytes)
        npc_id = reader.read_gint3()
        
        # Parse properties
        properties = {}
        while reader.bytes_left() > 0:
            prop_id = reader.read_byte()
            
            # Parse based on property ID
            if prop_id == 0:  # IMAGE
                length = reader.read_gchar()
                properties['image'] = reader.read_string(length)
            elif prop_id == 1:  # SCRIPT
                length = reader.read_gshort()
                properties['script'] = reader.read_string(length)
            elif prop_id == 2:  # NPCX (obsolete, but still sent)
                properties['x'] = reader.read_gchar() / 2.0
            elif prop_id == 3:  # NPCY (obsolete, but still sent)
                properties['y'] = reader.read_gchar() / 2.0
            elif prop_id == 4:  # NPCPOWER
                properties['power'] = reader.read_gchar()
            elif prop_id == 5:  # NPCRUPEES
                properties['rupees'] = reader.read_gint(4)  # 4-byte integer
            elif prop_id == 6:  # ARROWS
                properties['arrows'] = reader.read_gchar()
            elif prop_id == 7:  # BOMBS
                properties['bombs'] = reader.read_gchar()
            elif prop_id == 8:  # GLOVEPOWER
                properties['glove_power'] = reader.read_gchar()
            elif prop_id == 9:  # BOMBPOWER
                properties['bomb_power'] = reader.read_gchar()
            elif prop_id == 10:  # SWORDIMAGE
                length = reader.read_gchar()
                properties['sword_image'] = reader.read_string(length) if length > 0 else ""
            elif prop_id == 11:  # SHIELDIMAGE
                length = reader.read_gchar()
                properties['shield_image'] = reader.read_string(length) if length > 0 else ""
            elif prop_id == 12:  # GANI
                length = reader.read_gchar()
                properties['gani'] = reader.read_string(length)
            elif prop_id == 13:  # VISFLAGS
                properties['vis_flags'] = reader.read_gchar()
            elif prop_id == 14:  # BLOCKFLAGS
                properties['block_flags'] = reader.read_gchar()
            elif prop_id == 15:  # MESSAGE
                length = reader.read_gchar()
                properties['message'] = reader.read_string(length)
            elif prop_id == 16:  # HURTDXDY
                properties['hurt_dx'] = reader.read_gchar()
                properties['hurt_dy'] = reader.read_gchar()
            elif prop_id == 17:  # ID
                properties['npc_id2'] = reader.read_gint(4)  # 4-byte integer
            elif prop_id in range(18, 28):  # SPRITE 0-9
                properties[f'sprite{prop_id - 18}'] = reader.read_gchar()
            elif prop_id in range(28, 33):  # SAVE 0-9 (28-32)
                properties[f'save{prop_id - 28}'] = reader.read_gchar()
            elif prop_id == 34:  # IMAGEPART
                length = reader.read_gchar()
                properties['image_part'] = reader.read_string(length)
            elif prop_id == 35:  # BODY
                length = reader.read_gchar()
                properties['body'] = reader.read_string(length)
            elif prop_id == 36:  # COLORS
                properties['colors'] = [reader.read_gchar() for _ in range(5)]
            elif prop_id == 37:  # NICKNAME
                length = reader.read_gchar()
                properties['nickname'] = reader.read_string(length)
            elif prop_id == 38:  # HORSEIMG
                length = reader.read_gchar()
                properties['horse_img'] = reader.read_string(length)
            elif prop_id == 39:  # HEADIMG
                length = reader.read_gchar()
                properties['head_img'] = reader.read_string(length) 
            elif prop_id == 41:  # GMAPLEVELX
                properties['gmap_level_x'] = reader.read_gchar()
            elif prop_id == 42:  # GMAPLEVELY
                properties['gmap_level_y'] = reader.read_gchar()
            elif prop_id == 75:  # PIXELX
                val = reader.read_gshort()
                properties['pixel_x'] = -(val >> 1) if (val & 1) else (val >> 1)
                properties['x'] = properties['pixel_x'] / 16.0
            elif prop_id == 76:  # PIXELY
                val = reader.read_gshort()
                properties['pixel_y'] = -(val >> 1) if (val & 1) else (val >> 1)
                properties['y'] = properties['pixel_y'] / 16.0
            else:
                # Unknown property, try to skip it
                logger.debug(f"Unknown NPC property ID {prop_id}")
                # We don't know the size, so this might fail
                break
        
        logger.debug(f"Parsed NPC {npc_id} with {len(properties)} properties")
        
        return {
            'packet_id': PLO_NPCPROPS.packet_id,
            'packet_name': PLO_NPCPROPS.name,
            'parsed_data': {
                'npc_id': npc_id,
                'properties': properties
            },
            'fields': {
                'npc_id': npc_id,
                'properties': properties
            }
        }
    except Exception as e:
        logger.error(f"Error parsing NPC props: {e}")
        return {
            'packet_id': PLO_NPCPROPS.packet_id,
            'packet_name': PLO_NPCPROPS.name,
            'parsed_data': {},
            'fields': {}
        }
