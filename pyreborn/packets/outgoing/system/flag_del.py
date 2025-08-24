"""
PLI_FLAGDEL - Flag Delete Packet

This packet deletes a server flag.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class FlagDelBuilder:
    """Custom builder for FlagDel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build FlagDel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_FLAGDEL + 32)  # Packet ID + 32
        
        # Get flag name
        flag_name = packet.get_field('flag_name') or ""
        
        # Add flag name as GSTRING
        data.append(len(flag_name) + 32)
        data.extend(flag_name.encode('ascii', errors='replace'))
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the FlagDel packet structure
PLI_FLAGDEL = OutgoingPacketStructure(
    packet_id=19,
    name="PLI_FLAGDEL",
    description="Delete a server flag",
    fields=[
        OutgoingPacketField(
            name="flag_name",
            field_type=PacketFieldType.STRING_GCHAR_LEN,
            description="Name of the flag to delete",
            default=""
        )
    ],
    variable_length=True,
    builder_class=FlagDelBuilder
)


class FlagDelPacketHelper:
    """Helper class for easier FlagDel packet construction"""
    
    @staticmethod
    def create(flag_name: str) -> OutgoingPacket:
        """Create a new FlagDel packet
        
        Args:
            flag_name: Name of the flag to delete
        """
        return PLI_FLAGDEL.create_packet(flag_name=flag_name)


# Export the helper
FlagDelPacket = FlagDelPacketHelper