#!/usr/bin/env python3
"""
PLO_UNKNOWN190 (Packet 190) - Blank packet sent before weapon list
"""

from ...base import PacketStructure

PLO_UNKNOWN190 = PacketStructure(
    packet_id=190,
    name="PLO_UNKNOWN190",
    fields=[],  # Blank packet
    description="Blank packet sent before weapon list",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> dict:
    """Parse blank packet sent before weapon list"""
    return {
        'packet_id': 190,
        'packet_name': 'PLO_UNKNOWN190',
        'parsed_data': {},  # Blank packet
        'fields': {}
    }