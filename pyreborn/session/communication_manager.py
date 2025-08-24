#!/usr/bin/env python3
"""
Communication Manager - Handles chat, private messages, and player communication

This manager handles all communication-related packets including chat messages,
private messages, server announcements, and player-to-player communication.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from ..protocol.interfaces import IManager
from ..session.events import EventType

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Represents a message (chat or PM)"""
    timestamp: datetime
    sender: str
    content: str
    message_type: str  # 'chat', 'pm', 'server'
    is_incoming: bool = True
    recipient: Optional[str] = None  # For PMs


class CommunicationManager(IManager):
    """Manager for handling player communication"""
    
    def __init__(self):
        self.chat_history: List[Message] = []
        self.pm_history: List[Message] = []
        self.server_messages: List[Message] = []
        self.max_history_size = 100
        self.event_manager = None
        self.config = None
        self.logger = logger
        
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager"""
        self.config = config
        self.event_manager = event_manager
        logger.info("Communication manager initialized")
        
    def cleanup(self) -> None:
        """Clean up manager resources"""
        self.chat_history.clear()
        self.pm_history.clear()
        self.server_messages.clear()
        logger.info("Communication manager cleaned up")
        
    @property
    def name(self) -> str:
        """Get manager name"""
        return "communication_manager"
        
    def handle_packet(self, packet_id: int, packet_data: Dict[str, Any]) -> None:
        """Handle incoming communication packets"""
        packet_name = packet_data.get('packet_name', 'UNKNOWN')
        fields = packet_data.get('fields', {})
        
        logger.debug(f"Communication manager handling packet: {packet_name} ({packet_id})")
        
        # Route based on packet ID
        if packet_id == 10:  # PLO_PRIVATEMESSAGE
            self._handle_private_message(fields)
        elif packet_id == 20:  # PLO_TOALL
            self._handle_chat_message(fields)
        elif packet_id == 82:  # PLO_SERVERTEXT
            self._handle_server_text(fields)
        else:
            logger.warning(f"Communication manager received unhandled packet: {packet_name} ({packet_id})")
    
    def _handle_private_message(self, fields: Dict[str, Any]) -> None:
        """Handle incoming private message"""
        sender = fields.get('player_account', 'Unknown')
        message_text = fields.get('message', '')
        
        if not message_text:
            return
            
        message = Message(
            timestamp=datetime.now(),
            sender=sender,
            content=message_text,
            message_type='pm',
            is_incoming=True
        )
        
        self._add_to_history(self.pm_history, message)
        logger.info(f"PM from {sender}: {message_text}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.PRIVATE_MESSAGE_RECEIVED, {
                'sender': sender,
                'message': message_text,
                'timestamp': message.timestamp,
                'fields': fields
            })
    
    def _handle_chat_message(self, fields: Dict[str, Any]) -> None:
        """Handle incoming chat message"""
        nickname = fields.get('nickname', 'Unknown')
        message_text = fields.get('message', '')
        
        if not message_text:
            return
            
        message = Message(
            timestamp=datetime.now(),
            sender=nickname,
            content=message_text,
            message_type='chat',
            is_incoming=True
        )
        
        self._add_to_history(self.chat_history, message)
        logger.info(f"Chat from {nickname}: {message_text}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.CHAT_MESSAGE_RECEIVED, {
                'sender': nickname,
                'message': message_text,
                'timestamp': message.timestamp,
                'fields': fields
            })
    
    def _handle_server_text(self, fields: Dict[str, Any]) -> None:
        """Handle server text message"""
        message_text = fields.get('message', '')
        
        if not message_text:
            return
            
        message = Message(
            timestamp=datetime.now(),
            sender='Server',
            content=message_text,
            message_type='server',
            is_incoming=True
        )
        
        self._add_to_history(self.server_messages, message)
        logger.info(f"Server message: {message_text}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.SERVER_MESSAGE, {
                'message': message_text,
                'timestamp': message.timestamp,
                'fields': fields
            })
    
    def _add_to_history(self, history_list: List[Message], message: Message) -> None:
        """Add message to history with size limit"""
        history_list.append(message)
        
        # Trim history if needed
        if len(history_list) > self.max_history_size:
            history_list.pop(0)
    
    # Public API methods
    
    def record_sent_message(self, message_text: str, message_type: str = 'chat', recipient: Optional[str] = None) -> None:
        """Record a message sent by the local player"""
        message = Message(
            timestamp=datetime.now(),
            sender='You',
            content=message_text,
            message_type=message_type,
            is_incoming=False,
            recipient=recipient
        )
        
        if message_type == 'pm' and recipient:
            self._add_to_history(self.pm_history, message)
        elif message_type == 'chat':
            self._add_to_history(self.chat_history, message)
    
    def get_chat_history(self, limit: Optional[int] = None) -> List[Message]:
        """Get chat message history"""
        if limit:
            return self.chat_history[-limit:]
        return self.chat_history.copy()
    
    def get_pm_history(self, limit: Optional[int] = None) -> List[Message]:
        """Get private message history"""
        if limit:
            return self.pm_history[-limit:]
        return self.pm_history.copy()
    
    def get_server_messages(self, limit: Optional[int] = None) -> List[Message]:
        """Get server message history"""
        if limit:
            return self.server_messages[-limit:]
        return self.server_messages.copy()
    
    def get_all_messages(self, limit: Optional[int] = None) -> List[Tuple[datetime, str, str, str]]:
        """Get all messages sorted by timestamp
        
        Returns:
            List of tuples: (timestamp, type, sender, message)
        """
        all_messages = []
        
        # Add chat messages
        for msg in self.chat_history:
            all_messages.append((msg.timestamp, 'chat', msg.sender, msg.content))
        
        # Add PMs
        for msg in self.pm_history:
            if msg.is_incoming:
                all_messages.append((msg.timestamp, 'pm', f"{msg.sender} (PM)", msg.content))
            else:
                all_messages.append((msg.timestamp, 'pm', f"You -> {msg.recipient}", msg.content))
        
        # Add server messages
        for msg in self.server_messages:
            all_messages.append((msg.timestamp, 'server', 'Server', msg.content))
        
        # Sort by timestamp
        all_messages.sort(key=lambda x: x[0])
        
        if limit:
            return all_messages[-limit:]
        return all_messages
    
    def clear_history(self, message_type: Optional[str] = None) -> None:
        """Clear message history
        
        Args:
            message_type: Type to clear ('chat', 'pm', 'server'), or None for all
        """
        if message_type == 'chat' or message_type is None:
            self.chat_history.clear()
        if message_type == 'pm' or message_type is None:
            self.pm_history.clear()
        if message_type == 'server' or message_type is None:
            self.server_messages.clear()
    
    def search_messages(self, search_term: str, message_type: Optional[str] = None) -> List[Message]:
        """Search messages for a term
        
        Args:
            search_term: Text to search for (case insensitive)
            message_type: Type to search ('chat', 'pm', 'server'), or None for all
            
        Returns:
            List of matching messages
        """
        search_lower = search_term.lower()
        results = []
        
        # Search chat
        if message_type == 'chat' or message_type is None:
            results.extend([msg for msg in self.chat_history 
                          if search_lower in msg.content.lower() or search_lower in msg.sender.lower()])
        
        # Search PMs
        if message_type == 'pm' or message_type is None:
            results.extend([msg for msg in self.pm_history 
                          if search_lower in msg.content.lower() or search_lower in msg.sender.lower()])
        
        # Search server messages
        if message_type == 'server' or message_type is None:
            results.extend([msg for msg in self.server_messages 
                          if search_lower in msg.content.lower()])
        
        return results