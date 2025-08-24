"""
Level Adapter
=============

Simplified level management adapter for pygame clients.
Provides clean interface to pyReborn's robust level management system
while eliminating code duplication.

This replaces pygame's level manager with a thin wrapper that:
- Delegates to pyReborn's proven level management
- Provides pygame-specific convenience methods
- Maintains compatibility with existing pygame code
"""

import logging
from typing import Dict, Any, Optional, List
from ..models.level import Level

logger = logging.getLogger(__name__)


class LevelAdapter:
    """Simplified level management adapter for pygame clients"""
    
    def __init__(self, client=None):
        """Initialize level adapter
        
        Args:
            client: PyReborn client reference
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Cache for pygame-specific level adaptations
        self._pygame_level_cache = {}
        
        self.logger.info("Level adapter initialized")
    
    def set_client(self, client):
        """Set PyReborn client reference
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger.info("Level adapter connected to PyReborn client")
    
    def get_current_level(self) -> Optional[Level]:
        """Get current level object
        
        Returns:
            Current Level object or None
        """
        if not self.client:
            return None
        
        try:
            # Get current level name from session manager
            if hasattr(self.client, 'session_manager') and self.client.session_manager:
                level_name = self.client.session_manager.get_effective_level_name()
                if level_name:
                    return self.get_level(level_name)
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting current level: {e}")
            return None
    
    def get_level(self, level_name: str) -> Optional[Level]:
        """Get level by name
        
        Args:
            level_name: Name of the level
            
        Returns:
            Level object or None if not available
        """
        if not self.client or not level_name:
            return None
        
        try:
            # Check pygame cache first
            if level_name in self._pygame_level_cache:
                return self._pygame_level_cache[level_name]
            
            # Get from pyReborn level manager
            if hasattr(self.client, 'level_manager') and self.client.level_manager:
                pyreborn_level = self.client.level_manager.get_level(level_name)
                
                if pyreborn_level:
                    # Create pygame-compatible level object
                    pygame_level = self._adapt_level_for_pygame(pyreborn_level, level_name)
                    
                    # Cache for future use
                    self._pygame_level_cache[level_name] = pygame_level
                    
                    return pygame_level
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting level {level_name}: {e}")
            return None
    
    def get_available_levels(self) -> List[str]:
        """Get list of available level names
        
        Returns:
            List of available level names
        """
        if not self.client:
            return []
        
        try:
            if hasattr(self.client, 'level_manager') and self.client.level_manager:
                if hasattr(self.client.level_manager, 'levels'):
                    return list(self.client.level_manager.levels.keys())
            
            return []
            
        except Exception as e:
            self.logger.debug(f"Error getting available levels: {e}")
            return []
    
    def is_level_available(self, level_name: str) -> bool:
        """Check if level is available
        
        Args:
            level_name: Name of the level to check
            
        Returns:
            True if level is available
        """
        return level_name in self.get_available_levels()
    
    def get_level_info(self, level_name: str) -> Dict[str, Any]:
        """Get level information without loading full level
        
        Args:
            level_name: Name of the level
            
        Returns:
            Dictionary with level information
        """
        level = self.get_level(level_name)
        
        if level:
            return {
                'name': level_name,
                'width': getattr(level, 'width', 64),
                'height': getattr(level, 'height', 64),
                'tile_count': getattr(level, 'tile_count', 0),
                'has_tiles': hasattr(level, 'tiles'),
                'has_links': hasattr(level, 'links') and bool(level.links),
                'link_count': len(getattr(level, 'links', {}))
            }
        else:
            return {
                'name': level_name,
                'available': False
            }
    
    def clear_cache(self):
        """Clear pygame level cache"""
        self._pygame_level_cache.clear()
        self.logger.debug("Level adapter cache cleared")
    
    def _adapt_level_for_pygame(self, pyreborn_level: Any, level_name: str) -> Level:
        """Adapt pyReborn level to pygame Level object
        
        Args:
            pyreborn_level: PyReborn level object
            level_name: Name of the level
            
        Returns:
            Pygame-compatible Level object
        """
        try:
            # Create Level object compatible with pygame systems
            level = Level(name=level_name)
            
            # Set width/height if different from default
            if hasattr(pyreborn_level, 'width'):
                level.width = pyreborn_level.width
            if hasattr(pyreborn_level, 'height'):
                level.height = pyreborn_level.height
            
            # Copy essential data using Level's unified format
            if hasattr(pyreborn_level, 'board_tiles'):
                level.board_tiles = pyreborn_level.board_tiles
            elif hasattr(pyreborn_level, 'tiles'):
                # Convert tiles to board_tiles format if needed
                level.board_tiles = pyreborn_level.tiles[:4096] if len(pyreborn_level.tiles) >= 4096 else pyreborn_level.tiles
            
            if hasattr(pyreborn_level, 'links'):
                level.links = pyreborn_level.links
            
            if hasattr(pyreborn_level, 'npcs'):
                level.npcs = pyreborn_level.npcs
            
            if hasattr(pyreborn_level, 'items'):
                level.items = pyreborn_level.items
            
            if hasattr(pyreborn_level, 'signs'):
                level.signs = pyreborn_level.signs
            
            if hasattr(pyreborn_level, 'chests'):
                level.chests = pyreborn_level.chests
            
            # Add pygame-specific convenience properties
            level.tile_count = len(level.board_tiles)
            level.link_count = len(getattr(level, 'links', []))
            
            return level
            
        except Exception as e:
            self.logger.error(f"Error adapting level {level_name}: {e}")
            # Return minimal level object
            return Level(name=level_name)


# Convenience function for easy integration
def create_level_adapter(client=None) -> LevelAdapter:
    """Create a level adapter instance
    
    Args:
        client: Optional PyReborn client
        
    Returns:
        Configured LevelAdapter instance
    """
    adapter = LevelAdapter(client)
    return adapter