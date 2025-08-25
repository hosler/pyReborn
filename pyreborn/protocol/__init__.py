"""
Protocol Module - All protocol handling and processing

This module consolidates all protocol-related functionality:
- Packet processing and parsing
- Protocol state management
- Binary data handling
- Packet analysis and metrics
"""

from .packet_processor import PacketProcessor
# Temporarily disabled - uses old packet system
# from .protocol_state import ProtocolState
# Packet analyzer removed for simplicity
from .binary_reader import BinaryPacketReader
# Unified reader removed for simplicity

__all__ = [
    'PacketProcessor',
    'BinaryPacketReader',
]