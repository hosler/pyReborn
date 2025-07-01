"""
Extensible packet handler registry system.
"""
from typing import Dict, Callable, Optional, Any, List
from dataclasses import dataclass
import logging

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader

logger = logging.getLogger(__name__)


@dataclass
class HandlerInfo:
    """Information about a registered handler."""
    handler: Callable
    packet_id: int
    name: str
    priority: int = 0  # Higher priority handlers run first
    
    
class PacketHandlerRegistry:
    """
    Registry for packet handlers that allows custom handlers to be registered.
    """
    
    def __init__(self):
        self._handlers: Dict[int, List[HandlerInfo]] = {}
        self._middleware: List[Callable] = []
        self._default_handler: Optional[Callable] = None
        
    def register(self, packet_id: int, handler: Callable, 
                 name: Optional[str] = None, priority: int = 0) -> None:
        """
        Register a packet handler.
        
        Args:
            packet_id: The packet ID to handle
            handler: Function that takes (packet_reader, game_state) and returns result
            name: Optional name for the handler
            priority: Higher priority handlers run first
        """
        if packet_id not in self._handlers:
            self._handlers[packet_id] = []
            
        info = HandlerInfo(
            handler=handler,
            packet_id=packet_id,
            name=name or handler.__name__,
            priority=priority
        )
        
        self._handlers[packet_id].append(info)
        self._handlers[packet_id].sort(key=lambda x: x.priority, reverse=True)
        
        logger.debug(f"Registered handler {info.name} for packet {packet_id}")
        
    def unregister(self, packet_id: int, handler_name: str) -> bool:
        """
        Unregister a specific handler.
        
        Returns:
            True if handler was found and removed
        """
        if packet_id not in self._handlers:
            return False
            
        original_count = len(self._handlers[packet_id])
        self._handlers[packet_id] = [
            h for h in self._handlers[packet_id] 
            if h.name != handler_name
        ]
        
        if len(self._handlers[packet_id]) == 0:
            del self._handlers[packet_id]
            
        return len(self._handlers[packet_id]) < original_count
        
    def add_middleware(self, middleware: Callable) -> None:
        """
        Add middleware that processes all packets.
        
        Middleware should have signature: (packet_id, packet_reader, game_state) -> Optional[Any]
        If middleware returns non-None, that value is used and handlers are skipped.
        """
        self._middleware.append(middleware)
        
    def set_default_handler(self, handler: Callable) -> None:
        """Set handler for unregistered packet types."""
        self._default_handler = handler
        
    def handle_packet(self, packet_id: int, packet_reader: PacketReader, 
                     game_state: Any) -> Optional[Any]:
        """
        Handle a packet using registered handlers.
        
        Returns:
            Result from handler or None
        """
        # Run middleware first
        for middleware in self._middleware:
            result = middleware(packet_id, packet_reader, game_state)
            if result is not None:
                return result
                
        # Get handlers for this packet
        handlers = self._handlers.get(packet_id, [])
        
        if not handlers:
            if self._default_handler:
                return self._default_handler(packet_id, packet_reader, game_state)
            logger.debug(f"No handler registered for packet {packet_id}")
            return None
            
        # Run handlers in priority order
        for handler_info in handlers:
            try:
                result = handler_info.handler(packet_reader, game_state)
                if result is not None:
                    return result
            except Exception as e:
                logger.error(f"Handler {handler_info.name} failed: {e}")
                
        return None
        
    def get_registered_packets(self) -> List[int]:
        """Get list of packet IDs with registered handlers."""
        return list(self._handlers.keys())
        
    def get_handlers_for_packet(self, packet_id: int) -> List[HandlerInfo]:
        """Get all handlers for a specific packet ID."""
        return self._handlers.get(packet_id, []).copy()
        
    def clear(self) -> None:
        """Clear all registered handlers and middleware."""
        self._handlers.clear()
        self._middleware.clear()
        self._default_handler = None


def create_handler_decorator(registry: PacketHandlerRegistry):
    """
    Create a decorator for registering packet handlers.
    
    Usage:
        handler = create_handler_decorator(registry)
        
        @handler(ServerToPlayer.PLAYER_PROPS)
        def handle_player_props(packet_reader, game_state):
            # Handle packet
            pass
    """
    def handler(packet_id: int, priority: int = 0):
        def decorator(func: Callable):
            registry.register(packet_id, func, priority=priority)
            return func
        return decorator
    return handler