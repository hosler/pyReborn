"""
Item Manager - Handles item pickups, drops, and animations in Classic Graal style
"""

import time
import math
import random
from typing import List, Tuple, Optional, Dict
from game.constants import ClassicItems, ItemValues, ClassicConstants, ClassicTileTypes

class DroppedItem:
    """Represents an item dropped in the world"""
    def __init__(self, x: float, y: float, item_type: str, tile_ids: List[int], value: float = 1):
        self.x = x
        self.y = y
        self.item_type = item_type  # 'heart', 'rupee', 'bomb', 'arrow', 'key'
        self.tile_ids = tile_ids  # 2x2 tile IDs for rendering
        self.value = value  # How much to give when picked up
        self.spawn_time = time.time()
        self.picked_up = False
        self.pickup_time = 0
        self.despawn_time = 60.0  # Items disappear after 60 seconds
        
    def get_float_offset(self, current_time: float) -> float:
        """Get vertical float offset for animation"""
        elapsed = current_time - self.spawn_time
        return math.sin(elapsed * ClassicConstants.FLOAT_SPEED * 2 * math.pi) * ClassicConstants.FLOAT_AMPLITUDE
        
    def is_expired(self, current_time: float) -> bool:
        """Check if item should despawn"""
        if self.picked_up:
            return current_time - self.pickup_time > ClassicConstants.PICKUP_DURATION
        return current_time - self.spawn_time > self.despawn_time

class ItemManager:
    """Manages all item drops and pickups"""
    
    def __init__(self):
        self.dropped_items: List[DroppedItem] = []
        self.respawn_timers: Dict[Tuple[int, int], float] = {}  # (x,y) -> respawn time
        
    def drop_item(self, x: float, y: float, item_type: str) -> Optional[DroppedItem]:
        """Drop an item at the specified location"""
        tile_ids = []
        value = 1
        
        if item_type == 'heart':
            tile_ids = ClassicItems.HEART_TILES
            value = ItemValues.HEART_HEAL
        elif item_type == 'rupee':
            # Random rupee type with weighted chances
            rand = random.randint(1, 100)
            if rand <= 70:  # 70% green
                tile_ids = ClassicItems.GREEN_RUPEE_TILES
                value = ItemValues.GREEN_RUPEE
            elif rand <= 95:  # 25% blue
                tile_ids = ClassicItems.BLUE_RUPEE_TILES
                value = ItemValues.BLUE_RUPEE
            else:  # 5% red
                tile_ids = ClassicItems.RED_RUPEE_TILES
                value = ItemValues.RED_RUPEE
        elif item_type == 'bomb':
            tile_ids = ClassicItems.BOMB_TILES
            value = ItemValues.BOMB_PICKUP
        elif item_type == 'arrow':
            tile_ids = ClassicItems.ARROW_TILES
            value = ItemValues.ARROW_BUNDLE
        elif item_type == 'key':
            tile_ids = ClassicItems.KEY_TILES
            value = 1
        elif item_type == 'heart_container':
            tile_ids = ClassicItems.HEART_CONTAINER_TILES
            value = 1
        else:
            return None
            
        item = DroppedItem(x, y, item_type, tile_ids, value)
        self.dropped_items.append(item)
        return item
        
    def drop_random_item(self, x: float, y: float) -> Optional[DroppedItem]:
        """Drop a random item (for grass cutting)"""
        if random.randint(1, 100) > ClassicConstants.GRASS_DROP_RATE:
            return None  # No drop
            
        # Determine what to drop
        rand = random.randint(1, 100)
        if rand <= ClassicConstants.GRASS_HEART_CHANCE:
            return self.drop_item(x, y, 'heart')
        elif rand <= ClassicConstants.GRASS_HEART_CHANCE + ClassicConstants.GRASS_RUPEE_CHANCE:
            return self.drop_item(x, y, 'rupee')
        elif rand <= ClassicConstants.GRASS_HEART_CHANCE + ClassicConstants.GRASS_RUPEE_CHANCE + ClassicConstants.GRASS_ARROW_CHANCE:
            return self.drop_item(x, y, 'arrow')
        else:
            return self.drop_item(x, y, 'bomb')
            
    def check_pickup(self, player_x: float, player_y: float, pickup_radius: float = 0.5) -> List[DroppedItem]:
        """Check if player can pick up any items"""
        picked_up = []
        current_time = time.time()
        
        for item in self.dropped_items:
            if item.picked_up:
                continue
                
            # Check distance
            dx = abs(player_x + 0.5 - (item.x + 0.5))
            dy = abs(player_y + 0.5 - (item.y + 0.5))
            
            if dx <= pickup_radius and dy <= pickup_radius:
                item.picked_up = True
                item.pickup_time = current_time
                picked_up.append(item)
                
        return picked_up
        
    def update(self, current_time: float):
        """Update items and remove expired ones"""
        self.dropped_items = [item for item in self.dropped_items if not item.is_expired(current_time)]
        
        # Update respawn timers
        expired_timers = []
        for pos, respawn_time in self.respawn_timers.items():
            if current_time >= respawn_time:
                expired_timers.append(pos)
                
        for pos in expired_timers:
            del self.respawn_timers[pos]
            
    def add_respawn_timer(self, x: int, y: int, respawn_time: float):
        """Add a respawn timer for a position"""
        self.respawn_timers[(x, y)] = time.time() + respawn_time
        
    def can_respawn_at(self, x: int, y: int) -> bool:
        """Check if something can respawn at this position"""
        return (x, y) not in self.respawn_timers
        
    def get_chest_tiles(self, chest_item: int) -> int:
        """Get the base tile ID for a chest based on its item"""
        # In Classic Graal, chest appearance often indicates contents
        if chest_item >= 20:  # Special items use red chest
            return ClassicItems.CHEST_RED
        elif chest_item >= 10:  # Good items use blue chest
            return ClassicItems.CHEST_BLUE
        elif chest_item >= 5:  # Decent items use green chest
            return ClassicItems.CHEST_GREEN
        else:  # Basic items use brown chest
            return ClassicItems.CHEST_BROWN