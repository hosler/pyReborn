"""
Standardized Item Manager - Implements IItemManager interface
"""

import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass

from ..core.interfaces import IItemManager
from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from ..protocol.enums import LevelItemType


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
    
    def __str__(self):
        return f"{self.item_type.name} at ({self.x}, {self.y}) in {self.level}"


@dataclass
class InventoryItem:
    """Represents an item in player inventory"""
    item_type: LevelItemType
    quantity: int
    
    def __str__(self):
        return f"{self.quantity}x {self.item_type.name}"


class StandardizedItemManager(IItemManager):
    """Standardized item manager implementing IItemManager interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # World items by level
        self._level_items: Dict[str, Set[Item]] = {}
        
        # Player inventory
        self._inventory: Dict[LevelItemType, InventoryItem] = {}
        
        # Picked up items (to prevent re-pickup)
        self._picked_up_items: Set[Tuple[str, float, float]] = set()
        
        # Item spawning history
        self._spawned_items: List[Item] = []
        
        # Statistics
        self._stats = {
            'items_added': 0,
            'items_removed': 0,
            'items_picked_up': 0,
            'inventory_changes': 0
        }
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize the item manager"""
        self.config = config
        self.events = event_manager
        
        # Subscribe to relevant events
        self.events.subscribe(EventType.ITEM_ADDED, self._on_item_added)
        self.events.subscribe(EventType.ITEM_REMOVED, self._on_item_removed)
        self.events.subscribe(EventType.ITEM_TAKEN, self._on_item_taken)
        self.events.subscribe(EventType.ITEM_SPAWNED, self._on_item_spawned)
        self.events.subscribe(EventType.LEVEL_LEFT, self._on_level_left)
        
        self.logger.debug("Item manager initialized")
        
    def cleanup(self) -> None:
        """Clean up item manager resources"""
        if self.events:
            self.events.unsubscribe(EventType.ITEM_ADDED, self._on_item_added)
            self.events.unsubscribe(EventType.ITEM_REMOVED, self._on_item_removed)
            self.events.unsubscribe(EventType.ITEM_TAKEN, self._on_item_taken)
            self.events.unsubscribe(EventType.ITEM_SPAWNED, self._on_item_spawned)
            self.events.unsubscribe(EventType.LEVEL_LEFT, self._on_level_left)
        
        self._clear_all_data()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "standardized_item_manager"
    
    def get_player_items(self) -> List[InventoryItem]:
        """Get player's current items"""
        return list(self._inventory.values())
    
    def add_item(self, item: Item) -> None:
        """Add item to world"""
        if item.level not in self._level_items:
            self._level_items[item.level] = set()
        
        self._level_items[item.level].add(item)
        self._stats['items_added'] += 1
        
        self.logger.debug(f"Added world item: {item}")
        
        if self.events:
            self.events.emit(EventType.ITEM_ADDED, 
                           item=item, 
                           level=item.level)
    
    def remove_item(self, item_id: str) -> bool:
        """Remove item from world by ID"""
        # Parse item_id format: "level:x:y:type"
        try:
            parts = item_id.split(':')
            if len(parts) >= 4:
                level = parts[0]
                x = float(parts[1])
                y = float(parts[2])
                item_type = parts[3]
                
                return self.remove_item_at(level, x, y)
        except (ValueError, IndexError):
            self.logger.warning(f"Invalid item ID format: {item_id}")
        
        return False
    
    # Extended item management methods
    def add_world_item(self, level: str, x: float, y: float, 
                      item_type: LevelItemType, item_id: int = None) -> Item:
        """Add an item to the world at specific coordinates"""
        item = Item(x, y, item_type, level, item_id)
        self.add_item(item)
        return item
    
    def remove_item_at(self, level: str, x: float, y: float) -> bool:
        """Remove item at specific coordinates"""
        if level not in self._level_items:
            return False
        
        # Find item at coordinates (with small tolerance for floating point)
        for item in list(self._level_items[level]):
            if abs(item.x - x) < 0.1 and abs(item.y - y) < 0.1:
                self._level_items[level].remove(item)
                self._stats['items_removed'] += 1
                
                self.logger.debug(f"Removed world item: {item}")
                
                if self.events:
                    self.events.emit(EventType.ITEM_REMOVED, 
                                   item=item, 
                                   level=level)
                return True
        
        return False
    
    def get_level_items(self, level: str) -> List[Item]:
        """Get all items in a specific level"""
        if level in self._level_items:
            return list(self._level_items[level])
        return []
    
    def get_items_near(self, level: str, x: float, y: float, radius: float = 1.0) -> List[Item]:
        """Get items near specific coordinates"""
        if level not in self._level_items:
            return []
        
        nearby_items = []
        for item in self._level_items[level]:
            distance = ((item.x - x) ** 2 + (item.y - y) ** 2) ** 0.5
            if distance <= radius:
                nearby_items.append(item)
        
        return nearby_items
    
    def pickup_item(self, level: str, x: float, y: float) -> Optional[Item]:
        """Pick up an item from the world"""
        item_key = (level, x, y)
        
        # Check if already picked up
        if item_key in self._picked_up_items:
            return None
        
        # Find and remove item
        if level in self._level_items:
            for item in list(self._level_items[level]):
                if abs(item.x - x) < 0.1 and abs(item.y - y) < 0.1:
                    # Remove from world
                    self._level_items[level].remove(item)
                    
                    # Add to inventory
                    self._add_to_inventory(item.item_type, 1)
                    
                    # Mark as picked up
                    self._picked_up_items.add(item_key)
                    self._stats['items_picked_up'] += 1
                    
                    self.logger.debug(f"Picked up item: {item}")
                    
                    if self.events:
                        self.events.emit(EventType.ITEM_TAKEN, 
                                       item=item, 
                                       level=level)
                    
                    return item
        
        return None
    
    def add_to_inventory(self, item_type: LevelItemType, quantity: int = 1) -> None:
        """Add items to player inventory"""
        self._add_to_inventory(item_type, quantity)
    
    def remove_from_inventory(self, item_type: LevelItemType, quantity: int = 1) -> bool:
        """Remove items from player inventory"""
        if item_type not in self._inventory:
            return False
        
        current_quantity = self._inventory[item_type].quantity
        if current_quantity < quantity:
            return False
        
        if current_quantity == quantity:
            del self._inventory[item_type]
        else:
            self._inventory[item_type].quantity -= quantity
        
        self._stats['inventory_changes'] += 1
        self.logger.debug(f"Removed {quantity}x {item_type.name} from inventory")
        
        return True
    
    def get_inventory_item(self, item_type: LevelItemType) -> Optional[InventoryItem]:
        """Get specific item from inventory"""
        return self._inventory.get(item_type)
    
    def get_inventory_quantity(self, item_type: LevelItemType) -> int:
        """Get quantity of specific item in inventory"""
        if item_type in self._inventory:
            return self._inventory[item_type].quantity
        return 0
    
    def has_item(self, item_type: LevelItemType, quantity: int = 1) -> bool:
        """Check if player has enough of an item"""
        return self.get_inventory_quantity(item_type) >= quantity
    
    def clear_level_items(self, level: str) -> None:
        """Clear all items from a level"""
        if level in self._level_items:
            item_count = len(self._level_items[level])
            del self._level_items[level]
            self.logger.debug(f"Cleared {item_count} items from level: {level}")
    
    def clear_inventory(self) -> None:
        """Clear player inventory"""
        item_count = len(self._inventory)
        self._inventory.clear()
        self._stats['inventory_changes'] += 1
        self.logger.debug(f"Cleared inventory ({item_count} item types)")
    
    def get_spawned_items(self) -> List[Item]:
        """Get list of items that were spawned"""
        return self._spawned_items.copy()
    
    def get_item_stats(self) -> Dict[str, Any]:
        """Get item manager statistics"""
        stats = self._stats.copy()
        
        total_world_items = sum(len(items) for items in self._level_items.values())
        total_inventory_items = sum(item.quantity for item in self._inventory.values())
        
        stats.update({
            'levels_with_items': len(self._level_items),
            'total_world_items': total_world_items,
            'inventory_item_types': len(self._inventory),
            'total_inventory_items': total_inventory_items,
            'picked_up_locations': len(self._picked_up_items),
            'spawned_items': len(self._spawned_items)
        })
        
        return stats
    
    def _add_to_inventory(self, item_type: LevelItemType, quantity: int) -> None:
        """Internal method to add items to inventory"""
        if item_type in self._inventory:
            self._inventory[item_type].quantity += quantity
        else:
            self._inventory[item_type] = InventoryItem(item_type, quantity)
        
        self._stats['inventory_changes'] += 1
        self.logger.debug(f"Added {quantity}x {item_type.name} to inventory")
    
    def _clear_all_data(self) -> None:
        """Clear all item data"""
        self._level_items.clear()
        self._inventory.clear()
        self._picked_up_items.clear()
        self._spawned_items.clear()
        self._stats = {
            'items_added': 0,
            'items_removed': 0,
            'items_picked_up': 0,
            'inventory_changes': 0
        }
    
    # Event handlers
    def _on_item_added(self, event) -> None:
        """Handle item added event"""
        # This could be used for additional processing
        pass
    
    def _on_item_removed(self, event) -> None:
        """Handle item removed event"""
        # This could be used for additional processing
        pass
    
    def _on_item_taken(self, event) -> None:
        """Handle item taken event"""
        # This could be used for additional processing
        pass
    
    def _on_item_spawned(self, event) -> None:
        """Handle item spawned event"""
        item_data = event.data.get('item')
        if item_data:
            # Convert to Item object if needed
            if isinstance(item_data, dict):
                item = Item(
                    x=item_data.get('x', 0),
                    y=item_data.get('y', 0),
                    item_type=item_data.get('item_type', LevelItemType.GREENRUPEE),
                    level=item_data.get('level', ''),
                    id=item_data.get('id')
                )
            else:
                item = item_data
            
            self._spawned_items.append(item)
            self.add_item(item)
    
    def _on_level_left(self, event) -> None:
        """Handle level exit event"""
        level_name = event.data.get('level_name')
        if level_name and level_name in self._level_items:
            # Could implement item persistence here
            # For now, just log the transition
            item_count = len(self._level_items[level_name])
            self.logger.debug(f"Left level {level_name} with {item_count} items")