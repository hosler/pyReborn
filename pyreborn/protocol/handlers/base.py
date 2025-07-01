"""
Base packet handler interface for PyReborn.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from ...events import EventManager

class PacketHandler(ABC):
    """Base class for packet handlers"""
    
    def __init__(self, events: EventManager, state: Dict[str, Any]):
        self.events = events
        self.state = state
        
    @abstractmethod
    def get_packet_ids(self) -> list[int]:
        """Return list of packet IDs this handler processes"""
        pass
        
    @abstractmethod
    def handle_packet(self, packet_id: int, data: bytes) -> None:
        """Handle a packet"""
        pass
        
    def emit_event(self, event_name: str, data: Dict[str, Any]):
        """Helper to emit events"""
        self.events.emit(event_name, data)