"""
Gameplay Module - All gameplay mechanics and interactions

This module consolidates all gameplay-related functionality:
- Combat system (weapons, projectiles, damage)
- Item management (inventory, items, chests)
- NPC interactions and management
- Game mechanics and rules
"""

# Keep only essential managers
from .combat_manager import CombatManager
from .item_manager import ItemManager
from .npc_manager import NPCManager

__all__ = [
    'CombatManager',
    'ItemManager', 
    'NPCManager',
]