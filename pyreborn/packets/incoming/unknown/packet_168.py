#!/usr/bin/env python3
"""
PLO_UNKNOWN168 (Packet 168) - Blank packet from login server
"""

from ...base import PacketStructure

PLO_UNKNOWN168 = PacketStructure(
    packet_id=168,
    name="PLO_UNKNOWN168",
    fields=[],  # Blank packet
    description="Blank packet sent by login server",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> dict:
    """Parse blank packet from login server"""
    return {
        'packet_id': 168,
        'packet_name': 'PLO_UNKNOWN168',
        'parsed_data': {},  # Blank packet
        'fields': {}
    }