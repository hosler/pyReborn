#!/usr/bin/env python3
"""
System Manager - Handles system-related packets and server management

This manager handles system packets like server messages, flags, time updates,
disconnections, signatures, and other server-level operations.
"""

import logging
from typing import Dict, Any, Optional, List
from ..protocol.interfaces import IManager
from ..session.events import EventType

logger = logging.getLogger(__name__)


class SystemManager(IManager):
    """Manager for handling system packets and server state"""
    
    def __init__(self):
        self.flags: Dict[str, str] = {}  # Server flags
        self.server_time = 0
        self.server_text_messages: List[str] = []
        self.staff_guilds: List[str] = []
        self.has_npc_server = False
        self.active_level = ""
        self.processes: List[Dict[str, Any]] = []
        self.last_disconnect_reason = ""
        self.event_manager = None
        self.config = None
        self.logger = logger
        
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager"""
        self.config = config
        self.event_manager = event_manager
        logger.info("System manager initialized")
        
    def cleanup(self) -> None:
        """Clean up manager resources"""
        self.flags.clear()
        self.server_text_messages.clear()
        self.staff_guilds.clear()
        self.processes.clear()
        logger.info("System manager cleaned up")
        
    @property
    def name(self) -> str:
        """Get manager name"""
        return "system_manager"
        
    def handle_packet(self, packet_id: int, packet_data: Dict[str, Any]) -> None:
        """Handle incoming system packets"""
        packet_name = packet_data.get('packet_name', 'UNKNOWN')
        fields = packet_data.get('fields', {})
        
        logger.debug(f"System manager handling packet: {packet_name} ({packet_id})")
        
        # Route based on packet ID
        if packet_id == 16:  # PLO_DISCONNECT
            self._handle_disconnect(fields)
        elif packet_id == 25:  # PLO_SIGNATURE
            self._handle_signature(fields)
        elif packet_id == 28:  # PLO_FLAGSET
            self._handle_flag_set(fields)
        elif packet_id == 39:  # PLO_LEVELMODTIME
            self._handle_level_modtime(fields)
        elif packet_id == 42:  # PLO_NEWWORLDTIME
            self._handle_world_time(fields)
        elif packet_id == 44:  # PLO_HASNPCSERVER
            self._handle_has_npc_server(fields)
        elif packet_id == 47:  # PLO_STAFFGUILDS
            self._handle_staff_guilds(fields)
        elif packet_id == 82:  # PLO_SERVERTEXT
            self._handle_server_text(fields)
        elif packet_id == 156:  # PLO_SETACTIVELEVEL
            self._handle_set_active_level(fields)
        elif packet_id == 182:  # PLO_LISTPROCESSES
            self._handle_list_processes(fields)
        else:
            logger.warning(f"System manager received unhandled packet: {packet_name} ({packet_id})")
    
    def _handle_disconnect(self, fields: Dict[str, Any]) -> None:
        """Handle disconnect message"""
        reason = fields.get('message', 'Unknown reason')
        self.last_disconnect_reason = reason
        logger.info(f"Server disconnect: {reason}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.DISCONNECTED, {
                'reason': reason,
                'fields': fields
            })
    
    def _handle_signature(self, fields: Dict[str, Any]) -> None:
        """Handle server signature - according to Preagonal this should be empty and do nothing"""
        signature = fields.get('signature', '')
        logger.debug(f"Server signature received: {signature[:50]}{'...' if len(signature) > 50 else ''}")
        
        # According to Preagonal, signature handler is empty - it does nothing
        # The signature packet should NOT contain player properties
        # Player properties come in their own separate packet (PLO_PLAYERPROPS)
        
        if self.event_manager:
            self.event_manager.emit(EventType.SERVER_SIGNATURE, {
                'signature': signature,
                'fields': fields
            })
    
    def _handle_flag_set(self, fields: Dict[str, Any]) -> None:
        """Handle flag set"""
        flag_name = fields.get('flag_name', '')
        flag_value = fields.get('flag_value', '')
        
        if flag_name:
            self.flags[flag_name] = flag_value
            logger.debug(f"Flag set: {flag_name} = {flag_value}")
            
            if self.event_manager:
                self.event_manager.emit(EventType.FLAG_SET, {
                    'flag_name': flag_name,
                    'flag_value': flag_value,
                    'fields': fields
                })
    
    def _handle_level_modtime(self, fields: Dict[str, Any]) -> None:
        """Handle level modification time"""
        level_name = fields.get('level_name', '')
        modtime = fields.get('modtime', 0)
        
        logger.debug(f"Level modtime: {level_name} = {modtime}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_MODTIME, {
                'level_name': level_name,
                'modtime': modtime,
                'fields': fields
            })
    
    def _handle_world_time(self, fields: Dict[str, Any]) -> None:
        """Handle world time update"""
        self.server_time = fields.get('world_time', 0)
        logger.debug(f"World time updated: {self.server_time}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.WORLD_TIME_UPDATE, {
                'world_time': self.server_time,
                'fields': fields
            })
    
    def _handle_has_npc_server(self, fields: Dict[str, Any]) -> None:
        """Handle NPC server availability"""
        self.has_npc_server = fields.get('has_npc_server', False)
        logger.info(f"NPC server available: {self.has_npc_server}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.NPC_SERVER_STATUS, {
                'has_npc_server': self.has_npc_server,
                'fields': fields
            })
    
    def _handle_staff_guilds(self, fields: Dict[str, Any]) -> None:
        """Handle staff guilds list"""
        self.staff_guilds = fields.get('guilds', [])
        logger.debug(f"Staff guilds updated: {self.staff_guilds}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.STAFF_GUILDS_UPDATE, {
                'guilds': self.staff_guilds,
                'fields': fields
            })
    
    def _handle_server_text(self, fields: Dict[str, Any]) -> None:
        """Handle server text message"""
        message = fields.get('message', '')
        if message:
            self.server_text_messages.append(message)
            logger.info(f"Server message: {message}")
            
            if self.event_manager:
                self.event_manager.emit(EventType.SERVER_MESSAGE, {
                    'message': message,
                    'fields': fields
                })
    
    def _handle_set_active_level(self, fields: Dict[str, Any]) -> None:
        """Handle set active level"""
        self.active_level = fields.get('level_name', '')
        logger.debug(f"Active level set: {self.active_level}")
        
        if self.event_manager:
            self.event_manager.emit(EventType.ACTIVE_LEVEL_SET, {
                'level_name': self.active_level,
                'fields': fields
            })
    
    def _handle_list_processes(self, fields: Dict[str, Any]) -> None:
        """Handle process list"""
        self.processes = fields.get('processes', [])
        logger.debug(f"Process list updated: {len(self.processes)} processes")
        
        if self.event_manager:
            self.event_manager.emit(EventType.PROCESS_LIST_UPDATE, {
                'processes': self.processes,
                'fields': fields
            })
    
    # Public API methods
    
    def get_flag(self, flag_name: str) -> Optional[str]:
        """Get a server flag value"""
        return self.flags.get(flag_name)
    
    def get_all_flags(self) -> Dict[str, str]:
        """Get all server flags"""
        return self.flags.copy()
    
    def get_server_time(self) -> int:
        """Get current server time"""
        return self.server_time
    
    def get_server_messages(self) -> List[str]:
        """Get all server text messages"""
        return self.server_text_messages.copy()
    
    def is_npc_server_available(self) -> bool:
        """Check if NPC server is available"""
        return self.has_npc_server
    
    def get_staff_guilds(self) -> List[str]:
        """Get list of staff guilds"""
        return self.staff_guilds.copy()
    
    def get_active_level(self) -> str:
        """Get currently active level"""
        return self.active_level
    
    def get_processes(self) -> List[Dict[str, Any]]:
        """Get server process list"""
        return self.processes.copy()
    
    def get_last_disconnect_reason(self) -> str:
        """Get reason for last disconnect"""
        return self.last_disconnect_reason
    
    # Removed all hardcoded packet separation and player property parsing methods
    # These were incorrect - packets are properly separated by the Preagonal approach in socket manager