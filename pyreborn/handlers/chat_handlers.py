"""
Chat and communication packet handlers.
"""
import logging
from typing import Dict, Any

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_chat_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register all chat-related packet handlers."""
    
    def handle_chat(reader: PacketReader, state: GameState):
        """Handle chat messages."""
        message = reader.read_string()
        
        # Parse message format: "playername: message"
        if ': ' in message:
            player_name, chat_text = message.split(': ', 1)
        else:
            player_name = "Server"
            chat_text = message
            
        # Add to state
        state.add_chat_message(player_name, chat_text)
        
        # Emit event
        events.emit(EventType.CHAT_MESSAGE,
            player=player_name,
            message=chat_text,
            full_message=message
        )
        
        logger.info(f"Chat: {message}")
        return {'player': player_name, 'message': chat_text}
        
    def handle_private_message(reader: PacketReader, state: GameState):
        """Handle private messages."""
        message = reader.read_string()
        
        # Parse format: "playername: message"
        if ': ' in message:
            sender, pm_text = message.split(': ', 1)
        else:
            sender = "Unknown"
            pm_text = message
            
        events.emit(EventType.PRIVATE_MESSAGE,
            sender=sender,
            message=pm_text,
            full_message=message
        )
        
        logger.info(f"PM from {sender}: {pm_text}")
        return {'sender': sender, 'message': pm_text}
        
    def handle_server_message(reader: PacketReader, state: GameState):
        """Handle server messages."""
        message = reader.read_string()
        
        state.add_chat_message("Server", message)
        
        events.emit(EventType.SERVER_MESSAGE,
            message=message
        )
        
        logger.info(f"Server: {message}")
        return message
        
    def handle_guild_chat(reader: PacketReader, state: GameState):
        """Handle guild chat messages."""
        message = reader.read_string()
        
        # Parse format similar to regular chat
        if ': ' in message:
            player_name, guild_text = message.split(': ', 1)
        else:
            player_name = "Guild"
            guild_text = message
            
        events.emit(EventType.GUILD_MESSAGE,
            player=player_name,
            message=guild_text,
            full_message=message
        )
        
        logger.info(f"Guild - {player_name}: {guild_text}")
        return {'player': player_name, 'message': guild_text}
        
    def handle_toall_message(reader: PacketReader, state: GameState):
        """Handle server-wide broadcast messages."""
        message = reader.read_string()
        
        state.add_chat_message("Broadcast", message)
        
        events.emit(EventType.TOALL_MESSAGE,
            message=message
        )
        
        logger.info(f"[TOALL] {message}")
        return message
    
    # Register all handlers
    registry.register(ServerToPlayer.PLO_TOALL, handle_chat)
    registry.register(ServerToPlayer.PLO_PRIVATEMESSAGE, handle_private_message)
    registry.register(ServerToPlayer.PLO_RC_ADMINMESSAGE, handle_server_message)
    registry.register(ServerToPlayer.PLO_TOALL, handle_guild_chat, name="handle_guild_chat", priority=5)
    registry.register(ServerToPlayer.PLO_TOALL, handle_toall_message, name="handle_toall_message", priority=1)