"""
Standardized Level Manager - Implements ILevelManager interface
"""

import logging
import time
from typing import Dict, List, Optional, Any, Callable

from ..core.interfaces import ILevelManager
from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from ..models.level import Level, Sign, Chest, LevelLink, NPC, Baddy


class StandardizedLevelManager(ILevelManager):
    """Standardized level manager implementing ILevelManager interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Level state
        self._current_level: Optional[Level] = None
        self._level_cache: Dict[str, Level] = {}
        
        # Asset management
        self._assets: Dict[str, bytes] = {}
        self._pending_requests: Dict[str, List[Callable]] = {}
        self._requested_files = set()
        self._request_timestamps = {}
        
        # Configuration
        self._request_timeout = 30.0
        self._request_rate_limit = 0.1
        self._max_concurrent_requests = 5
        self._active_requests = 0
        
        # Statistics
        self._stats = {
            'levels_loaded': 0,
            'assets_downloaded': 0,
            'failed_requests': 0,
            'cache_hits': 0
        }
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize the level manager"""
        self.config = config
        self.events = event_manager
        
        # Subscribe to relevant events
        self.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
        self.events.subscribe(EventType.LEVEL_LEFT, self._on_level_left)
        self.events.subscribe(EventType.LEVEL_UPDATE, self._on_level_update)
        self.events.subscribe(EventType.FILE_RECEIVED, self._on_file_received)
        
        self.logger.debug("Level manager initialized")
        
    def cleanup(self) -> None:
        """Clean up level manager resources"""
        if self.events:
            self.events.unsubscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
            self.events.unsubscribe(EventType.LEVEL_LEFT, self._on_level_left)
            self.events.unsubscribe(EventType.LEVEL_UPDATE, self._on_level_update)
            self.events.unsubscribe(EventType.FILE_RECEIVED, self._on_file_received)
        
        self._clear_cache()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "standardized_level_manager"
    
    def get_current_level(self) -> Optional[Level]:
        """Get current level object"""
        return self._current_level
    
    def load_level(self, level_name: str) -> bool:
        """Load a specific level"""
        try:
            # Check cache first
            if level_name in self._level_cache:
                self._current_level = self._level_cache[level_name]
                self._stats['cache_hits'] += 1
                self.logger.debug(f"Loaded level from cache: {level_name}")
                
                if self.events:
                    self.events.emit(EventType.LEVEL_ENTERED, 
                                   level_name=level_name, 
                                   level=self._current_level)
                return True
            
            # Request level data if not cached
            self._request_level_data(level_name)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load level {level_name}: {e}")
            self._stats['failed_requests'] += 1
            return False
    
    def get_level_cache(self) -> Dict[str, Level]:
        """Get cached levels"""
        return self._level_cache.copy()
    
    # Extended level management methods
    def create_level(self, level_name: str, width: int = 64, height: int = 64) -> Level:
        """Create a new level"""
        level = Level(level_name)
        level.width = width
        level.height = height
        self._level_cache[level_name] = level
        self._stats['levels_loaded'] += 1
        
        self.logger.debug(f"Created level: {level_name} ({width}x{height})")
        return level
    
    def set_current_level(self, level: Level) -> None:
        """Set the current level"""
        old_level = self._current_level
        self._current_level = level
        
        # Cache the level
        if level and level.name:
            self._level_cache[level.name] = level
        
        # Emit events
        if self.events:
            if old_level and old_level != level:
                self.events.emit(EventType.LEVEL_LEFT, 
                               level_name=old_level.name, 
                               level=old_level)
            
            if level:
                self.events.emit(EventType.LEVEL_ENTERED, 
                               level_name=level.name, 
                               level=level)
        
        self.logger.debug(f"Current level set to: {level.name if level else None}")
    
    def get_level(self, level_name: str) -> Optional[Level]:
        """Get a specific level by name"""
        return self._level_cache.get(level_name)
    
    def has_level(self, level_name: str) -> bool:
        """Check if level is cached"""
        return level_name in self._level_cache
    
    def remove_level(self, level_name: str) -> bool:
        """Remove level from cache"""
        if level_name in self._level_cache:
            del self._level_cache[level_name]
            
            # Clear current level if it was removed
            if self._current_level and self._current_level.name == level_name:
                self._current_level = None
            
            self.logger.debug(f"Removed level from cache: {level_name}")
            return True
        return False
    
    def clear_cache(self) -> None:
        """Clear level cache"""
        self._clear_cache()
        self.logger.debug("Level cache cleared")
    
    def add_sign(self, level_name: str, sign: Sign) -> bool:
        """Add a sign to a level"""
        level = self.get_level(level_name)
        if level:
            level.add_sign(sign)
            if self.events:
                self.events.emit(EventType.LEVEL_SIGN_ADDED, 
                               level_name=level_name, 
                               sign=sign)
            return True
        return False
    
    def add_chest(self, level_name: str, chest: Chest) -> bool:
        """Add a chest to a level"""
        level = self.get_level(level_name)
        if level:
            level.add_chest(chest)
            if self.events:
                self.events.emit(EventType.LEVEL_CHEST_ADDED, 
                               level_name=level_name, 
                               chest=chest)
            return True
        return False
    
    def add_link(self, level_name: str, link: LevelLink) -> bool:
        """Add a level link"""
        level = self.get_level(level_name)
        if level:
            level.add_link(link)
            if self.events:
                self.events.emit(EventType.LEVEL_LINK_ADDED, 
                               level_name=level_name, 
                               link=link)
            return True
        return False
    
    def add_npc(self, level_name: str, npc: NPC) -> bool:
        """Add an NPC to a level"""
        level = self.get_level(level_name)
        if level:
            level.add_npc(npc)
            if self.events:
                self.events.emit(EventType.NPC_ADDED, 
                               level_name=level_name, 
                               npc=npc)
            return True
        return False
    
    def request_asset(self, filename: str, callback: Callable = None) -> bool:
        """Request an asset file"""
        if filename in self._assets:
            # Asset already available
            if callback:
                callback(filename, self._assets[filename])
            return True
        
        # Check if already requesting
        if filename in self._requested_files:
            # Add callback to pending list
            if callback:
                if filename not in self._pending_requests:
                    self._pending_requests[filename] = []
                self._pending_requests[filename].append(callback)
            return True
        
        # Check request limits
        if self._active_requests >= self._max_concurrent_requests:
            self.logger.warning(f"Asset request limit reached, queuing: {filename}")
            return False
        
        # Make request
        try:
            self._requested_files.add(filename)
            self._request_timestamps[filename] = time.time()
            self._active_requests += 1
            
            if callback:
                if filename not in self._pending_requests:
                    self._pending_requests[filename] = []
                self._pending_requests[filename].append(callback)
            
            # Emit request event (to be handled by connection layer)
            if self.events:
                self.events.emit(EventType.FILE_REQUEST_FAILED, filename=filename)
            
            self.logger.debug(f"Requested asset: {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to request asset {filename}: {e}")
            self._stats['failed_requests'] += 1
            return False
    
    def get_asset(self, filename: str) -> Optional[bytes]:
        """Get cached asset data"""
        return self._assets.get(filename)
    
    def has_asset(self, filename: str) -> bool:
        """Check if asset is cached"""
        return filename in self._assets
    
    def get_level_stats(self) -> Dict[str, Any]:
        """Get level manager statistics"""
        stats = self._stats.copy()
        stats.update({
            'cached_levels': len(self._level_cache),
            'cached_assets': len(self._assets),
            'pending_requests': len(self._pending_requests),
            'active_requests': self._active_requests,
            'current_level': self._current_level.name if self._current_level else None
        })
        return stats
    
    def _clear_cache(self) -> None:
        """Clear all cached data"""
        self._current_level = None
        self._level_cache.clear()
        self._assets.clear()
        self._pending_requests.clear()
        self._requested_files.clear()
        self._request_timestamps.clear()
        self._active_requests = 0
    
    def _request_level_data(self, level_name: str) -> None:
        """Request level data from server"""
        # This would typically send a file request packet
        self.request_asset(f"{level_name}.nw")
        self.request_asset(f"{level_name}.graal")  # If using graal format
    
    # Event handlers
    def _on_level_entered(self, event) -> None:
        """Handle level entry event"""
        level_name = event.data.get('level_name')
        level_obj = event.data.get('level')
        
        if level_name and level_obj:
            self._current_level = level_obj
            self._level_cache[level_name] = level_obj
            
            if level_name not in [l.name for l in self._level_cache.values()]:
                self._stats['levels_loaded'] += 1
    
    def _on_level_left(self, event) -> None:
        """Handle level exit event"""
        # Could implement level cleanup here if needed
        pass
    
    def _on_level_update(self, event) -> None:
        """Handle level update event"""
        level_name = event.data.get('level_name')
        if level_name and level_name in self._level_cache:
            # Update cached level with new data
            level = self._level_cache[level_name]
            # Apply updates to level object
            self.logger.debug(f"Updated level: {level_name}")
    
    def _on_file_received(self, event) -> None:
        """Handle file received event"""
        filename = event.data.get('filename')
        file_data = event.data.get('data')
        
        if filename and file_data:
            # Cache the asset
            self._assets[filename] = file_data
            self._stats['assets_downloaded'] += 1
            
            # Remove from active requests
            if filename in self._requested_files:
                self._requested_files.remove(filename)
            if filename in self._request_timestamps:
                del self._request_timestamps[filename]
            self._active_requests = max(0, self._active_requests - 1)
            
            # Call pending callbacks
            if filename in self._pending_requests:
                for callback in self._pending_requests[filename]:
                    try:
                        callback(filename, file_data)
                    except Exception as e:
                        self.logger.error(f"Callback error for {filename}: {e}")
                del self._pending_requests[filename]
            
            self.logger.debug(f"Received asset: {filename} ({len(file_data)} bytes)")