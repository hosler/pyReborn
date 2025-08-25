"""
Connection Module - All networking, encryption, and version handling

This module consolidates all connection-related functionality:
- Socket management and connection handling
- Protocol version negotiation
- Encryption and security
- Connection resilience and recovery
"""

# Simplified connection module (kept version manager for login compatibility)
from .connection_manager import ConnectionManager
from .socket_manager import ConnectionManager as SocketManager
from .version_manager import VersionManager  
from .encryption import RebornEncryption
from .versions import get_version_config, get_default_version, ClientType
from .version_codecs import create_codec

__all__ = [
    'ConnectionManager',
    'SocketManager',
    'VersionManager', 
    'RebornEncryption',
    'get_version_config',
    'get_default_version',
    'ClientType',
    'create_codec',
]