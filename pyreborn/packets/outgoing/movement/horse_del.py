"""
PLI_HORSEDEL - Horse Delete Packet

This packet notifies the server that the player has dismounted their horse.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class HorseDelBuilder:
    """Custom builder for HorseDel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build HorseDel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_HORSEDEL + 32)  # Packet ID + 32
        
        # This packet is typically empty - just the packet ID
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the HorseDel packet structure
PLI_HORSEDEL = OutgoingPacketStructure(
    packet_id=8,
    name="PLI_HORSEDEL",
    description="Dismount horse",
    fields=[],  # No fields - empty packet
    variable_length=False,
    builder_class=HorseDelBuilder
)


class HorseDelPacketHelper:
    """Helper class for easier HorseDel packet construction"""
    
    @staticmethod
    def create() -> OutgoingPacket:
        """Create a new HorseDel packet"""
        return PLI_HORSEDEL.create_packet()


# Export the helper
HorseDelPacket = HorseDelPacketHelper