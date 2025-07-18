"""
pyReborn - Python library for Reborn servers with 100% GServer-v2 coverage
"""

from .client import RebornClient
from .events import EventType
from .tile_mapping import TileMapping, TileInfo, TilesetMapper, load_reborn_tiles
from .models.level import Level, LevelLink, Sign, Chest, NPC, Baddy
from .models.player import Player
from .serverlist import ServerListClient, ServerInfo
from .managers import ItemManager, CombatManager, NPCManager

__version__ = "1.0.0"  # Major version bump for full GServer-v2 support!
__all__ = [
    # Core classes
    "RebornClient", "EventType", 
    
    # Tile system
    "TileMapping", "TileInfo", "TilesetMapper", "load_reborn_tiles",
    
    # Models
    "Level", "LevelLink", "Sign", "Chest", "NPC", "Baddy", "Player",
    
    # Server list
    "ServerListClient", "ServerInfo",
    
    # Managers
    "ItemManager", "CombatManager", "NPCManager"
]