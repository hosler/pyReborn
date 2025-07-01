"""
Packet handler registry for PyReborn.
Allows registration and lookup of packet handlers.
"""

from typing import Dict, Type, Optional, Callable, Any
from .base import PacketHandler

class HandlerRegistry:
    """Registry for packet handlers"""
    
    def __init__(self):
        self.handlers: Dict[int, PacketHandler] = {}
        self.handler_classes: Dict[int, Type[PacketHandler]] = {}
        
    def register_handler_class(self, handler_class: Type[PacketHandler]):
        """Register a handler class"""
        # Create instance to get packet IDs
        temp_instance = handler_class(None, {})
        for packet_id in temp_instance.get_packet_ids():
            self.handler_classes[packet_id] = handler_class
            
    def register_handler(self, handler: PacketHandler):
        """Register a handler instance"""
        for packet_id in handler.get_packet_ids():
            self.handlers[packet_id] = handler
            
    def get_handler(self, packet_id: int) -> Optional[PacketHandler]:
        """Get handler for packet ID"""
        return self.handlers.get(packet_id)
        
    def handle_packet(self, packet_id: int, data: bytes) -> bool:
        """Handle a packet if handler exists"""
        handler = self.get_handler(packet_id)
        if handler:
            handler.handle_packet(packet_id, data)
            return True
        return False
        
    def register_custom_handler(self, packet_id: int, handler_func: Callable[[bytes], Any]):
        """Register a simple function as handler"""
        class CustomHandler(PacketHandler):
            def get_packet_ids(self):
                return [packet_id]
            def handle_packet(self, pid, data):
                handler_func(data)
        
        handler = CustomHandler(None, {})
        self.register_handler(handler)