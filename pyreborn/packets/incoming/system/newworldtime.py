"""
PLO_NEWWORLDTIME packet (ID 42) - Server heartbeat/time sync
"""

from typing import Dict, Any
from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field

PLO_NEWWORLDTIME = PacketStructure(
    packet_id=42,
    name="PLO_NEWWORLDTIME",
    description="Server heartbeat and world time synchronization packet (sent ~1/sec)",
    fields=[
        PacketField("world_time", PacketFieldType.GINT5, "Current world time in server ticks")
    ]
)


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse NEWWORLDTIME packet data"""
    world_time = data.get('world_time', 0)
    
    # Convert ticks to seconds (assuming 20 ticks per second like many game servers)
    seconds = world_time / 20.0 if world_time else 0
    
    # Calculate hours, minutes, seconds for display
    hours = int(seconds // 3600) % 24
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    return {
        'world_time': world_time,
        'time_seconds': seconds,
        'time_formatted': f"{hours:02d}:{minutes:02d}:{secs:02d}",
        'is_heartbeat': True  # This packet serves as a heartbeat
    }


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NEWWORLDTIME packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NEWWORLDTIME.packet_id,
        'packet_name': PLO_NEWWORLDTIME.name,
        'fields': {}
    }
    
    # Parse the raw fields first
    for field in PLO_NEWWORLDTIME.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply custom parsing logic
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result