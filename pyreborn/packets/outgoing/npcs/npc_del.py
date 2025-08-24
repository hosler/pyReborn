"""
PLI_NPCDEL - NPC Delete Packet

This packet requests deletion of an NPC from the server.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class NpcDelBuilder:
    """Custom builder for NpcDel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build NpcDel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_NPCDEL + 32)  # Packet ID + 32
        
        # Get NPC ID
        npc_id = packet.get_field('npc_id') or 0
        
        # Add NPC ID as GUINT (3 bytes)
        data.append((npc_id >> 14) + 32)
        data.append(((npc_id >> 7) & 0x7F) + 32)
        data.append((npc_id & 0x7F) + 32)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the NpcDel packet structure
PLI_NPCDEL = OutgoingPacketStructure(
    packet_id=22,
    name="PLI_NPCDEL",
    description="Delete an NPC",
    fields=[
        OutgoingPacketField(
            name="npc_id",
            field_type=PacketFieldType.GINT3,
            description="ID of the NPC to delete",
            default=0
        )
    ],
    variable_length=False,
    builder_class=NpcDelBuilder
)


class NpcDelPacketHelper:
    """Helper class for easier NpcDel packet construction"""
    
    @staticmethod
    def create(npc_id: int) -> OutgoingPacket:
        """Create a new NpcDel packet
        
        Args:
            npc_id: ID of the NPC to delete
        """
        return PLI_NPCDEL.create_packet(npc_id=npc_id)


# Export the helper
NpcDelPacket = NpcDelPacketHelper