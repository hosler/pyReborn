#!/usr/bin/env python3
"""
PLO_LEVELNAME (Packet 6) - Level name

This packet sets the current level name. It's sent when a player enters
a new level or when the server needs to update the level context.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


PLO_LEVELNAME = PacketStructure(
    packet_id=6,
    name="PLO_LEVELNAME",
    fields=[
        variable_data_field("level_name", "Null-terminated level name")
    ],
    description="Current level name",
    variable_length=True
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse level name with business logic for session tracking.
    
    This function processes level name updates from the server and provides
    the necessary events for session management and GMAP integration.
    
    Args:
        data: Raw parsed fields from packet
        
    Returns:
        Dictionary with processed level name and events
    """
    try:
        # Extract level name
        level_name_raw = data.get('level_name', b'')
        if isinstance(level_name_raw, bytes):
            level_name = level_name_raw.decode('latin-1', errors='replace').strip('\x00')
        else:
            level_name = str(level_name_raw).strip('\x00')
        
        # Throttle repetitive level name messages (time-based)
        import time
        current_time = time.time()
        throttle_key = f"_last_level_log_{level_name}"
        
        if not hasattr(parse, throttle_key) or current_time - getattr(parse, throttle_key) > 2.0:
            logger.info(f"🏠 PLO_LEVELNAME: Level changed to '{level_name}'")
            setattr(parse, throttle_key, current_time)
        else:
            logger.debug(f"🏠 PLO_LEVELNAME: Level '{level_name}' (throttled)")
        
        # Determine if this is a GMAP level
        is_gmap_level = level_name.endswith('.gmap')
        
        # Prepare events to emit
        events_to_emit = []
        
        # Always emit level change event
        events_to_emit.append({
            'type': 'LEVEL_CHANGED',
            'data': {
                'level_name': level_name,
                'is_gmap': is_gmap_level,
                'session_manager_notification': True  # Flag for session manager
            }
        })
        
        # If GMAP level, emit GMAP mode event
        if is_gmap_level:
            events_to_emit.append({
                'type': 'GMAP_MODE_ENTERED',
                'data': {
                    'gmap_name': level_name,
                    'awaiting_coordinates': True  # Will be resolved when coordinates arrive
                }
            })
            logger.debug(f"🗺️ Detected GMAP level: {level_name}")
        else:
            events_to_emit.append({
                'type': 'SINGLE_LEVEL_MODE',
                'data': {
                    'level_name': level_name
                }
            })
            logger.debug(f"🏠 Detected single level: {level_name}")
        
        return {
            'level_name': level_name,
            'is_gmap': is_gmap_level,
            'events': events_to_emit
        }
        
    except Exception as e:
        logger.error(f"Error parsing level name packet: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': str(e),
            'level_name': '',
            'events': []
        }


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELNAME packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELNAME.packet_id,
        'packet_name': PLO_LEVELNAME.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LEVELNAME.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result
