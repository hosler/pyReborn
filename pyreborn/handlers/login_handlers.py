"""
Login and authentication packet handlers.
"""
import logging

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_login_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register login-related packet handlers."""
    
    def handle_signature(reader: PacketReader, state: GameState):
        """Handle signature packet (login response)."""
        # Signature contains server info
        signature_data = reader.read_gstring() if reader.bytes_available() > 0 else ""
        
        logger.info(f"Login accepted - signature: {signature_data}")
        
        events.emit(EventType.LOGIN_SUCCESS,
            signature=signature_data
        )
        
        return signature_data
        
    def handle_start_message(reader: PacketReader, state: GameState):
        """Handle start message (MOTD)."""
        message = reader.read_gstring() if reader.bytes_available() > 0 else ""
        
        logger.info(f"Server message: {message}")
        
        events.emit(EventType.SERVER_MESSAGE,
            message=message
        )
        
        return message
    
    # Register handlers
    registry.register(ServerToPlayer.PLO_SIGNATURE, handle_signature)
    registry.register(ServerToPlayer.PLO_STARTMESSAGE, handle_start_message)