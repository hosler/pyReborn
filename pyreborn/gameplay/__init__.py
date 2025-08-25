"""
Gameplay Module - All gameplay mechanics and interactions

This module consolidates all gameplay-related functionality:
- Combat system (weapons, projectiles, damage)
- Item management (inventory, items, chests)
- NPC interactions and management
- Game mechanics and rules
"""

# Keep only essential managers
from .item_manager import ItemManager

__all__ = [
    'ItemManager'
]