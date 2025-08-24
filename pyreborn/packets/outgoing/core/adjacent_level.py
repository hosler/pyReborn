"""
PLI_ADJACENTLEVEL - Adjacent Level Packet

This packet notifies the server about adjacent levels for seamless transitions.
Used in GMAP systems to preload neighboring levels.
"""

import logging
from typing import List
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class AdjacentLevelBuilder:
    """Custom builder for AdjacentLevel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build AdjacentLevel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_ADJACENTLEVEL + 32)  # Packet ID + 32
        
        # Get adjacent levels list
        levels = packet.get_field('levels') or []
        
        # Add each level name
        for level_name in levels:
            data.append(len(level_name) + 32)
            data.extend(level_name.encode('ascii', errors='replace'))
        
        # End packet with newline
        data.append(10)
        return bytes(data)


def encode_levels_field(levels: List[str]) -> List[str]:
    """Encoder function to ensure levels are properly formatted"""
    return levels if levels else []


# Define the AdjacentLevel packet structure
PLI_ADJACENTLEVEL = OutgoingPacketStructure(
    packet_id=35,
    name="PLI_ADJACENTLEVEL",
    description="Notify server of adjacent levels",
    fields=[
        OutgoingPacketField(
            name="levels",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="List of adjacent level names",
            default=[],
            encoder=encode_levels_field
        )
    ],
    variable_length=True,
    builder_class=AdjacentLevelBuilder
)


class AdjacentLevelPacketHelper:
    """Helper class for easier AdjacentLevel packet construction"""
    
    @staticmethod
    def create(levels: List[str] = None) -> OutgoingPacket:
        """Create a new AdjacentLevel packet
        
        Args:
            levels: List of adjacent level names
        """
        return PLI_ADJACENTLEVEL.create_packet(levels=levels or [])
    
    @staticmethod
    def create_for_gmap(x: int, y: int, gmap_name: str, adjacent_levels: List[str]) -> OutgoingPacket:
        """Create packet for GMAP adjacent levels
        
        Args:
            x: Current GMAP X coordinate (for reference)
            y: Current GMAP Y coordinate (for reference)
            gmap_name: Name of the GMAP file (for reference)
            adjacent_levels: Actual list of adjacent level names from GMAP data
        """
        # Use the provided adjacent levels list instead of guessing names
        return AdjacentLevelPacketHelper.create(adjacent_levels)


# Export the helper
AdjacentLevelPacket = AdjacentLevelPacketHelper