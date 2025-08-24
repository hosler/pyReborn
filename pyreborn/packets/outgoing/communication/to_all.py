"""
PLI_TOALL - Send Chat Message to All Players

Simple packet for sending chat messages that all players can see.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_message_field(message: str) -> str:
    """Encoder for chat messages - ensures proper encoding"""
    if not isinstance(message, str):
        return str(message)
    # Limit message length for safety
    return message[:200] if len(message) > 200 else message


# Define the ToAll packet structure
PLI_TOALL = OutgoingPacketStructure(
    packet_id=6,
    name="PLI_TOALL",
    description="Send chat message to all players",
    fields=[
        OutgoingPacketField(
            name="message",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Chat message to send",
            encoder=encode_message_field
        )
    ],
    variable_length=True  # Reborn string field has its own terminator
)


class ToAllPacketHelper:
    """Helper class for easier ToAll packet construction"""
    
    @staticmethod
    def create(message: str):
        """Create a ToAll packet with message"""
        return PLI_TOALL.create_packet(message=message)


# Export the helper for easier imports
ToAllPacket = ToAllPacketHelper