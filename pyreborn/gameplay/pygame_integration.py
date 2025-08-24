"""
Pygame Integration API
======================

Enhanced APIs specifically designed for pygame client integration.
Provides everything pygame needs in clean, simple interfaces.

Key Features:
- Single API calls for complex operations
- Pygame-optimized data structures
- Performance-focused rendering data
- Clean separation between game logic and rendering
"""

import logging
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass

from .movement_coordinator import MovementCoordinator, MovementResponse
from .position_manager import PositionManager, PositionSnapshot
from .level_adapter import LevelAdapter
from .transition_manager import TransitionManager, TransitionResult
from ..gmap_api.gmap_render_api import GMAPRenderAPI

logger = logging.getLogger(__name__)


@dataclass
class PygameRenderData:
    """Complete rendering data package for pygame clients"""
    # Position data
    player_position: Tuple[float, float]
    player_world_position: Tuple[float, float]
    current_level_name: str
    
    # GMAP data (if applicable)
    gmap_active: bool
    gmap_segments: List[Any] = None
    current_segment: Tuple[int, int] = (0, 0)
    
    # Level data
    current_level: Any = None
    available_levels: List[str] = None
    
    # Performance data
    api_timing_ms: float = 0.0
    data_quality: Dict[str, bool] = None


@dataclass
class PygameGameState:
    """Complete game state for pygame clients"""
    # Player state
    position: Tuple[float, float]
    level: str
    health: int = 100
    
    # World state
    gmap_mode: bool = False
    current_segment: Tuple[int, int] = (0, 0)
    
    # System state
    connected: bool = False
    authenticated: bool = False
    
    # Statistics
    movements_made: int = 0
    levels_visited: int = 0
    uptime_seconds: float = 0.0


class PygameIntegrationAPI:
    """Comprehensive integration API for pygame clients"""
    
    def __init__(self, client=None):
        """Initialize pygame integration API
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Initialize all subsystems
        self.movement_coordinator = MovementCoordinator(client)
        self.position_manager = PositionManager(client)
        self.level_adapter = LevelAdapter(client)
        self.transition_manager = TransitionManager(client)
        
        # GMAP API
        self.gmap_api = None
        if client:
            self.gmap_api = GMAPRenderAPI(client)
        
        # Performance tracking
        self.last_update_time = 0.0
        self.update_count = 0
        
        self.logger.info("Pygame integration API initialized")
    
    def set_client(self, client):
        """Set PyReborn client for all subsystems
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        
        # Update all subsystems
        self.movement_coordinator.set_client(client)
        self.position_manager.set_client(client)
        self.level_adapter.set_client(client)
        self.transition_manager.set_client(client)
        
        # Initialize GMAP API
        if client:
            self.gmap_api = GMAPRenderAPI(client)
        
        self.logger.info("Pygame integration API connected to PyReborn client")
    
    def get_complete_render_data(self) -> PygameRenderData:
        """Get everything pygame needs for rendering in one call
        
        Returns:
            PygameRenderData with all rendering information
        """
        import time
        start_time = time.time()
        
        try:
            # Update position manager
            position_snapshot = self.position_manager.update()
            
            # Get current position
            position = self.position_manager.get_current_position()
            
            # Get current level
            current_level = self.level_adapter.get_current_level()
            available_levels = self.level_adapter.get_available_levels()
            
            # Get GMAP data if applicable
            gmap_data = None
            gmap_active = False
            gmap_segments = []
            current_segment = (0, 0)
            
            if self.gmap_api:
                gmap_data = self.gmap_api.get_gmap_render_data()
                if gmap_data and gmap_data.active:
                    gmap_active = True
                    gmap_segments = gmap_data.segments
                    current_segment = gmap_data.current_segment
            
            # Create complete render data
            render_data = PygameRenderData(
                player_position=position['local'],
                player_world_position=position['world'],
                current_level_name=position['level'],
                gmap_active=gmap_active,
                gmap_segments=gmap_segments,
                current_segment=current_segment,
                current_level=current_level,
                available_levels=available_levels,
                api_timing_ms=(time.time() - start_time) * 1000,
                data_quality=gmap_data.server_data_quality if gmap_data else {}
            )
            
            return render_data
            
        except Exception as e:
            self.logger.error(f"Error getting render data: {e}")
            # Return minimal data
            return PygameRenderData(
                player_position=(0, 0),
                player_world_position=(0, 0),
                current_level_name="unknown",
                gmap_active=False,
                api_timing_ms=(time.time() - start_time) * 1000
            )
    
    def execute_movement(self, dx: int, dy: int) -> MovementResponse:
        """Execute player movement with full coordination
        
        Args:
            dx: X direction (-1, 0, or 1)
            dy: Y direction (-1, 0, or 1)
            
        Returns:
            MovementResponse with complete result information
        """
        return self.movement_coordinator.request_movement(dx, dy, "pygame_client")
    
    def get_game_state(self) -> PygameGameState:
        """Get complete game state for pygame UI
        
        Returns:
            PygameGameState with all game information
        """
        try:
            position = self.position_manager.get_current_position()
            movement_stats = self.movement_coordinator.get_movement_stats()
            
            # Get connection state
            connected = bool(self.client and hasattr(self.client, 'connected') and self.client.connected)
            authenticated = bool(self.client and getattr(self.client, 'authenticated', False))
            
            return PygameGameState(
                position=position['local'],
                level=position['level'],
                gmap_mode=position['gmap_active'],
                current_segment=position['segment'],
                connected=connected,
                authenticated=authenticated,
                movements_made=movement_stats['movements_processed'],
                levels_visited=len(self.level_adapter.get_available_levels()),
                uptime_seconds=time.time() - self.last_update_time if self.last_update_time else 0
            )
            
        except Exception as e:
            self.logger.error(f"Error getting game state: {e}")
            return PygameGameState(
                position=(0, 0),
                level="unknown"
            )
    
    def process_level_link(self, link_data: Dict[str, Any]) -> Optional[TransitionResult]:
        """Process level link interaction
        
        Args:
            link_data: Level link information
            
        Returns:
            TransitionResult if transition was executed
        """
        position = self.position_manager.get_current_position()
        return self.transition_manager.process_level_link(link_data, position['local'])
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics
        
        Returns:
            Dictionary with performance data
        """
        return {
            'movement': self.movement_coordinator.get_movement_stats(),
            'position': self.position_manager.get_stats(),
            'transitions': self.transition_manager.get_transition_stats(),
            'levels': {
                'available_count': len(self.level_adapter.get_available_levels()),
                'current_level': self.level_adapter.get_current_level() is not None
            },
            'api_updates': self.update_count,
            'last_update': self.last_update_time
        }
    
    def update(self) -> Dict[str, Any]:
        """Update all subsystems and return status
        
        Returns:
            Dictionary with update status
        """
        self.last_update_time = time.time()
        self.update_count += 1
        
        try:
            # Update position manager (which updates position tracking)
            position_snapshot = self.position_manager.update()
            
            # Process any queued movements
            queued_responses = self.movement_coordinator.process_queue()
            
            return {
                'position_updated': position_snapshot is not None,
                'movements_processed': len(queued_responses),
                'update_count': self.update_count,
                'timing': time.time() - self.last_update_time
            }
            
        except Exception as e:
            self.logger.error(f"Error during update: {e}")
            return {
                'error': str(e),
                'update_count': self.update_count
            }


# Convenience function for easy integration
def create_pygame_integration_api(client=None) -> PygameIntegrationAPI:
    """Create a pygame integration API instance
    
    Args:
        client: Optional PyReborn client
        
    Returns:
        Configured PygameIntegrationAPI instance
    """
    api = PygameIntegrationAPI(client)
    return api