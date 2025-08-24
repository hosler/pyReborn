"""
PLI_NPCPROPS - NPC Properties Packet

This packet updates NPC properties on the server.
Used to change NPC position, appearance, script variables, etc.
"""

import logging
from typing import Dict, Any, List, Tuple
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class NpcPropsBuilder:
    """Custom builder for NpcProps packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build NpcProps packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_NPCPROPS + 32)  # Packet ID + 32
        
        # Get fields
        npc_id = packet.get_field('npc_id') or 0
        properties = packet.get_field('properties') or []
        
        # Add NPC ID as GUINT (3 bytes)
        data.append((npc_id >> 14) + 32)
        data.append(((npc_id >> 7) & 0x7F) + 32)
        data.append((npc_id & 0x7F) + 32)
        
        # Add properties
        # Properties are encoded similarly to player props
        for prop_id, value in properties:
            data.append(prop_id + 32)  # Property ID + 32
            
            if isinstance(value, str):
                # String property with length
                data.append(len(value) + 32)
                data.extend(value.encode('ascii', errors='replace'))
            elif isinstance(value, (int, float)):
                # Numeric property
                if prop_id in [0, 1]:  # X, Y positions (half-tiles)
                    data.append(int(value * 2) + 32)
                else:
                    data.append(int(value) + 32)
            elif isinstance(value, bytes):
                # Raw bytes
                data.extend(value)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


def encode_properties_field(properties: List[Tuple[int, Any]]) -> List[Tuple[int, Any]]:
    """Encoder function to ensure properties are properly formatted"""
    return properties if properties else []


# Define the NpcProps packet structure
PLI_NPCPROPS = OutgoingPacketStructure(
    packet_id=3,
    name="PLI_NPCPROPS",
    description="Update NPC properties",
    fields=[
        OutgoingPacketField(
            name="npc_id",
            field_type=PacketFieldType.GINT3,
            description="ID of the NPC to update",
            default=0
        ),
        OutgoingPacketField(
            name="properties",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="List of (property_id, value) tuples",
            default=[],
            encoder=encode_properties_field
        )
    ],
    variable_length=True,
    builder_class=NpcPropsBuilder
)


class NpcPropsPacketHelper:
    """Helper class for easier NpcProps packet construction"""
    
    # Common NPC property IDs
    PROP_X = 0
    PROP_Y = 1
    PROP_IMAGE = 2
    PROP_SCRIPT = 3
    PROP_VISIBILITY = 4
    PROP_BLOCKFLAGS = 5
    
    @staticmethod
    def create(npc_id: int, properties: List[Tuple[int, Any]] = None) -> OutgoingPacket:
        """Create a new NpcProps packet
        
        Args:
            npc_id: ID of the NPC
            properties: List of (property_id, value) tuples
        """
        return PLI_NPCPROPS.create_packet(
            npc_id=npc_id,
            properties=properties or []
        )
    
    @staticmethod
    def move_npc(npc_id: int, x: float, y: float) -> OutgoingPacket:
        """Create packet to move an NPC
        
        Args:
            npc_id: ID of the NPC
            x: New X position (in tiles)
            y: New Y position (in tiles)
        """
        return NpcPropsPacketHelper.create(npc_id, [
            (NpcPropsPacketHelper.PROP_X, x),
            (NpcPropsPacketHelper.PROP_Y, y)
        ])
    
    @staticmethod
    def set_npc_image(npc_id: int, image: str) -> OutgoingPacket:
        """Create packet to change NPC image
        
        Args:
            npc_id: ID of the NPC
            image: Image filename
        """
        return NpcPropsPacketHelper.create(npc_id, [
            (NpcPropsPacketHelper.PROP_IMAGE, image)
        ])
    
    @staticmethod
    def hide_npc(npc_id: int) -> OutgoingPacket:
        """Create packet to hide an NPC
        
        Args:
            npc_id: ID of the NPC
        """
        return NpcPropsPacketHelper.create(npc_id, [
            (NpcPropsPacketHelper.PROP_VISIBILITY, 0)
        ])


# Export the helper
NpcPropsPacket = NpcPropsPacketHelper