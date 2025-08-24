#!/usr/bin/env python3
"""
Communication Manager
Handles chat messages, private messages, and server text
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CommunicationManager:
    """Manages communication/chat functionality"""
    
    def __init__(self):
        """Initialize communication manager"""
        self.messages = []
        self.server_text = []
        logger.debug("CommunicationManager initialized")
    
    def initialize(self, config, events):
        """Initialize with config and events (for IManager interface compatibility)"""
        self.config = config
        self.events = events
        logger.debug("CommunicationManager initialized with config and events")
    
    def handle_packet(self, packet_id: int, parsed_data: Dict[str, Any]) -> bool:
        """Handle communication-related packets
        
        Args:
            packet_id: The packet ID
            parsed_data: Parsed packet data
            
        Returns:
            True if packet was handled, False otherwise
        """
        if packet_id == 10:  # PLO_PRIVATEMESSAGE
            return self._handle_private_message(parsed_data)
        elif packet_id == 20:  # PLO_TOALL
            return self._handle_toall_message(parsed_data)
        elif packet_id == 82:  # PLO_SERVERTEXT
            return self._handle_server_text(parsed_data)
        
        logger.warning(f"Unhandled communication packet: {packet_id}")
        return False
    
    def _handle_private_message(self, data: Dict[str, Any]) -> bool:
        """Handle private message packet"""
        logger.debug(f"Received private message: {data}")
        self.messages.append({
            'type': 'private',
            'data': data
        })
        return True
    
    def _handle_toall_message(self, data: Dict[str, Any]) -> bool:
        """Handle broadcast message packet"""
        logger.debug(f"Received broadcast message: {data}")
        self.messages.append({
            'type': 'broadcast',
            'data': data
        })
        return True
    
    def _handle_server_text(self, data: Dict[str, Any]) -> bool:
        """Handle server text packet"""
        logger.debug(f"Received server text: {data}")
        self.server_text.append(data)
        return True
    
    def get_messages(self) -> list:
        """Get all received messages"""
        return self.messages
    
    def get_server_text(self) -> list:
        """Get all server text messages"""
        return self.server_text
    
    def clear_messages(self):
        """Clear all stored messages"""
        self.messages = []
        self.server_text = []