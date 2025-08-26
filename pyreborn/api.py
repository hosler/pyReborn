#!/usr/bin/env python3
"""
PyReborn High-Level API
=======================

High-level convenience functions for common PyReborn operations.
"""

from typing import Optional, List, Dict, Any
from .client import Client, connect_and_login
from .packet_api import PacketAPI
from .models import Player, Level
from .events import EventType

# Create a global packet API instance for convenience
packet_info = PacketAPI()


def quick_connect(host: str = "localhost", port: int = 14900, username: str = "", password: str = "") -> Optional[Client]:
    """
    Quick connection helper using common defaults.
    
    Args:
        host: Server hostname (default: localhost)
        port: Server port (default: 14900)  
        username: Account username (optional)
        password: Account password (optional)
        
    Returns:
        Connected Client or None if failed
    """
    return connect_and_login(host, port, username, password, "6.037")


def get_packet_info(packet_id: int) -> Optional[Any]:
    """
    Get information about a packet.
    
    Args:
        packet_id: Packet ID to look up
        
    Returns:
        Packet information or None if not found
    """
    return packet_info.get_packet_info(packet_id)


def list_packets() -> List[Any]:
    """
    Get list of all available packets.
    
    Returns:
        List of packet information objects
    """
    return packet_info.get_all_packets()


def search_packets(name: str) -> List[Any]:
    """
    Search for packets by name.
    
    Args:
        name: Name pattern to search for
        
    Returns:
        List of matching packets
    """
    return packet_info.find_packets_by_name(name)


def get_registry_stats() -> Dict[str, Any]:
    """
    Get packet registry statistics.
    
    Returns:
        Dictionary of registry statistics
    """
    return packet_info.get_statistics()


# Export commonly used constants
from .protocol.enums import Direction, PlayerProp

# Advanced APIs removed for simplicity - use basic Client class instead
from .protocol.packet_enums import IncomingPackets, OutgoingPackets, ServerToClient, ClientToServer

__all__ = [
    'quick_connect',
    'get_packet_info', 
    'list_packets',
    'search_packets',
    'get_registry_stats',
    'Direction',
    'PlayerProp',
    'ClientBuilder',
    'PresetBuilder',
    'CompressionType',
    'EncryptionGen', 
    'LogLevel',
    'AsyncClient',
    'async_quick_connect',
    'IncomingPackets',
    'OutgoingPackets',
    'ServerToClient',
    'ClientToServer'
]