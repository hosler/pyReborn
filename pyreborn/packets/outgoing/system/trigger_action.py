"""
PLI_TRIGGERACTION - Trigger Action Packet

This packet triggers server-side actions or scripts.
Used for NPC interactions, weapon actions, and server events.
"""

import logging
from typing import List, Any
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class TriggerActionBuilder:
    """Custom builder for TriggerAction packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build TriggerAction packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_TRIGGERACTION + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        action = packet.get_field('action') or ""
        params = packet.get_field('params') or []
        
        # Add position (in half-tiles)
        data.append(int(x * 2) + 32)
        data.append(int(y * 2) + 32)
        
        # Add action string
        data.append(len(action) + 32)
        data.extend(action.encode('ascii', errors='replace'))
        
        # Add parameters (comma-separated)
        if params:
            param_str = ",".join(str(p) for p in params)
            data.append(len(param_str) + 32)
            data.extend(param_str.encode('ascii', errors='replace'))
        
        # End packet with newline
        data.append(10)
        return bytes(data)


def encode_params_field(params: List[Any]) -> List[str]:
    """Encoder function to convert params to strings"""
    return [str(p) for p in params] if params else []


# Define the TriggerAction packet structure
PLI_TRIGGERACTION = OutgoingPacketStructure(
    packet_id=38,
    name="PLI_TRIGGERACTION",
    description="Trigger a server-side action",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="action",
            field_type=PacketFieldType.STRING_GCHAR_LEN,
            description="Action name/identifier",
            default=""
        ),
        OutgoingPacketField(
            name="params",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Action parameters",
            default=[],
            encoder=encode_params_field
        )
    ],
    variable_length=True,
    builder_class=TriggerActionBuilder
)


class TriggerActionPacketHelper:
    """Helper class for easier TriggerAction packet construction"""
    
    @staticmethod
    def create(x: float = 0, y: float = 0, action: str = "", 
               params: List[Any] = None) -> OutgoingPacket:
        """Create a new TriggerAction packet
        
        Args:
            x: X coordinate (in tiles)
            y: Y coordinate (in tiles)
            action: Action name/identifier
            params: List of parameters for the action
        """
        return PLI_TRIGGERACTION.create_packet(
            x=x, y=y, action=action, params=params or []
        )
    
    @staticmethod
    def trigger_npc(npc_id: int, action: str = "activate") -> OutgoingPacket:
        """Create packet to trigger an NPC action
        
        Args:
            npc_id: ID of the NPC
            action: Action to trigger
        """
        return TriggerActionPacketHelper.create(
            action=f"npc_{action}",
            params=[npc_id]
        )
    
    @staticmethod
    def trigger_weapon(weapon_name: str, action: str = "use") -> OutgoingPacket:
        """Create packet to trigger a weapon action
        
        Args:
            weapon_name: Name of the weapon
            action: Action to trigger
        """
        return TriggerActionPacketHelper.create(
            action=f"weapon_{action}",
            params=[weapon_name]
        )


# Export the helper
TriggerActionPacket = TriggerActionPacketHelper