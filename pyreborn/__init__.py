"""
PyReborn - Python library for connecting to Reborn servers

This library provides a comprehensive Python interface for interacting with
Graal Reborn servers, including support for movement, chat, combat, items,
NPCs, and GMAP (multi-level world) systems.

Architecture:
- RebornClient is the main unified interface (incorporates former V2 features)
- V1 client is available for legacy compatibility
- Clean modular structure with core, protocol, models, managers, and actions
"""

# Core API (unified client)
from .core import RebornClient, EventManager, EventType
from .models import Player, Level
from .managers import SessionManager, LevelManager, ItemManager, CombatManager, NPCManager
from .actions import PlayerActions, ItemActions, CombatActions, NPCActions
from .serverlist import ServerListClient, ServerInfo

# Note: V2 has been merged into the main RebornClient - no separate v2 client needed

# Legacy V1 support
from .core.client import RebornClient

# Protocol and utilities
from .protocol.enums import Direction, PlayerProp
from .utils import GMAPUtils

__version__ = "3.0.0"  # Major version bump for reorganization
__author__ = "PyReborn Contributors"
__license__ = "MIT"

__all__ = [
    # Core API (unified client)
    'RebornClient',         # Main client class (unified)
    'EventManager',         # Event system
    'EventType',            # Event type constants
    
    # Models
    'Player',               # Player data model
    'Level',                # Level data model
    
    # Managers
    'SessionManager',       # Session state management
    'LevelManager',         # Level management
    'ItemManager',          # Item management
    'CombatManager',        # Combat management
    'NPCManager',           # NPC management
    
    # Actions (High-level API)
    'PlayerActions',        # Player action commands
    'ItemActions',          # Item interaction commands
    'CombatActions',        # Combat commands
    'NPCActions',           # NPC interaction commands
    
    # Server Discovery
    'ServerListClient',     # Server list client
    'ServerInfo',           # Server information
    
    # Legacy clients
    'RebornClientV1',       # V1 client (legacy)
    
    # Protocol
    'Direction',            # Direction constants
    'PlayerProp',           # Player property constants
    
    # Utilities
    'GMAPUtils',            # GMAP utilities
]

# Convenience functions
def connect(host: str, port: int = 14900, version: str = "2.19") -> RebornClient:
    """
    Create and return a new RebornClient instance.
    
    Args:
        host: Server hostname or IP
        port: Server port (default 14900)
        version: Client version string (default "2.19")
        
    Returns:
        RebornClient: A new client instance ready to connect
    """
    return RebornClient(host, port, version)

def connect_and_login(host: str, port: int = 14900, 
                     account: str = None, password: str = None,
                     version: str = "2.19") -> RebornClient:
    """
    Create a client, connect, and login in one step.
    
    Args:
        host: Server hostname or IP  
        port: Server port (default 14900)
        account: Account name
        password: Account password
        version: Client version string (default "2.19")
        
    Returns:
        RebornClient: A connected and logged-in client instance
        
    Raises:
        ConnectionError: If connection or login fails
    """
    client = RebornClient(host, port, version)
    if not client.connect():
        raise ConnectionError(f"Failed to connect to {host}:{port}")
    if account and password:
        if not client.login(account, password):
            raise ConnectionError("Login failed")
    return client