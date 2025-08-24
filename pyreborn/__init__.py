"""
PyReborn - Simple Python client for Reborn servers
==================================================

PyReborn provides a clean, simple interface for connecting to Reborn Reborn servers.
The library handles all the complex protocol details internally, exposing only 
what users actually need.

Quick Start:
    from pyreborn import Client
    
    client = Client("localhost", 14900)
    client.connect()
    client.login("username", "password")
    
    # Move player
    client.move(1, 0)
    
    # Chat  
    client.say("Hello!")
    
    # Get player info
    player = client.get_player()
    print(f"Player: {player.account} at ({player.x}, {player.y})")

Advanced Usage:
    from pyreborn import quick_connect, Direction, EventType
    
    # Quick connection
    client = quick_connect("localhost", 14900, "user", "pass")
    
    # Event handling
    def on_chat(event_data):
        print(f"Chat: {event_data}")
    
    client.on_event(EventType.PLAYER_CHAT, on_chat)
"""

# Simple public API - this is all users should need to import
from .client import Client, connect_and_login
from .models import Player, Level  
from .events import EventType
from .api import quick_connect, Direction, PlayerProp
# Import from the new advanced_api/ directory
from .advanced_api import ClientBuilder, PresetBuilder

# Legacy compatibility (for existing code)
try:
    from .core.reborn_client import RebornClient
except ImportError:
    from .core.simple_consolidated_client import SimpleConsolidatedClient as RebornClient
from .compat.legacy_client import LegacyRebornClient

# Version info
__version__ = "3.0.0"
__author__ = "PyReborn Contributors"  
__license__ = "MIT"

# What users can import directly
__all__ = [
    # Main client
    'Client',                # Simple client (RECOMMENDED)
    'connect_and_login',     # Connection helper
    'quick_connect',         # Quick connection with defaults
    
    # Data models
    'Player',                # Player data
    'Level',                 # Level data
    
    # Events  
    'EventType',             # Event type constants
    
    # Constants
    'Direction',             # Direction constants
    'PlayerProp',            # Player property constants
    
    # Legacy clients (backward compatibility)
    'RebornClient',          # Modern client (direct access)
    'LegacyRebornClient',    # Legacy monolithic client
]

# Simple convenience functions
def connect(host: str = "localhost", port: int = 14900) -> Client:
    """
    Create a new Client instance.
    
    Args:
        host: Server hostname or IP (default: localhost)
        port: Server port (default: 14900)
        
    Returns:
        Client: A new client instance ready to connect
    """
    return Client(host, port)

# Add convenience function to exports
__all__.append('connect')