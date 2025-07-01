"""
Base classes and interfaces for packet handlers.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from ..protocol.packets import PacketReader
from ..game.state import GameState


class BasePacketHandler(ABC):
    """
    Abstract base class for packet handlers.
    
    Subclasses can implement handlers for specific packet types.
    """
    
    def __init__(self, game_state: GameState):
        self.game_state = game_state
        
    @abstractmethod
    def get_handled_packets(self) -> dict[int, str]:
        """
        Return a dict of packet_id -> handler_method_name.
        
        Example:
            return {
                ServerToPlayer.PLAYER_PROPS: 'handle_player_props',
                ServerToPlayer.CHAT: 'handle_chat',
            }
        """
        pass
        
    def handle(self, packet_id: int, packet_reader: PacketReader) -> Optional[Any]:
        """
        Route packet to appropriate handler method.
        """
        handlers = self.get_handled_packets()
        method_name = handlers.get(packet_id)
        
        if method_name and hasattr(self, method_name):
            method = getattr(self, method_name)
            return method(packet_reader)
            
        return None


class PacketHandlerMixin:
    """
    Mixin that provides utilities for packet handlers.
    """
    
    @staticmethod
    def read_player_props(packet_reader: PacketReader) -> dict:
        """Read common player property format."""
        props = {}
        
        # Read standard properties
        if packet_reader.bytes_available() >= 1:
            props['id'] = packet_reader.read_byte()
            
        if packet_reader.bytes_available() >= 2:
            props['x'] = packet_reader.read_byte() / 2.0
            props['y'] = packet_reader.read_byte() / 2.0
            
        return props
        
    @staticmethod
    def read_string_list(packet_reader: PacketReader) -> list[str]:
        """Read a newline-separated string list."""
        data = packet_reader.read_string()
        return [s.strip() for s in data.split('\n') if s.strip()]