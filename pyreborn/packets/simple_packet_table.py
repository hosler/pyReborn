#!/usr/bin/env python3
"""
Simple Packet Table - Table-driven parsing for basic packets
============================================================

Replaces 80+ individual packet files with a single table-driven system.
Only complex packets like PLO_PLAYERPROPS and PLO_GMAPWARP2 need individual files.
"""

from typing import Dict, Any, List, Tuple
from .base import PacketFieldType

# Use the actual field types from base.py  
FieldType = PacketFieldType  # Alias for table readability

# Table-driven packet definitions (replaces individual files)
SIMPLE_PACKET_TABLE = {
    # System packets
    57: {  # PLO_ADMINMESSAGE
        'name': 'PLO_ADMINMESSAGE',
        'fields': [
            ('admin_name', FieldType.STRING_GCHAR_LEN),
            ('message_content', FieldType.STRING_GCHAR_LEN)
        ]
    },
    
    62: {  # PLO_PLAYERSTATUS  
        'name': 'PLO_PLAYERSTATUS',
        'fields': [
            ('player_id', FieldType.GSHORT),
            ('status_flags', FieldType.GCHAR),
            ('status_message', FieldType.STRING_GCHAR_LEN)
        ]
    },
    
    82: {  # PLO_PRIVATEMESSAGE
        'name': 'PLO_PRIVATEMESSAGE',
        'fields': [
            ('sender_name', FieldType.STRING_GCHAR_LEN),
            ('message_content', FieldType.STRING_GCHAR_LEN)
        ]
    },
    
    60: {  # PLO_PLAYERRIGHTS
        'name': 'PLO_PLAYERRIGHTS',
        'fields': [
            ('rights_data', FieldType.VARIABLE_DATA)
        ]
    },
    
    25: {  # PLO_SIGNATURE
        'name': 'PLO_SIGNATURE',
        'fields': [
            ('signature_data', FieldType.VARIABLE_DATA)
        ]
    },
    
    42: {  # PLO_NEWWORLDTIME
        'name': 'PLO_NEWWORLDTIME',
        'fields': [
            ('world_time', FieldType.GINT4)
        ]
    },
    
    # Combat packets
    17: {  # PLO_HORSEADD
        'name': 'PLO_HORSEADD',
        'fields': [
            ('horse_data', FieldType.VARIABLE_DATA)
        ]
    },
    
    18: {  # PLO_HORSEDEL
        'name': 'PLO_HORSEDEL',
        'fields': [
            ('horse_id', FieldType.GSHORT)
        ]
    },
    
    # Add more simple packets here as needed...
}

def parse_simple_packet(packet_id: int, data: bytes) -> Dict[str, Any]:
    """
    Parse a simple packet using table-driven approach.
    
    Returns None if packet_id is not in simple table (needs individual parser).
    """
    if packet_id not in SIMPLE_PACKET_TABLE:
        return None
        
    packet_def = SIMPLE_PACKET_TABLE[packet_id]
    result = {
        'packet_id': packet_id,
        'packet_name': packet_def['name'],
        'fields': {}
    }
    
    offset = 0
    
    for field_name, field_type in packet_def['fields']:
        try:
            if field_type == FieldType.GCHAR:
                if offset < len(data):
                    result['fields'][field_name] = data[offset]
                    offset += 1
                    
            elif field_type == FieldType.GSHORT:
                if offset + 1 < len(data):
                    result['fields'][field_name] = int.from_bytes(data[offset:offset+2], 'little')
                    offset += 2
                    
            elif field_type == FieldType.GINT4:
                if offset + 3 < len(data):
                    result['fields'][field_name] = int.from_bytes(data[offset:offset+4], 'little')
                    offset += 4
                    
            elif field_type == FieldType.STRING_GCHAR_LEN:
                if offset < len(data):
                    length = data[offset]
                    offset += 1
                    if offset + length <= len(data):
                        result['fields'][field_name] = data[offset:offset+length].decode('utf-8', errors='ignore')
                        offset += length
                        
            elif field_type == PacketFieldType.STRING_LEN:  # Use the actual enum value
                if offset + 1 < len(data):
                    length = int.from_bytes(data[offset:offset+2], 'little')
                    offset += 2
                    if offset + length <= len(data):
                        result['fields'][field_name] = data[offset:offset+length].decode('utf-8', errors='ignore')
                        offset += length
                        
            elif field_type == FieldType.VARIABLE_DATA:
                result['fields'][field_name] = data[offset:]
                break  # Variable data consumes rest of packet
                
        except Exception:
            # Parse what we can, ignore errors in simple packets
            break
    
    return result

def is_simple_packet(packet_id: int) -> bool:
    """Check if packet uses table-driven parsing"""
    return packet_id in SIMPLE_PACKET_TABLE

def get_simple_packet_name(packet_id: int) -> str:
    """Get packet name for simple packets"""
    return SIMPLE_PACKET_TABLE.get(packet_id, {}).get('name', f'PACKET_{packet_id}')