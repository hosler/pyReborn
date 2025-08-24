"""
Movement Coordinator
====================

Centralized movement coordination system that handles:
- Movement validation and physics rules
- Server communication for position updates
- GMAP-aware movement with segment transitions
- Collision detection coordination
- Movement queuing and rate limiting

This consolidates movement logic from pygame client into pyReborn.
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple, List, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MovementResult(Enum):
    """Movement execution results"""
    SUCCESS = "success"
    BLOCKED = "blocked"
    OUT_OF_BOUNDS = "out_of_bounds"
    RATE_LIMITED = "rate_limited"
    INVALID_DIRECTION = "invalid_direction"
    NO_CLIENT = "no_client"


@dataclass
class MovementRequest:
    """Movement request data structure"""
    dx: int
    dy: int
    timestamp: float
    source: str = "unknown"
    priority: int = 0


@dataclass
class MovementResponse:
    """Movement response with complete state information"""
    result: MovementResult
    old_position: Tuple[float, float]
    new_position: Tuple[float, float]
    world_position: Tuple[float, float]
    segment: Tuple[int, int]
    level_name: str
    server_sent: bool
    collision_info: Optional[Dict[str, Any]] = None
    timing_ms: float = 0.0


class MovementCoordinator:
    """Centralized movement coordination and validation system"""
    
    def __init__(self, client=None):
        """Initialize movement coordinator
        
        Args:
            client: PyReborn client for server communication
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Movement state
        self.last_movement_time = 0.0
        self.movement_queue = []
        self.movement_history = []
        
        # Configuration
        self.movement_rate_limit = 0.05  # 50ms between movements (20 moves/sec max)
        self.max_queue_size = 10
        self.history_size = 100
        
        # Collision detection callback
        self.collision_callback: Optional[Callable] = None
        
        # Statistics
        self.stats = {
            'movements_processed': 0,
            'movements_blocked': 0,
            'movements_sent': 0,
            'rate_limited': 0,
            'average_timing': 0.0
        }
        
        self.logger.info("Movement coordinator initialized")
    
    def set_client(self, client):
        """Set PyReborn client reference
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger.info("Movement coordinator connected to PyReborn client")
    
    def set_collision_callback(self, callback: Callable):
        """Set collision detection callback
        
        Args:
            callback: Function that takes (x, y) and returns collision info
        """
        self.collision_callback = callback
        self.logger.debug("Collision detection callback registered")
    
    def request_movement(self, dx: int, dy: int, source: str = "user") -> MovementResponse:
        """Request a movement with full validation and coordination
        
        Args:
            dx: X direction (-1, 0, or 1)
            dy: Y direction (-1, 0, or 1)
            source: Source of the movement request
            
        Returns:
            MovementResponse with complete result information
        """
        start_time = time.time()
        
        # Validate movement direction
        if not self._is_valid_direction(dx, dy):
            return MovementResponse(
                result=MovementResult.INVALID_DIRECTION,
                old_position=(0, 0),
                new_position=(0, 0),
                world_position=(0, 0),
                segment=(0, 0),
                level_name="unknown",
                server_sent=False,
                timing_ms=(time.time() - start_time) * 1000
            )
        
        # Check rate limiting
        current_time = time.time()
        if current_time - self.last_movement_time < self.movement_rate_limit:
            self.stats['rate_limited'] += 1
            return MovementResponse(
                result=MovementResult.RATE_LIMITED,
                old_position=(0, 0),
                new_position=(0, 0),
                world_position=(0, 0),
                segment=(0, 0),
                level_name="unknown",
                server_sent=False,
                timing_ms=(time.time() - start_time) * 1000
            )
        
        # Get current position from client
        if not self.client:
            return MovementResponse(
                result=MovementResult.NO_CLIENT,
                old_position=(0, 0),
                new_position=(0, 0),
                world_position=(0, 0),
                segment=(0, 0),
                level_name="unknown",
                server_sent=False,
                timing_ms=(time.time() - start_time) * 1000
            )
        
        # Get current position and state
        current_state = self._get_current_state()
        old_position = current_state['local_position']
        
        # Calculate new position
        new_x = old_position[0] + dx
        new_y = old_position[1] + dy
        new_position = (new_x, new_y)
        
        # Check collision if callback available
        collision_info = None
        if self.collision_callback:
            collision_info = self.collision_callback(new_x, new_y)
            if collision_info and not collision_info.get('can_move', True):
                self.stats['movements_blocked'] += 1
                return MovementResponse(
                    result=MovementResult.BLOCKED,
                    old_position=old_position,
                    new_position=new_position,
                    world_position=current_state['world_position'],
                    segment=current_state['segment'],
                    level_name=current_state['level_name'],
                    server_sent=False,
                    collision_info=collision_info,
                    timing_ms=(time.time() - start_time) * 1000
                )
        
        # Execute movement
        server_sent = self._execute_movement(dx, dy)
        
        # Get updated state after movement
        new_state = self._get_current_state()
        
        # Record movement
        self.last_movement_time = current_time
        self.stats['movements_processed'] += 1
        if server_sent:
            self.stats['movements_sent'] += 1
        
        # Create response
        response = MovementResponse(
            result=MovementResult.SUCCESS,
            old_position=old_position,
            new_position=new_state['local_position'],
            world_position=new_state['world_position'],
            segment=new_state['segment'],
            level_name=new_state['level_name'],
            server_sent=server_sent,
            collision_info=collision_info,
            timing_ms=(time.time() - start_time) * 1000
        )
        
        # Update statistics
        self._update_timing_stats(response.timing_ms)
        
        # Add to history
        self.movement_history.append(response)
        if len(self.movement_history) > self.history_size:
            self.movement_history = self.movement_history[-self.history_size:]
        
        return response
    
    def queue_movement(self, dx: int, dy: int, source: str = "queued") -> bool:
        """Queue a movement for later execution
        
        Args:
            dx: X direction
            dy: Y direction
            source: Source of the movement
            
        Returns:
            True if queued successfully
        """
        if len(self.movement_queue) >= self.max_queue_size:
            return False
        
        request = MovementRequest(
            dx=dx,
            dy=dy,
            timestamp=time.time(),
            source=source
        )
        
        self.movement_queue.append(request)
        return True
    
    def process_queue(self) -> List[MovementResponse]:
        """Process queued movements
        
        Returns:
            List of movement responses
        """
        responses = []
        
        while self.movement_queue:
            request = self.movement_queue.pop(0)
            response = self.request_movement(request.dx, request.dy, request.source)
            responses.append(response)
            
            # Stop if rate limited
            if response.result == MovementResult.RATE_LIMITED:
                break
        
        return responses
    
    def get_movement_stats(self) -> Dict[str, Any]:
        """Get movement statistics
        
        Returns:
            Dictionary with movement statistics
        """
        return {
            **self.stats,
            'queue_size': len(self.movement_queue),
            'history_size': len(self.movement_history)
        }
    
    def get_recent_movements(self, count: int = 10) -> List[MovementResponse]:
        """Get recent movement history
        
        Args:
            count: Number of recent movements to return
            
        Returns:
            List of recent MovementResponse objects
        """
        return self.movement_history[-count:] if self.movement_history else []
    
    def _is_valid_direction(self, dx: int, dy: int) -> bool:
        """Validate movement direction
        
        Args:
            dx: X direction
            dy: Y direction
            
        Returns:
            True if direction is valid
        """
        # Only allow single-tile movements in cardinal directions
        return (abs(dx) <= 1 and abs(dy) <= 1 and 
                (dx != 0 or dy != 0) and  # Must move somewhere
                not (abs(dx) == 1 and abs(dy) == 1))  # No diagonal movement
    
    def _get_current_state(self) -> Dict[str, Any]:
        """Get current player state from client
        
        Returns:
            Dictionary with current position and state information
        """
        if not self.client:
            return {
                'local_position': (0, 0),
                'world_position': (0, 0),
                'segment': (0, 0),
                'level_name': 'unknown'
            }
        
        try:
            # Try to use GMAP API for comprehensive state
            if hasattr(self.client, 'gmap_api') or hasattr(self.client, '_gmap_api'):
                gmap_api = getattr(self.client, 'gmap_api', getattr(self.client, '_gmap_api', None))
                if gmap_api:
                    render_data = gmap_api.get_gmap_render_data()
                    if render_data:
                        # Find current level
                        current_level = "unknown"
                        for segment in render_data.segments:
                            if segment.is_current_segment:
                                current_level = segment.level_name or "unknown"
                                break
                        
                        return {
                            'local_position': render_data.player_local_position,
                            'world_position': render_data.player_world_position,
                            'segment': render_data.current_segment,
                            'level_name': current_level
                        }
            
            # Fallback to basic client state
            if hasattr(self.client, 'session_manager') and self.client.session_manager:
                session_manager = self.client.session_manager
                if hasattr(session_manager, 'player') and session_manager.player:
                    player = session_manager.player
                    return {
                        'local_position': (player.x, player.y),
                        'world_position': (getattr(player, 'x2', player.x), getattr(player, 'y2', player.y)),
                        'segment': (0, 0),  # Default segment
                        'level_name': getattr(session_manager, 'current_level_name', 'unknown')
                    }
            
            # Ultimate fallback
            return {
                'local_position': (0, 0),
                'world_position': (0, 0),
                'segment': (0, 0),
                'level_name': 'unknown'
            }
            
        except Exception as e:
            self.logger.debug(f"Error getting current state: {e}")
            return {
                'local_position': (0, 0),
                'world_position': (0, 0),
                'segment': (0, 0),
                'level_name': 'unknown'
            }
    
    def _execute_movement(self, dx: int, dy: int) -> bool:
        """Execute movement via client
        
        Args:
            dx: X direction
            dy: Y direction
            
        Returns:
            True if movement was sent to server successfully
        """
        try:
            if hasattr(self.client, 'move'):
                result = self.client.move(dx, dy)
                return bool(result)
            else:
                self.logger.warning("Client has no move method")
                return False
                
        except Exception as e:
            self.logger.error(f"Error executing movement: {e}")
            return False
    
    def _update_timing_stats(self, timing_ms: float):
        """Update timing statistics
        
        Args:
            timing_ms: Timing in milliseconds
        """
        if self.stats['movements_processed'] > 0:
            # Calculate running average
            current_avg = self.stats['average_timing']
            processed = self.stats['movements_processed']
            self.stats['average_timing'] = ((current_avg * (processed - 1)) + timing_ms) / processed
        else:
            self.stats['average_timing'] = timing_ms


class MovementValidator:
    """Validates movement requests and provides detailed feedback"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def validate_movement(self, dx: int, dy: int, current_position: Tuple[float, float], 
                         level_data: Any = None) -> Dict[str, Any]:
        """Validate a movement request
        
        Args:
            dx: X direction
            dy: Y direction  
            current_position: Current (x, y) position
            level_data: Current level data for bounds checking
            
        Returns:
            Validation result dictionary
        """
        validation = {
            'valid': True,
            'issues': [],
            'warnings': [],
            'metadata': {}
        }
        
        # Check direction validity
        if abs(dx) > 1 or abs(dy) > 1:
            validation['valid'] = False
            validation['issues'].append(f"Movement too large: ({dx}, {dy})")
        
        if dx == 0 and dy == 0:
            validation['valid'] = False
            validation['issues'].append("No movement specified")
        
        if abs(dx) == 1 and abs(dy) == 1:
            validation['valid'] = False
            validation['issues'].append("Diagonal movement not allowed")
        
        # Check bounds if level data available
        if level_data and hasattr(level_data, 'width') and hasattr(level_data, 'height'):
            new_x = current_position[0] + dx
            new_y = current_position[1] + dy
            
            if new_x < 0 or new_x >= level_data.width:
                validation['warnings'].append(f"X position {new_x} near level boundary")
            
            if new_y < 0 or new_y >= level_data.height:
                validation['warnings'].append(f"Y position {new_y} near level boundary")
        
        validation['metadata'] = {
            'direction': self._get_direction_name(dx, dy),
            'magnitude': abs(dx) + abs(dy),
            'target_position': (current_position[0] + dx, current_position[1] + dy)
        }
        
        return validation
    
    def _get_direction_name(self, dx: int, dy: int) -> str:
        """Get direction name from delta values"""
        if dx == 1:
            return "east"
        elif dx == -1:
            return "west"
        elif dy == 1:
            return "south"
        elif dy == -1:
            return "north"
        else:
            return "none"


# Convenience function for easy integration
def create_movement_coordinator(client=None) -> MovementCoordinator:
    """Create a movement coordinator instance
    
    Args:
        client: Optional PyReborn client
        
    Returns:
        Configured MovementCoordinator instance
    """
    coordinator = MovementCoordinator(client)
    return coordinator