#!/usr/bin/env python3
"""
PLO_GMAPWARP2 (Packet 49) - GMAP warp with world coordinates

This packet is sent when the player enters a GMAP and includes:
- World coordinates (x2, y2)
- GMAP segment positions (gmaplevelx, gmaplevely) 
- GMAP filename
- Z coordinate and other data
"""

from ...base import PacketStructure, PacketField, PacketFieldType, gchar_field, variable_data_field, PacketReader, parse_field
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


PLO_GMAPWARP2 = PacketStructure(
    packet_id=49,
    name="PLO_GMAPWARP2",
    fields=[
        gchar_field("x2", "World X coordinate"),
        gchar_field("y2", "World Y coordinate"),  
        gchar_field("z_plus_50", "Z coordinate + 50"),
        gchar_field("gmaplevelx", "GMAP segment X (map_x)"),
        gchar_field("gmaplevely", "GMAP segment Y (map_y)"),
        variable_data_field("gmap_name", "GMAP filename")
    ],
    description="GMAP warp with world coordinates and segment positions",
    variable_length=True
)


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GMAPWARP2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GMAPWARP2.packet_id,
        'packet_name': PLO_GMAPWARP2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GMAPWARP2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply custom parsing for parsed_data
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse GMAP warp data with full business logic.
    
    This function processes GMAP warp information including:
    - GMAP segment positions for multi-level worlds
    - World coordinates (though often unreliable from server)
    - Z-layer information
    - Events to emit based on the warp
    
    Args:
        data: Raw parsed fields from packet
        
    Returns:
        Dictionary with processed GMAP warp data and events
    """
    try:
        # Extract coordinates - already decoded from GCHAR (32 subtracted)
        x2_raw = data.get('x2', 0)
        y2_raw = data.get('y2', 0)
        z = data.get('z_plus_50', 50) - 50  # Remove the +50 offset
        
        # 🎯 CRITICAL FIX: Divide world coordinates by 2 (half-tiles to tiles)
        x2 = x2_raw / 2.0
        y2 = y2_raw / 2.0
        
        # GMAP segment positions - already decoded from GCHAR
        gmaplevelx = data.get('gmaplevelx', 0)  
        gmaplevely = data.get('gmaplevely', 0)
        
        # GMAP filename
        gmap_name = data.get('gmap_name', b'')
        if isinstance(gmap_name, bytes):
            gmap_name = gmap_name.decode('latin-1', errors='replace').strip()
        
        # Process coordinate information
        # 🎯 CRITICAL FIX: x2/y2 are LOCAL coordinates within segment, not world coordinates
        # Calculate actual world coordinates using segment position
        segment_base_x = gmaplevelx * 64
        segment_base_y = gmaplevely * 64
        
        # Calculate world coordinates: world = segment * 64 + local
        world_x = segment_base_x + x2
        world_y = segment_base_y + y2
        
        logger.info(f"🗺️ PLO_GMAPWARP2: {gmap_name} - Segment({gmaplevelx},{gmaplevely})")
        logger.info(f"   Local coords (corrected): ({x2:.2f}, {y2:.2f}) [was {x2_raw}, {y2_raw}]")
        logger.info(f"   World coords (calculated): ({world_x:.2f}, {world_y:.2f}) = segment({gmaplevelx},{gmaplevely}) * 64 + local({x2:.2f}, {y2:.2f})")
        logger.debug(f"   Segment base: ({segment_base_x}, {segment_base_y})")
        
        # Prepare coordinate info for other systems
        coordinate_info = {
            'in_gmap': True,
            'gmap_name': gmap_name,
            'gmap_segment': (gmaplevelx, gmaplevely),
            'segment_base': (segment_base_x, segment_base_y),
            'z_layer': z,
            'local_coords': (x2, y2),  # Local coordinates within segment
            'world_position': (world_x, world_y),  # Calculated world coordinates
            'raw_world_coords': (world_x, world_y),  # For compatibility
            'reliable': True  # World coordinates now correctly calculated
        }
        
        # Determine events to emit
        events_to_emit = []
        
        # Emit GMAP mode event
        events_to_emit.append({
            'type': 'GMAP_MODE_CHANGED',
            'data': {
                'gmap_name': gmap_name,
                'entering_gmap': True,
                'segment': (gmaplevelx, gmaplevely)
            }
        })
        
        # Emit player warp event
        events_to_emit.append({
            'type': 'PLAYER_WARPED',
            'data': {
                'is_self': True,
                'is_gmap_warp': True,
                'gmap_name': gmap_name,
                'segment': (gmaplevelx, gmaplevely),
                'coordinate_info': coordinate_info
            }
        })
        
        return {
            'gmap_name': gmap_name,
            'gmaplevelx': gmaplevelx,  # GMAP segment X
            'gmaplevely': gmaplevely,  # GMAP segment Y
            'z': z,
            'x2': world_x,  # World X coordinate (calculated from segment + local)
            'y2': world_y,  # World Y coordinate (calculated from segment + local)
            'local_x': x2,  # Local X coordinate within segment
            'local_y': y2,  # Local Y coordinate within segment
            'coordinate_info': coordinate_info,
            'events': events_to_emit,
            'note': 'World coordinates calculated as segment * 64 + local coordinates'
        }
        
    except Exception as e:
        logger.error(f"Error parsing GMAP warp packet: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': str(e),
            'events': []
        }