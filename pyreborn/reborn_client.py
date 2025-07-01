"""
Simplified RebornClient that combines core networking with game functionality.
"""
import logging
from typing import Optional, Dict, Any, List

from .core.client import CoreClient
from .game.actions import GameActions
from .game.queries import GameQueries
from .handlers.registry import create_handler_decorator
from .protocol.enums import ServerToPlayer
from .events import EventType

# Import default handlers
from .handlers.player_handlers import register_player_handlers
from .handlers.level_handlers import register_level_handlers
from .handlers.chat_handlers import register_chat_handlers
from .handlers.combat_handlers import register_combat_handlers
from .handlers.login_handlers import register_login_handlers
from .handlers.board_handlers import register_board_handlers

logger = logging.getLogger(__name__)


class RebornClient(CoreClient):
    """
    Main client for connecting to Graal Reborn servers.
    
    This client provides:
    - Simple API for game actions (move, say, etc.)
    - Extensible packet handling system
    - Clean access to game state
    - Event system for notifications
    """
    
    def __init__(self, host: str, port: int = 14900):
        super().__init__()
        self.host = host
        self.port = port
        
        # Game components
        self.actions = GameActions(self)
        self.queries = GameQueries(self.state)
        
        # Create handler decorator for this client
        self.handler = create_handler_decorator(self.handlers)
        
        # Register default handlers
        self._register_default_handlers()
        
    def _register_default_handlers(self):
        """Register the default packet handlers."""
        register_login_handlers(self.handlers, self.state, self.events)
        register_board_handlers(self.handlers, self.state, self.events)
        register_player_handlers(self.handlers, self.state, self.events)
        register_level_handlers(self.handlers, self.state, self.events)
        register_chat_handlers(self.handlers, self.state, self.events)
        register_combat_handlers(self.handlers, self.state, self.events)
        
    # Convenience methods that delegate to actions
    def move_to(self, x: float, y: float, direction: Optional[int] = None) -> None:
        """Move the player to a position."""
        self.actions.move(x, y, direction)
        
    def say(self, message: str) -> None:
        """Send a chat message."""
        self.actions.say(message)
        
    def drop_bomb(self) -> None:
        """Drop a bomb."""
        self.actions.drop_bomb()
        
    def shoot_arrow(self, direction: Optional[int] = None) -> None:
        """Shoot an arrow."""
        self.actions.shoot_arrow(direction)
        
    def set_nickname(self, nickname: str) -> None:
        """Set player nickname."""
        self.actions.set_nickname(nickname)
        
    def warp_to(self, level_name: str, x: float = 30.0, y: float = 30.5) -> None:
        """Warp to another level."""
        self.actions.warp_to_level(level_name, x, y)
        
    # Convenience query methods
    def find_player(self, name: str) -> Optional[Any]:
        """Find a player by name."""
        players = self.queries.find_players_by_name(name, exact=True)
        return players[0] if players else None
        
    def get_nearby_players(self, radius: float = 10.0) -> List[Any]:
        """Get players near the local player."""
        return self.queries.get_nearby_players(radius)
        
    def get_player_info(self) -> Dict[str, Any]:
        """Get local player information."""
        return self.queries.get_player_stats()
        
    # Event registration helpers
    def on(self, event_type: EventType):
        """
        Decorator for registering event handlers.
        
        Usage:
            @client.on(EventType.CHAT_MESSAGE)
            def handle_chat(data):
                print(f"{data['player']}: {data['message']}")
        """
        def decorator(func):
            self.events.subscribe(event_type, func)
            return func
        return decorator
        
    def once(self, event_type: EventType):
        """
        Decorator for registering one-time event handlers.
        
        Usage:
            @client.once(EventType.LEVEL_CHANGE)
            def on_first_level(data):
                print(f"Entered {data['level_name']}")
        """
        def decorator(func):
            def wrapper(**kwargs):
                func(**kwargs)
                self.events.unsubscribe(event_type, wrapper)
            self.events.subscribe(event_type, wrapper)
            return func
        return decorator
        
    # Status methods
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self.connected
        
    def get_current_level(self) -> Optional[str]:
        """Get current level name."""
        return self.state.current_level.name if self.state.current_level else None
        
    def get_position(self) -> Optional[tuple[float, float]]:
        """Get local player position."""
        if self.state.local_player:
            return (self.state.local_player.x, self.state.local_player.y)
        return None