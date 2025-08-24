"""
PLI_FLAGSET - Set Server Flag Packet

This packet is sent to set a server flag value.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_flag_name(name: str) -> str:
    """Ensure flag name is valid"""
    # Limit length and remove invalid characters
    name = str(name).strip()[:50]
    return name


# Define the FlagSet packet structure
PLI_FLAGSET = OutgoingPacketStructure(
    packet_id=18,
    name="PLI_FLAGSET",
    description="Set a server flag",
    fields=[
        OutgoingPacketField(
            name="flag_name",
            field_type=PacketFieldType.STRING_LEN,
            description="Name of the flag to set",
            encoder=encode_flag_name
        ),
        OutgoingPacketField(
            name="value",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Value to set (empty string to delete flag)",
            default=""
        )
    ],
    variable_length=True
)


class FlagSetPacketHelper:
    """Helper class for easier FlagSet packet construction"""
    
    @staticmethod
    def create(flag_name: str, value: str = ""):
        """Create a FlagSet packet
        
        Args:
            flag_name: Name of the flag to set
            value: Value to set (empty string deletes the flag)
        """
        return PLI_FLAGSET.create_packet(flag_name=flag_name, value=value)


# Export the helper for easier imports
FlagSetPacket = FlagSetPacketHelper