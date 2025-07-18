"""
Item management system for PyReborn
"""

from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
import logging
from ..protocol.enums import LevelItemType

logger = logging.getLogger(__name__)


@dataclass
class Item:
    """Represents an item in the game world"""
    x: float
    y: float
    item_type: LevelItemType
    level: str
    id: Optional[int] = None
    
    def __hash__(self):
        return hash((self.x, self.y, self.item_type, self.level))


class ItemManager:
    """Manages items in levels"""
    
    def __init__(self):
        # Items by level
        self._items: Dict[str, Set[Item]] = {}
        
        # Items in player's inventory
        self._inventory: Dict[LevelItemType, int] = {}
        
        # Picked up items (to avoid re-pickup)
        self._picked_up: Set[Tuple[str, float, float]] = set()
        
    def add_item(self, level: str, x: float, y: float, item_type: LevelItemType, item_id: Optional[int] = None):
        """Add an item to a level"""
        if level not in self._items:
            self._items[level] = set()
            
        item = Item(x, y, item_type, level, item_id)
        self._items[level].add(item)
        logger.debug(f"Added item {item_type.name} at ({x}, {y}) in {level}")
        
    def remove_item(self, level: str, x: float, y: float) -> Optional[Item]:
        """Remove an item from a level"""
        if level not in self._items:
            return None
            
        # Find item at position
        for item in self._items[level]:
            if abs(item.x - x) < 0.5 and abs(item.y - y) < 0.5:
                self._items[level].remove(item)
                logger.debug(f"Removed item {item.item_type.name} from ({x}, {y}) in {level}")
                return item
                
        return None
        
    def get_items_in_level(self, level: str) -> List[Item]:
        """Get all items in a level"""
        return list(self._items.get(level, []))
        
    def get_item_at(self, level: str, x: float, y: float, radius: float = 0.5) -> Optional[Item]:
        """Get item at or near position"""
        if level not in self._items:
            return None
            
        for item in self._items[level]:
            dx = abs(item.x - x)
            dy = abs(item.y - y)
            if dx <= radius and dy <= radius:
                return item
                
        return None
        
    def mark_picked_up(self, level: str, x: float, y: float):
        """Mark an item as picked up to avoid re-pickup"""
        self._picked_up.add((level, round(x, 1), round(y, 1)))
        
    def is_picked_up(self, level: str, x: float, y: float) -> bool:
        """Check if item was already picked up"""
        return (level, round(x, 1), round(y, 1)) in self._picked_up
        
    def add_to_inventory(self, item_type: LevelItemType, count: int = 1):
        """Add item to player's inventory"""
        if item_type not in self._inventory:
            self._inventory[item_type] = 0
        self._inventory[item_type] += count
        logger.debug(f"Added {count} {item_type.name} to inventory")
        
    def remove_from_inventory(self, item_type: LevelItemType, count: int = 1) -> bool:
        """Remove item from inventory, returns True if successful"""
        if self._inventory.get(item_type, 0) >= count:
            self._inventory[item_type] -= count
            if self._inventory[item_type] == 0:
                del self._inventory[item_type]
            return True
        return False
        
    def get_inventory_count(self, item_type: LevelItemType) -> int:
        """Get count of item in inventory"""
        return self._inventory.get(item_type, 0)
        
    def clear_level(self, level: str):
        """Clear all items from a level"""
        if level in self._items:
            del self._items[level]
            
    def clear_all(self):
        """Clear all items"""
        self._items.clear()
        self._picked_up.clear()