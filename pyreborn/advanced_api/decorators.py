#!/usr/bin/env python3
"""
Decorator-Based Event Handlers
===============================

Provides a clean, decorator-based API for handling PyReborn events.
Inspired by modern web frameworks and Discord.py's event handling patterns.

This system allows users to register event handlers using decorators, making
event-driven code more readable and organized.

Example usage:
    @client.on_packet(IncomingPackets.PLAYER_CHAT)
    def handle_chat(player_id: int, message: str):
        print(f"Player {player_id}: {message}")
    
    @client.on_event("player_moved")
    def handle_movement(player):
        print(f"Player moved to {player.x}, {player.y}")
"""

import logging
import functools
from typing import Callable, Dict, List, Any, Optional, Union
from collections import defaultdict
import inspect

from ..protocol.packet_enums import IncomingPackets, OutgoingPackets

logger = logging.getLogger(__name__)


class EventDecorator:
    """
    Event decorator system for PyReborn clients.
    
    Provides decorator-based event registration that's clean and easy to use.
    """
    
    def __init__(self, client=None):
        """
        Initialize event decorator system.
        
        Args:
            client: Optional client instance to bind to
        """
        self.client = client
        self._packet_handlers: Dict[int, List[Callable]] = defaultdict(list)
        self._event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._filters: Dict[str, List[Callable]] = defaultdict(list)
        self._middleware: List[Callable] = []
        
    def on_packet(self, packet_type: Union[IncomingPackets, int]):
        """
        Decorator for registering packet handlers.
        
        Args:
            packet_type: Packet type to handle (enum or int)
            
        Returns:
            Decorator function
            
        Example:
            @client.on_packet(IncomingPackets.PLAYER_CHAT)
            def handle_chat(packet_data):
                print(f"Chat: {packet_data}")
        """
        def decorator(func: Callable) -> Callable:
            packet_id = packet_type.value if isinstance(packet_type, IncomingPackets) else packet_type
            self._packet_handlers[packet_id].append(func)
            
            # Add metadata to function
            func._pyreborn_packet_handler = True
            func._pyreborn_packet_id = packet_id
            
            logger.debug(f"Registered packet handler for packet {packet_id}: {func.__name__}")
            return func
            
        return decorator
    
    def on_event(self, event_type: str):
        """
        Decorator for registering high-level event handlers.
        
        Args:
            event_type: Event type to handle (e.g., "player_moved", "player_chat")
            
        Returns:
            Decorator function
            
        Example:
            @client.on_event("player_moved")
            def handle_movement(player):
                print(f"Player moved to {player.x}, {player.y}")
        """
        def decorator(func: Callable) -> Callable:
            self._event_handlers[event_type].append(func)
            
            # Add metadata to function
            func._pyreborn_event_handler = True
            func._pyreborn_event_type = event_type
            
            logger.debug(f"Registered event handler for event {event_type}: {func.__name__}")
            return func
            
        return decorator
    
    def on_chat(self, filter_func: Optional[Callable[[str], bool]] = None):
        """
        Decorator for registering chat message handlers.
        
        Args:
            filter_func: Optional filter function to apply to messages
            
        Returns:
            Decorator function
            
        Example:
            @client.on_chat()
            def handle_all_chat(player_id, message):
                print(f"Chat: {message}")
            
            @client.on_chat(lambda msg: "help" in msg.lower())
            def handle_help_requests(player_id, message):
                print("Help requested!")
        """
        def decorator(func: Callable) -> Callable:
            # Register as both packet and event handler
            self._packet_handlers[IncomingPackets.TO_ALL.value].append(
                self._create_chat_wrapper(func, filter_func)
            )
            self._event_handlers["player_chat"].append(
                self._create_chat_wrapper(func, filter_func)
            )
            
            # Add metadata
            func._pyreborn_chat_handler = True
            func._pyreborn_chat_filter = filter_func
            
            logger.debug(f"Registered chat handler: {func.__name__}")
            return func
            
        return decorator
    
    def on_player_action(self, action_type: str):
        """
        Decorator for registering player action handlers.
        
        Args:
            action_type: Type of player action ("moved", "attacked", "died", etc.)
            
        Returns:
            Decorator function
            
        Example:
            @client.on_player_action("moved")
            def handle_player_movement(player):
                print(f"Player {player.account} moved")
        """
        def decorator(func: Callable) -> Callable:
            event_name = f"player_{action_type}"
            self._event_handlers[event_name].append(func)
            
            # Add metadata
            func._pyreborn_player_action_handler = True
            func._pyreborn_action_type = action_type
            
            logger.debug(f"Registered player action handler for {action_type}: {func.__name__}")
            return func
            
        return decorator
    
    def filter_events(self, condition: Callable[[Any], bool]):
        """
        Decorator for adding event filters.
        
        Args:
            condition: Filter condition function
            
        Returns:
            Decorator function
            
        Example:
            @client.filter_events(lambda event: event.player_id != my_player_id)
            @client.on_event("player_moved")
            def handle_other_player_movement(event):
                print("Another player moved")
        """
        def decorator(func: Callable) -> Callable:
            # Find what events this function handles
            if hasattr(func, '_pyreborn_event_type'):
                event_type = func._pyreborn_event_type
                self._filters[event_type].append(condition)
            elif hasattr(func, '_pyreborn_packet_id'):
                packet_id = str(func._pyreborn_packet_id)
                self._filters[packet_id].append(condition)
            
            func._pyreborn_filtered = True
            func._pyreborn_filter_condition = condition
            
            return func
            
        return decorator
    
    def middleware(self, func: Callable) -> Callable:
        """
        Decorator for registering middleware that processes all events.
        
        Args:
            func: Middleware function
            
        Returns:
            Decorated function
            
        Example:
            @client.middleware
            def log_all_events(event_type, event_data, next_handler):
                print(f"Processing {event_type}")
                return next_handler(event_data)
        """
        self._middleware.append(func)
        func._pyreborn_middleware = True
        
        logger.debug(f"Registered middleware: {func.__name__}")
        return func
    
    def _create_chat_wrapper(self, handler: Callable, filter_func: Optional[Callable] = None):
        """Create a wrapper for chat handlers that extracts player and message"""
        @functools.wraps(handler)
        def wrapper(packet_data):
            try:
                # Extract player ID and message from packet data
                # This would need to be adapted based on actual packet structure
                if isinstance(packet_data, dict):
                    player_id = packet_data.get('player_id', 0)
                    message = packet_data.get('message', '')
                elif hasattr(packet_data, 'message'):
                    player_id = getattr(packet_data, 'player_id', 0)
                    message = packet_data.message
                else:
                    # Fallback
                    player_id = 0
                    message = str(packet_data)
                
                # Apply filter if provided
                if filter_func and not filter_func(message):
                    return
                
                # Call the handler with extracted data
                sig = inspect.signature(handler)
                param_count = len(sig.parameters)
                
                if param_count == 1:
                    handler(message)
                elif param_count == 2:
                    handler(player_id, message)
                else:
                    handler(packet_data)
                    
            except Exception as e:
                logger.error(f"Error in chat handler {handler.__name__}: {e}")
        
        return wrapper
    
    def process_packet(self, packet_id: int, packet_data: Any) -> bool:
        """
        Process a packet through registered handlers.
        
        Args:
            packet_id: Packet ID
            packet_data: Packet data
            
        Returns:
            True if handled, False otherwise
        """
        handlers = self._packet_handlers.get(packet_id, [])
        if not handlers:
            return False
        
        # Apply middleware
        for middleware in self._middleware:
            try:
                packet_data = middleware(f"packet_{packet_id}", packet_data, lambda x: x)
            except Exception as e:
                logger.error(f"Middleware error: {e}")
        
        # Apply filters and call handlers
        for handler in handlers:
            try:
                # Check filters
                filters = self._filters.get(str(packet_id), [])
                if any(not filter_func(packet_data) for filter_func in filters):
                    continue
                
                # Call handler
                handler(packet_data)
                
            except Exception as e:
                logger.error(f"Handler error in {handler.__name__}: {e}")
        
        return True
    
    def process_event(self, event_type: str, event_data: Any) -> bool:
        """
        Process an event through registered handlers.
        
        Args:
            event_type: Event type
            event_data: Event data
            
        Returns:
            True if handled, False otherwise
        """
        handlers = self._event_handlers.get(event_type, [])
        if not handlers:
            return False
        
        # Apply middleware
        for middleware in self._middleware:
            try:
                event_data = middleware(event_type, event_data, lambda x: x)
            except Exception as e:
                logger.error(f"Middleware error: {e}")
        
        # Apply filters and call handlers
        for handler in handlers:
            try:
                # Check filters
                filters = self._filters.get(event_type, [])
                if any(not filter_func(event_data) for filter_func in filters):
                    continue
                
                # Call handler
                handler(event_data)
                
            except Exception as e:
                logger.error(f"Handler error in {handler.__name__}: {e}")
        
        return True
    
    def get_registered_handlers(self) -> Dict[str, List[str]]:
        """
        Get information about registered handlers.
        
        Returns:
            Dictionary with handler information
        """
        return {
            "packet_handlers": {
                str(packet_id): [h.__name__ for h in handlers] 
                for packet_id, handlers in self._packet_handlers.items()
            },
            "event_handlers": {
                event_type: [h.__name__ for h in handlers]
                for event_type, handlers in self._event_handlers.items()
            },
            "middleware": [m.__name__ for m in self._middleware]
        }


class DecoratedClient:
    """
    Client wrapper that provides decorator-based event handling.
    
    This can be used to wrap any PyReborn client (sync or async) to add
    decorator-based event handling capabilities.
    """
    
    def __init__(self, client):
        """
        Initialize decorated client.
        
        Args:
            client: PyReborn client instance to wrap
        """
        self.client = client
        self.decorators = EventDecorator(client)
        
        # Set up packet/event routing if the client supports it
        self._setup_event_routing()
    
    def _setup_event_routing(self):
        """Set up routing from client events to decorator handlers"""
        # This would integrate with the client's event system
        # For now, this is a placeholder for future integration
        pass
    
    # Expose decorator methods
    def on_packet(self, packet_type):
        """Register packet handler decorator"""
        return self.decorators.on_packet(packet_type)
    
    def on_event(self, event_type):
        """Register event handler decorator"""
        return self.decorators.on_event(event_type)
    
    def on_chat(self, filter_func=None):
        """Register chat handler decorator"""
        return self.decorators.on_chat(filter_func)
    
    def on_player_action(self, action_type):
        """Register player action handler decorator"""
        return self.decorators.on_player_action(action_type)
    
    def filter_events(self, condition):
        """Register event filter decorator"""
        return self.decorators.filter_events(condition)
    
    def middleware(self, func):
        """Register middleware decorator"""
        return self.decorators.middleware(func)
    
    # Delegate all other methods to the wrapped client
    def __getattr__(self, name):
        return getattr(self.client, name)


def create_decorated_client(client) -> DecoratedClient:
    """
    Create a decorated client wrapper.
    
    Args:
        client: PyReborn client instance
        
    Returns:
        DecoratedClient with decorator support
    """
    return DecoratedClient(client)


# Convenience function to add decorators to any client
def with_decorators(client_func: Callable) -> Callable:
    """
    Decorator to automatically add decorator support to client creation functions.
    
    Args:
        client_func: Function that returns a PyReborn client
        
    Returns:
        Decorated function that returns a DecoratedClient
        
    Example:
        @with_decorators
        def create_my_client():
            return Client("localhost", 14900)
        
        client = create_my_client()
        
        @client.on_chat()
        def handle_chat(player_id, message):
            print(f"Chat: {message}")
    """
    @functools.wraps(client_func)
    def wrapper(*args, **kwargs):
        client = client_func(*args, **kwargs)
        return create_decorated_client(client)
    
    return wrapper


__all__ = [
    'EventDecorator',
    'DecoratedClient', 
    'create_decorated_client',
    'with_decorators'
]