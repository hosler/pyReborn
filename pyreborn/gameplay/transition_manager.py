"""
Transition Manager
==================

Centralized level transition and warp management system that handles:
- Level link detection and processing
- Warp coordinate calculations
- GMAP transition management
- Transition validation and execution
- Position calculation for target levels

This consolidates transition logic from pygame client into pyReborn.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple, List, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TransitionType(Enum):
    """Types of level transitions"""
    NORMAL = "normal"
    PLAYERX = "playerx"
    PLAYERY = "playery"
    GMAP_WARP = "gmap_warp"
    SEGMENT_CROSSING = "segment_crossing"


@dataclass
class LevelLink:
    """Level link data structure"""
    target_level: str
    x: float
    y: float
    width: float
    height: float
    target_x: float = 0.0
    target_y: float = 0.0
    link_type: str = "normal"


@dataclass
class TransitionRequest:
    """Level transition request"""
    target_level: str
    target_position: Tuple[float, float]
    transition_type: TransitionType
    source_position: Tuple[float, float]
    link_data: Optional[LevelLink] = None
    timestamp: float = 0.0


@dataclass
class TransitionResult:
    """Level transition execution result"""
    success: bool
    transition_type: TransitionType
    from_level: str
    to_level: str
    from_position: Tuple[float, float]
    to_position: Tuple[float, float]
    server_notified: bool
    timing_ms: float
    error_message: Optional[str] = None


class TransitionManager:
    """Centralized level transition management"""
    
    def __init__(self, client=None):
        """Initialize transition manager
        
        Args:
            client: PyReborn client for server communication
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Transition tracking
        self.active_transition: Optional[TransitionRequest] = None
        self.transition_history: List[TransitionResult] = []
        
        # Configuration
        self.history_size = 50
        self.transition_timeout = 5.0  # 5 second timeout for transitions
        
        # Callbacks
        self.transition_start_callbacks: List[Callable] = []
        self.transition_complete_callbacks: List[Callable] = []
        
        # Statistics
        self.stats = {
            'transitions_processed': 0,
            'transitions_successful': 0,
            'gmap_transitions': 0,
            'link_transitions': 0,
            'average_timing': 0.0
        }
        
        self.logger.info("Transition manager initialized")
    
    def set_client(self, client):
        """Set PyReborn client reference
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger.info("Transition manager connected to PyReborn client")
    
    def add_transition_start_callback(self, callback: Callable):
        """Add callback for transition start events
        
        Args:
            callback: Function to call when transition starts
        """
        self.transition_start_callbacks.append(callback)
    
    def add_transition_complete_callback(self, callback: Callable):
        """Add callback for transition completion events
        
        Args:
            callback: Function to call when transition completes
        """
        self.transition_complete_callbacks.append(callback)
    
    def process_level_link(self, link_data: Dict[str, Any], player_position: Tuple[float, float]) -> Optional[TransitionResult]:
        """Process a level link for potential transition
        
        Args:
            link_data: Level link information
            player_position: Current player position
            
        Returns:
            TransitionResult if transition was executed
        """
        try:
            # Parse link data
            target_level = link_data.get('target_level', '')
            link_x = link_data.get('x', 0)
            link_y = link_data.get('y', 0)
            link_width = link_data.get('width', 1)
            link_height = link_data.get('height', 1)
            target_x = link_data.get('target_x', 0)
            target_y = link_data.get('target_y', 0)
            link_type = link_data.get('type', 'normal')
            
            # Check if player is within link bounds
            player_x, player_y = player_position
            
            if not self._is_position_in_link_bounds(player_x, player_y, link_x, link_y, link_width, link_height):
                return None  # Player not in link area
            
            # Create link object
            link = LevelLink(
                target_level=target_level,
                x=link_x,
                y=link_y,
                width=link_width,
                height=link_height,
                target_x=target_x,
                target_y=target_y,
                link_type=link_type
            )
            
            # Determine transition type
            transition_type = TransitionType.NORMAL
            if link_type == "playerx":
                transition_type = TransitionType.PLAYERX
            elif link_type == "playery":
                transition_type = TransitionType.PLAYERY
            
            # Calculate target position
            calculated_target = self._calculate_target_position(link, player_position)
            
            # Create transition request
            request = TransitionRequest(
                target_level=target_level,
                target_position=calculated_target,
                transition_type=transition_type,
                source_position=player_position,
                link_data=link,
                timestamp=time.time()
            )
            
            # Execute transition
            return self.execute_transition(request)
            
        except Exception as e:
            self.logger.error(f"Error processing level link: {e}")
            return None
    
    def execute_transition(self, request: TransitionRequest) -> TransitionResult:
        """Execute a level transition
        
        Args:
            request: TransitionRequest to execute
            
        Returns:
            TransitionResult with execution details
        """
        start_time = time.time()
        
        try:
            # Get current state
            current_level = "unknown"
            if self.client and hasattr(self.client, 'session_manager'):
                session_manager = self.client.session_manager
                if session_manager:
                    current_level = getattr(session_manager, 'current_level_name', 'unknown')
            
            # Trigger start callbacks
            self._trigger_start_callbacks(request)
            
            # Execute the transition based on type
            server_notified = False
            
            if request.transition_type == TransitionType.GMAP_WARP:
                server_notified = self._execute_gmap_transition(request)
            else:
                server_notified = self._execute_normal_transition(request)
            
            # Create result
            result = TransitionResult(
                success=server_notified,
                transition_type=request.transition_type,
                from_level=current_level,
                to_level=request.target_level,
                from_position=request.source_position,
                to_position=request.target_position,
                server_notified=server_notified,
                timing_ms=(time.time() - start_time) * 1000
            )
            
            # Update statistics
            self.stats['transitions_processed'] += 1
            if server_notified:
                self.stats['transitions_successful'] += 1
            
            if request.transition_type == TransitionType.GMAP_WARP:
                self.stats['gmap_transitions'] += 1
            else:
                self.stats['link_transitions'] += 1
            
            self._update_timing_stats(result.timing_ms)
            
            # Add to history
            self.transition_history.append(result)
            if len(self.transition_history) > self.history_size:
                self.transition_history = self.transition_history[-self.history_size:]
            
            # Trigger completion callbacks
            self._trigger_complete_callbacks(result)
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error executing transition: {error_msg}")
            
            return TransitionResult(
                success=False,
                transition_type=request.transition_type,
                from_level="unknown",
                to_level=request.target_level,
                from_position=request.source_position,
                to_position=request.target_position,
                server_notified=False,
                timing_ms=(time.time() - start_time) * 1000,
                error_message=error_msg
            )
    
    def get_transition_stats(self) -> Dict[str, Any]:
        """Get transition statistics
        
        Returns:
            Dictionary with transition statistics
        """
        return {
            **self.stats,
            'history_size': len(self.transition_history),
            'active_transition': self.active_transition is not None
        }
    
    def get_recent_transitions(self, count: int = 10) -> List[TransitionResult]:
        """Get recent transition history
        
        Args:
            count: Number of recent transitions to return
            
        Returns:
            List of recent TransitionResult objects
        """
        return self.transition_history[-count:] if self.transition_history else []
    
    def _is_position_in_link_bounds(self, player_x: float, player_y: float, 
                                  link_x: float, link_y: float, 
                                  link_width: float, link_height: float) -> bool:
        """Check if player position is within link bounds
        
        Args:
            player_x: Player X position
            player_y: Player Y position
            link_x: Link X position
            link_y: Link Y position
            link_width: Link width
            link_height: Link height
            
        Returns:
            True if player is within link bounds
        """
        return (link_x <= player_x < link_x + link_width and
                link_y <= player_y < link_y + link_height)
    
    def _calculate_target_position(self, link: LevelLink, player_position: Tuple[float, float]) -> Tuple[float, float]:
        """Calculate target position for transition
        
        Args:
            link: LevelLink object
            player_position: Current player position
            
        Returns:
            Calculated target position
        """
        if link.link_type == "playerx":
            # Use player's current X coordinate, link's target Y
            return (player_position[0], link.target_y)
        elif link.link_type == "playery":
            # Use link's target X, player's current Y coordinate
            return (link.target_x, player_position[1])
        else:
            # Normal link - use specified target coordinates
            return (link.target_x, link.target_y)
    
    def _execute_normal_transition(self, request: TransitionRequest) -> bool:
        """Execute normal level transition
        
        Args:
            request: TransitionRequest to execute
            
        Returns:
            True if server was notified successfully
        """
        if not self.client:
            return False
        
        try:
            # Use client's level warp functionality if available
            if hasattr(self.client, 'warp_to_level'):
                return self.client.warp_to_level(
                    request.target_level, 
                    request.target_position[0], 
                    request.target_position[1]
                )
            
            # Fallback: Set level and position separately
            success = True
            
            # Update level if client has level changing capability
            if hasattr(self.client, 'change_level'):
                success = self.client.change_level(request.target_level)
            
            # Update position
            if success and hasattr(self.client, 'set_position'):
                success = self.client.set_position(
                    request.target_position[0], 
                    request.target_position[1]
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error executing normal transition: {e}")
            return False
    
    def _execute_gmap_transition(self, request: TransitionRequest) -> bool:
        """Execute GMAP transition
        
        Args:
            request: TransitionRequest to execute
            
        Returns:
            True if server was notified successfully
        """
        if not self.client:
            return False
        
        try:
            # GMAP transitions are handled by the GMAP system
            if hasattr(self.client, 'gmap_manager') and self.client.gmap_manager:
                gmap_manager = self.client.gmap_manager
                
                # Calculate segment from target position
                target_x, target_y = request.target_position
                segment_x = int(target_x // 64)
                segment_y = int(target_y // 64)
                local_x = target_x % 64
                local_y = target_y % 64
                
                # Update GMAP position
                resolved_level = gmap_manager.update_world_position(
                    target_x, target_y, request.target_level
                )
                
                return resolved_level is not None
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error executing GMAP transition: {e}")
            return False
    
    def _trigger_start_callbacks(self, request: TransitionRequest):
        """Trigger transition start callbacks
        
        Args:
            request: TransitionRequest being started
        """
        for callback in self.transition_start_callbacks:
            try:
                callback(request)
            except Exception as e:
                self.logger.debug(f"Transition start callback error: {e}")
    
    def _trigger_complete_callbacks(self, result: TransitionResult):
        """Trigger transition complete callbacks
        
        Args:
            result: TransitionResult from completed transition
        """
        for callback in self.transition_complete_callbacks:
            try:
                callback(result)
            except Exception as e:
                self.logger.debug(f"Transition complete callback error: {e}")
    
    def _update_timing_stats(self, timing_ms: float):
        """Update timing statistics
        
        Args:
            timing_ms: Timing in milliseconds
        """
        if self.stats['transitions_processed'] > 0:
            current_avg = self.stats['average_timing']
            processed = self.stats['transitions_processed']
            self.stats['average_timing'] = ((current_avg * (processed - 1)) + timing_ms) / processed
        else:
            self.stats['average_timing'] = timing_ms


# Convenience function for easy integration
def create_transition_manager(client=None) -> TransitionManager:
    """Create a transition manager instance
    
    Args:
        client: Optional PyReborn client
        
    Returns:
        Configured TransitionManager instance
    """
    manager = TransitionManager(client)
    return manager