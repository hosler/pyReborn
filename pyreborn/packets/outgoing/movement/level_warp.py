"""
PLI_LEVELWARP - Level Warp Packet

This packet is sent when the player warps to a new level or position.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_coord(value: float) -> int:
    """Encode coordinate (tiles * 2)"""
    return max(0, min(255, int(value * 2)))


def encode_transition(value: str) -> str:
    """Encode transition effect"""
    return str(value)[:20]


# Define the LevelWarp packet structure
PLI_LEVELWARP = OutgoingPacketStructure(
    packet_id=0,
    name="PLI_LEVELWARP",
    description="Warp to a new level or position",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.BYTE,
            description="X coordinate in half-tiles",
            encoder=encode_coord
        ),
        OutgoingPacketField(
            name="y", 
            field_type=PacketFieldType.BYTE,
            description="Y coordinate in half-tiles",
            encoder=encode_coord
        ),
        OutgoingPacketField(
            name="level_name",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Target level name",
            default=""
        ),
        OutgoingPacketField(
            name="transition",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Transition effect",
            default="",
            encoder=encode_transition
        )
    ],
    variable_length=True
)


class LevelWarpPacketHelper:
    """Helper class for easier LevelWarp packet construction"""
    
    @staticmethod
    def create(x: float, y: float, level_name: str = "", transition: str = ""):
        """Create a LevelWarp packet
        
        Args:
            x: X coordinate in tiles
            y: Y coordinate in tiles
            level_name: Target level name (empty for same level)
            transition: Transition effect
        """
        return PLI_LEVELWARP.create_packet(
            x=x, y=y, level_name=level_name, transition=transition
        )


# Export the helper for easier imports
LevelWarpPacket = LevelWarpPacketHelper