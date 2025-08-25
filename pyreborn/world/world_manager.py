"""
Unified World Manager

This is the main interface for all world functionality, consolidating:
- Level management and loading
- GMAP multi-level worlds
- Coordinate transformations
- World navigation and transitions
"""

import logging
from typing import Optional, Dict, Any, List, Tuple

from .level_manager import LevelManager, LevelData, LevelEntity
from .gmap_manager import GMAPManager
# Simplified - no need for complex coordinate manager
Position = tuple  # (x, y)


class WorldManager:
    """Unified world management interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Core components
        self.levels = LevelManager()
        self.gmap = GMAPManager()
        # Coordinate manager removed - use coordinate helpers directly
        
        # World state
        self.current_world_name: Optional[str] = None
        
    def load_single_level_world(self, level_name: str, level_data: bytes):
        """Load a single-level world"""
        self.logger.info(f"Loading single-level world: {level_name}")
        
        # Disable GMAP mode
        self.gmap.disable_gmap()
        self.coordinates.set_gmap_mode(False)
        
        # Load level
        success = self.levels.load_level(level_name, level_data)
        if success:
            self.levels.set_current_level(level_name)
            self.current_world_name = level_name
            
        return success
        
    def load_gmap_world(self, gmap_name: str, levels_data: Dict[str, Tuple[int, int]]):
        """Load a GMAP multi-level world"""
        self.logger.info(f"Loading GMAP world: {gmap_name}")
        
        # Enable GMAP mode
        self.gmap.load_gmap_data(gmap_name, levels_data)
        self.coordinates.set_gmap_mode(True, gmap_name)
        
        # Register segments in coordinate manager
        for level_name, (seg_x, seg_y) in levels_data.items():
            self.coordinates.register_gmap_segment(level_name, seg_x, seg_y)
            
        self.current_world_name = gmap_name
        return True
        
    def load_level_data(self, level_name: str, level_data: bytes):
        """Load specific level data"""
        success = self.levels.load_level(level_name, level_data)
        if success and self.gmap.is_enabled():
            self.gmap.mark_level_loaded(level_name)
        return success
        
    def enter_level(self, level_name: str, x: float = 30.0, y: float = 30.0):
        """Enter a specific level"""
        self.logger.info(f"Entering level: {level_name} at ({x}, {y})")
        
        # Update level
        self.levels.set_current_level(level_name)
        
        # Update coordinates
        self.coordinates.update_position(x, y, level_name)
        
        # Preload adjacent levels if in GMAP mode
        if self.gmap.is_enabled():
            adjacent = self.gmap.get_adjacent_levels(level_name)
            for adj_level in adjacent:
                self.levels.preload_level(adj_level)
                
    def move_player(self, x: float, y: float):
        """Update player position in current level"""
        current_level = self.levels.current_level
        self.coordinates.update_position(x, y, current_level)
        
        # Check for level transitions in GMAP mode
        if self.gmap.is_enabled() and current_level:
            self._check_level_transition(x, y, current_level)
            
    def get_current_level(self) -> Optional[LevelData]:
        """Get current level data"""
        return self.levels.get_current_level()
        
    def get_current_position(self) -> Position:
        """Get current player position"""
        return self.coordinates.get_position()
        
    def get_server_coordinates(self) -> Tuple[float, float]:
        """Get coordinates to send to server"""
        return self.coordinates.get_server_coordinates()
        
    def get_server_level_name(self) -> Optional[str]:
        """Get level name to send to server"""
        return self.coordinates.get_level_name_for_server()
        
    def get_tile_at(self, x: int, y: int, level_name: Optional[str] = None) -> Optional[int]:
        """Get tile at coordinates"""
        if level_name is None:
            level_name = self.levels.current_level
        if level_name is None:
            return None
        return self.levels.get_tile_at(level_name, x, y)
        
    def get_entities_at(self, x: int, y: int, level_name: Optional[str] = None) -> List[LevelEntity]:
        """Get entities at coordinates"""
        if level_name is None:
            level_name = self.levels.current_level
        if level_name is None:
            return []
        return self.levels.get_entities_at(level_name, x, y)
        
    def add_entity(self, entity: LevelEntity, level_name: Optional[str] = None):
        """Add entity to level"""
        if level_name is None:
            level_name = self.levels.current_level
        if level_name is None:
            return
        self.levels.add_entity(level_name, entity)
        
    def remove_entity(self, entity: LevelEntity, level_name: Optional[str] = None):
        """Remove entity from level"""
        if level_name is None:
            level_name = self.levels.current_level
        if level_name is None:
            return
        self.levels.remove_entity(level_name, entity)
        
    def is_gmap_enabled(self) -> bool:
        """Check if GMAP mode is enabled"""
        return self.gmap.is_enabled()
        
    def get_world_info(self) -> Dict[str, Any]:
        """Get comprehensive world information"""
        position = self.get_current_position()
        
        info = {
            'world_name': self.current_world_name,
            'current_level': self.levels.current_level,
            'gmap_enabled': self.is_gmap_enabled(),
            'position': {
                'x': position.x,
                'y': position.y,
                'level': position.level
            },
            'server_coordinates': self.get_server_coordinates(),
            'server_level': self.get_server_level_name()
        }
        
        # Add GMAP info if enabled
        gmap_info = self.gmap.get_gmap_info()
        if gmap_info:
            info['gmap'] = gmap_info
            
        # Add level cache info
        info['levels'] = self.levels.get_cache_stats()
        
        return info
        
    def cleanup(self):
        """Clean up world resources"""
        self.gmap.cleanup()
        self.levels.cleanup_cache()
        # Coordinate manager removed - use coordinate helpers directly  # Reset coordinates
        self.current_world_name = None
        self.logger.info("World manager cleaned up")
        
    def _check_level_transition(self, x: float, y: float, current_level: str):
        """Check if player should transition to adjacent level"""
        # This would implement seamless GMAP level transitions
        # For now, just log potential transitions
        
        if x < 0 or x >= 64 or y < 0 or y >= 64:
            self.logger.debug(f"Player at edge of level {current_level}: ({x}, {y})")
            
            # In a full implementation, this would:
            # 1. Calculate which adjacent level to transition to
            # 2. Load the adjacent level if needed
            # 3. Update player position to the new level
            # 4. Trigger level transition event
    
    def update(self):
        """Update world state - compatibility method for clients"""
        # This is a compatibility method for clients that expect world updates
        # In our architecture, world state is updated through packet handlers
        # So this is mostly a no-op, but could be used for periodic tasks
        pass