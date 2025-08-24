"""
PLI_WANTFILE - Request File from Server

Packet for requesting files (levels, images, etc.) from the server.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_filename(filename: str) -> str:
    """Encoder for filenames - ensures proper format"""
    if not isinstance(filename, str):
        return str(filename)
    # Ensure reasonable length
    return filename[:100] if len(filename) > 100 else filename


# Define the WantFile packet structure
PLI_WANTFILE = OutgoingPacketStructure(
    packet_id=23,
    name="PLI_WANTFILE",
    description="Request a file from the server",
    fields=[
        OutgoingPacketField(
            name="filename",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Name of file to request",
            encoder=encode_filename
        )
    ],
    variable_length=True
)


class WantFilePacketHelper:
    """Helper class for easier WantFile packet construction"""
    
    @staticmethod
    def create(filename: str):
        """Create a WantFile packet"""
        return PLI_WANTFILE.create_packet(filename=filename)


# Export the helper for easier imports
WantFilePacket = WantFilePacketHelper