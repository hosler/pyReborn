"""
Position Manager
================

Centralized position tracking and management system that provides:
- Single source of truth for player position
- World/local/segment coordinate conversions
- Position history and change tracking
- GMAP-aware position management
- Clean API for all position queries

This eliminates position tracking duplication across pygame systems.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple, List, Callable
from dataclasses import dataclass
from ..world.coordinate_helpers import CoordinateSet, CoordinateHelpers

logger = logging.getLogger(__name__)


@dataclass
class PositionSnapshot:
    """Complete position state at a point in time"""
    timestamp: float
    local_position: Tuple[float, float]
    world_position: Tuple[float, float]
    segment: Tuple[int, int]
    level_name: str
    gmap_active: bool
    source: str = "unknown"


@dataclass
class PositionChange:
    """Position change event data"""
    timestamp: float
    old_position: Tuple[float, float]
    new_position: Tuple[float, float]
    change_type: str  # "movement", "warp", "transition"
    level_change: bool
    segment_change: bool


class PositionManager:
    """Centralized position tracking and management"""
    
    def __init__(self, client=None):
        """Initialize position manager
        
        Args:
            client: PyReborn client reference
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Position tracking
        self.current_snapshot: Optional[PositionSnapshot] = None
        self.position_history: List[PositionSnapshot] = []
        self.change_history: List[PositionChange] = []
        
        # Configuration
        self.history_size = 100
        self.change_threshold = 0.1  # Minimum change to record
        
        # Change detection callbacks
        self.position_change_callbacks: List[Callable] = []
        self.level_change_callbacks: List[Callable] = []
        self.segment_change_callbacks: List[Callable] = []
        
        # Statistics
        self.stats = {
            'position_updates': 0,
            'level_changes': 0,
            'segment_changes': 0,
            'warp_events': 0
        }
        
        self.logger.info("Position manager initialized")
    
    def set_client(self, client):
        """Set PyReborn client reference
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger.info("Position manager connected to PyReborn client")
    
    def add_position_change_callback(self, callback: Callable):
        """Add callback for position changes
        
        Args:
            callback: Function to call on position changes
        """
        self.position_change_callbacks.append(callback)
    
    def add_level_change_callback(self, callback: Callable):
        """Add callback for level changes
        
        Args:
            callback: Function to call on level changes
        """
        self.level_change_callbacks.append(callback)
    
    def add_segment_change_callback(self, callback: Callable):
        """Add callback for segment changes
        
        Args:
            callback: Function to call on segment changes
        """
        self.segment_change_callbacks.append(callback)
    
    def update(self) -> Optional[PositionSnapshot]:
        """Update position tracking and detect changes
        
        Returns:
            Current position snapshot if available
        """
        try:
            # Get current position from client
            new_snapshot = self._capture_position_snapshot("update")
            
            if new_snapshot:
                # Detect changes from previous snapshot
                if self.current_snapshot:
                    self._detect_and_process_changes(self.current_snapshot, new_snapshot)
                
                # Update current state
                self.current_snapshot = new_snapshot
                self.stats['position_updates'] += 1
                
                # Add to history
                self.position_history.append(new_snapshot)
                if len(self.position_history) > self.history_size:
                    self.position_history = self.position_history[-self.history_size:]
                
                return new_snapshot
            
            return self.current_snapshot
            
        except Exception as e:
            self.logger.debug(f"Error updating position: {e}")
            return self.current_snapshot
    
    def get_current_position(self) -> Dict[str, Any]:
        """Get current position in all coordinate systems
        
        Returns:
            Dictionary with position in all formats
        """
        if not self.current_snapshot:
            self.update()
        
        if self.current_snapshot:
            return {
                'local': self.current_snapshot.local_position,
                'world': self.current_snapshot.world_position,
                'segment': self.current_snapshot.segment,
                'level': self.current_snapshot.level_name,
                'gmap_active': self.current_snapshot.gmap_active,
                'timestamp': self.current_snapshot.timestamp
            }
        else:
            return {
                'local': (0, 0),
                'world': (0, 0),
                'segment': (0, 0),
                'level': 'unknown',
                'gmap_active': False,
                'timestamp': time.time()
            }
    
    def get_coordinate_info(self) -> Optional[CoordinateSet]:
        """Get comprehensive coordinate information
        
        Returns:
            CoordinateSet with complete position data
        """
        position = self.get_current_position()
        
        if position['local'] != (0, 0):  # Valid position available
            return CoordinateHelpers.create_coordinate_set(
                world_x=position['world'][0],
                world_y=position['world'][1],
                is_gmap=position['gmap_active'],
                level_name=position['level']
            )
        
        return None
    
    def get_position_history(self, count: int = 10) -> List[PositionSnapshot]:
        """Get recent position history
        
        Args:
            count: Number of recent positions to return
            
        Returns:
            List of recent PositionSnapshot objects
        """
        return self.position_history[-count:] if self.position_history else []
    
    def get_change_history(self, count: int = 10) -> List[PositionChange]:
        """Get recent position changes
        
        Args:
            count: Number of recent changes to return
            
        Returns:
            List of recent PositionChange objects
        """
        return self.change_history[-count:] if self.change_history else []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get position tracking statistics
        
        Returns:
            Dictionary with position statistics
        """
        return {
            **self.stats,
            'history_size': len(self.position_history),
            'change_count': len(self.change_history),
            'current_position': self.get_current_position()
        }
    
    def _capture_position_snapshot(self, source: str) -> Optional[PositionSnapshot]:
        """Capture current position snapshot
        
        Args:
            source: Source of the snapshot
            
        Returns:
            PositionSnapshot if successful
        """
        if not self.client:
            return None
        
        try:
            # Try GMAP API first for comprehensive data
            from ..gmap_api.gmap_render_api import GMAPRenderAPI
            
            if not hasattr(self, '_gmap_api'):
                self._gmap_api = GMAPRenderAPI(self.client)
            
            render_data = self._gmap_api.get_gmap_render_data()
            
            if render_data and render_data.active:
                # GMAP mode - use comprehensive data
                current_level = "unknown"
                for segment in render_data.segments:
                    if segment.is_current_segment:
                        current_level = segment.level_name or "unknown"
                        break
                
                return PositionSnapshot(
                    timestamp=time.time(),
                    local_position=render_data.player_local_position,
                    world_position=render_data.player_world_position,
                    segment=render_data.current_segment,
                    level_name=current_level,
                    gmap_active=True,
                    source=source
                )
            
            # Fallback to session manager
            if hasattr(self.client, 'session_manager') and self.client.session_manager:
                session_manager = self.client.session_manager
                player = session_manager.player.get_player() if session_manager.player else None
                
                if player:
                    return PositionSnapshot(
                        timestamp=time.time(),
                        local_position=(player.x, player.y),
                        world_position=(getattr(player, 'x2', player.x), getattr(player, 'y2', player.y)),
                        segment=(0, 0),  # Default for single level
                        level_name=getattr(session_manager, 'current_level_name', 'unknown'),
                        gmap_active=False,
                        source=source
                    )
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error capturing position snapshot: {e}")
            return None
    
    def _detect_and_process_changes(self, old: PositionSnapshot, new: PositionSnapshot):
        """Detect and process position changes
        
        Args:
            old: Previous position snapshot
            new: New position snapshot
        """
        # Calculate position change
        old_pos = old.local_position
        new_pos = new.local_position
        
        distance = ((new_pos[0] - old_pos[0]) ** 2 + (new_pos[1] - old_pos[1]) ** 2) ** 0.5
        
        # Check for significant change
        if distance >= self.change_threshold:
            # Determine change type
            level_changed = old.level_name != new.level_name
            segment_changed = old.segment != new.segment
            
            change_type = "movement"
            if level_changed:
                change_type = "transition"
                self.stats['level_changes'] += 1
            elif segment_changed:
                change_type = "warp"
                self.stats['segment_changes'] += 1
            
            if distance > 10.0:  # Large movement likely indicates warp
                change_type = "warp"
                self.stats['warp_events'] += 1
            
            # Create change record
            change = PositionChange(
                timestamp=new.timestamp,
                old_position=old_pos,
                new_position=new_pos,
                change_type=change_type,
                level_change=level_changed,
                segment_change=segment_changed
            )
            
            # Add to change history
            self.change_history.append(change)
            if len(self.change_history) > self.history_size:
                self.change_history = self.change_history[-self.history_size:]
            
            # Trigger callbacks
            self._trigger_callbacks(change)
    
    def _trigger_callbacks(self, change: PositionChange):
        """Trigger registered callbacks for position changes
        
        Args:
            change: PositionChange object
        """
        try:
            # Position change callbacks
            for callback in self.position_change_callbacks:
                try:
                    callback(change)
                except Exception as e:
                    self.logger.debug(f"Position change callback error: {e}")
            
            # Level change callbacks
            if change.level_change:
                for callback in self.level_change_callbacks:
                    try:
                        callback(change)
                    except Exception as e:
                        self.logger.debug(f"Level change callback error: {e}")
            
            # Segment change callbacks
            if change.segment_change:
                for callback in self.segment_change_callbacks:
                    try:
                        callback(change)
                    except Exception as e:
                        self.logger.debug(f"Segment change callback error: {e}")
        
        except Exception as e:
            self.logger.debug(f"Error triggering callbacks: {e}")


# Convenience function for easy integration
def create_position_manager(client=None) -> PositionManager:
    """Create a position manager instance
    
    Args:
        client: Optional PyReborn client
        
    Returns:
        Configured PositionManager instance
    """
    manager = PositionManager(client)
    return manager