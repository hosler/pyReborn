"""
Game State Manager
==================

Manages game state transitions and state-specific updates.
"""

from enum import Enum
import logging

logger = logging.getLogger(__name__)


class GameState(Enum):
    """Game states"""
    MENU = 1
    CONNECTING = 2
    PLAYING = 3
    PAUSED = 4
    

class GameStateManager:
    """Manages game state and transitions"""
    
    def __init__(self):
        self.state = GameState.MENU
        self.previous_state = None
        
    def transition_to(self, new_state: GameState):
        """Transition to a new state"""
        if new_state != self.state:
            self.previous_state = self.state
            self.state = new_state
            logger.debug(f"State transition: {self.previous_state.name} -> {self.state.name}")
            
    def is_playing(self) -> bool:
        """Check if in playing state"""
        return self.state == GameState.PLAYING
        
    def is_menu(self) -> bool:
        """Check if in menu state"""
        return self.state == GameState.MENU
        
    def is_connecting(self) -> bool:
        """Check if connecting"""
        return self.state == GameState.CONNECTING
        
    def is_paused(self) -> bool:
        """Check if paused"""
        return self.state == GameState.PAUSED