"""
Game State Module - Manages overall game state and coordination
"""

import time
from typing import Dict, Set, Optional, Tuple
from pyreborn.models.player import Player
from pyreborn.models.level import Level
from pyreborn.protocol.enums import Direction

from item_manager import ItemManager
from bush_handler import BushHandler
from classic_constants import ClassicConstants


class GameState:
    """Manages the overall game state"""
    
    def __init__(self, tile_defs=None):
        """Initialize game state
        
        Args:
            tile_defs: TileDefs instance (optional)
        """
        self.tile_defs = tile_defs
        # Core game objects
        self.current_level: Optional[Level] = None
        self.players: Dict[int, Player] = {}
        self.local_player: Optional[Player] = None
        
        # Managers
        self.item_manager = ItemManager()
        self.bush_handler = BushHandler()
        
        # Game state tracking
        self.opened_chests: Set[Tuple[int, int]] = set()
        self.grabbed_tile_pos: Optional[Tuple[int, int]] = None
        
        # Player state
        self.is_moving = False
        self.is_swimming = False
        self.is_grabbing = False
        self.is_pushing = False
        self.is_throwing = False
        self.is_attacking = False
        self.attack_just_finished = False
        self.throw_just_finished = False
        self.on_chair = False
        
        # Timing
        self.last_move_time = 0
        self.sword_start_time = 0
        self.throw_start_time = 0
        self.push_start_time = 0
        self.blocked_direction: Optional[Direction] = None
        
        # Movement
        self.move_speed = 0.5  # Half tile per move
        self.move_cooldown = 0.02  # 20ms between moves
        self.last_direction = Direction.DOWN
        self.step_count = 0  # Track steps for sound effects
        
        # GMAP state
        self.is_gmap = False
        self.gmap_width = 1
        self.gmap_height = 1
        self.adjacent_levels_requested = set()  # Track which adjacent levels we've requested
        
    def set_level(self, level: Level):
        """Set the current level
        
        Args:
            level: New level
        """
        print(f"[GAME STATE] set_level called with: {level.name if level else 'None'}")
        if not level:
            print(f"[GAME STATE] WARNING: Setting current level to None!")
            import traceback
            traceback.print_stack()
        old_level = self.current_level
        self.current_level = level
        
        # We'll detect gmap status from player properties instead
        # since gmap segments are regular .nw files
        
        # Only reset state if we're actually changing levels (not just updating)
        if old_level and level and old_level.name != level.name:
            print(f"[GAME STATE] Level changed from {old_level.name} to {level.name} - clearing state")
            # Reset level-specific state
            self.opened_chests.clear()
            self.item_manager.dropped_items.clear()
            self.bush_handler.thrown_bushes.clear()
            self.adjacent_levels_requested.clear()
        elif not old_level:
            print(f"[GAME STATE] Initial level set to {level.name if level else 'None'}")
        
    def update_gmap_status(self, player):
        """Update gmap status based on player properties"""
        if hasattr(player, 'gmaplevelx') and player.gmaplevelx is not None:
            self.is_gmap = True
            # Could also get gmap dimensions from server if provided
        else:
            self.is_gmap = False
        
    def add_player(self, player: Player):
        """Add a player to the game
        
        Args:
            player: Player to add
        """
        self.players[player.id] = player
        
    def remove_player(self, player_id: int):
        """Remove a player from the game
        
        Args:
            player_id: ID of player to remove
        """
        if player_id in self.players:
            del self.players[player_id]
            
    def update_player(self, player_id: int, **kwargs):
        """Update player properties
        
        Args:
            player_id: ID of player to update
            **kwargs: Properties to update
        """
        if player_id in self.players:
            player = self.players[player_id]
            for key, value in kwargs.items():
                if hasattr(player, key):
                    setattr(player, key, value)
                    
    def get_current_speed(self) -> float:
        """Get current movement speed based on state
        
        Returns:
            Movement speed in tiles per move
        """
        if self.is_swimming:
            return ClassicConstants.SWIM_SPEED
        else:
            return self.move_speed
            
    def can_move(self) -> bool:
        """Check if player can currently move
        
        Returns:
            True if movement is allowed
        """
        current_time = time.time()
        
        # Check cooldown
        if current_time - self.last_move_time < self.move_cooldown:
            return False
            
        # Check state restrictions
        if self.is_attacking or self.is_throwing:
            return False
            
        return True
        
    def start_attack(self):
        """Start sword attack"""
        self.is_attacking = True
        self.sword_start_time = time.time()
        self.attack_just_finished = False
        
    def is_attack_finished(self) -> bool:
        """Check if sword attack animation is finished
        
        Returns:
            True if attack is complete
        """
        if not self.is_attacking:
            return True
        return time.time() - self.sword_start_time > 0.16
        
    def start_throw(self):
        """Start throwing animation"""
        self.is_throwing = True
        self.throw_start_time = time.time()
        self.throw_just_finished = False
        
    def is_throw_finished(self) -> bool:
        """Check if throw animation is finished
        
        Returns:
            True if throw is complete
        """
        if not self.is_throwing:
            return True
        return time.time() - self.throw_start_time > 0.2
        
    def start_push(self, direction: Direction):
        """Start pushing against a wall
        
        Args:
            direction: Direction being pushed
        """
        if not self.is_pushing:
            self.is_pushing = True
            self.push_start_time = time.time()
            self.blocked_direction = direction
            
    def should_show_push_animation(self) -> bool:
        """Check if push animation should be shown
        
        Returns:
            True if pushing for more than 0.5 seconds
        """
        if not self.is_pushing:
            return False
        return time.time() - self.push_start_time > 0.5
        
    def stop_push(self):
        """Stop pushing"""
        self.is_pushing = False
        self.blocked_direction = None
        
    def update(self, current_time: float):
        """Update game state
        
        Args:
            current_time: Current time in seconds
        """
        # Update managers
        self.item_manager.update(current_time)
        
        # Update thrown bushes
        if self.current_level and self.tile_defs:
            self.bush_handler.update_thrown_bushes(self.current_level, self.tile_defs, current_time)
            self.bush_handler.update_explosions(current_time)
        
        # Update attack state
        if self.is_attacking and self.is_attack_finished():
            self.is_attacking = False
            self.attack_just_finished = True
            
        # Update throw state
        if self.is_throwing and self.is_throw_finished():
            self.is_throwing = False
            self.throw_just_finished = True
            
    def get_stats_dict(self) -> Dict[str, str]:
        """Get player stats for display
        
        Returns:
            Dict of stat names to values
        """
        if not self.local_player:
            return {}
            
        return {
            'Hearts': f"{self.local_player.hearts:.1f}/{self.local_player.max_hearts}",
            'Rupees': str(self.local_player.rupees),
            'Bombs': str(self.local_player.bombs),
            'Arrows': str(self.local_player.arrows),
            'Keys': str(getattr(self.local_player, 'keys', 0))
        }