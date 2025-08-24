#!/usr/bin/env python3
"""
RC Commands - High-level command interface for Remote Control operations

Provides convenient methods for common RC operations with proper error handling
and logging. Integrates with RCManager for session management.
"""

import logging
from typing import Optional, Dict, Any, List
from .rc_manager import RCManager, RCPermission
from .rc_file_manager import RCFileManager

logger = logging.getLogger(__name__)


class RCCommands:
    """High-level command interface for RC operations"""
    
    def __init__(self, rc_manager: RCManager):
        """Initialize RC Commands with manager"""
        self.rc_manager = rc_manager
        self.file_manager = RCFileManager(rc_manager)
        
        # Command categories and their required permissions
        self.command_permissions = {
            # Communication commands
            'send_message': RCPermission.PLAYER_ADMIN,
            'send_private_message': RCPermission.PLAYER_ADMIN,
            'rc_chat': RCPermission.BASIC,
            
            # Player management
            'disconnect_player': RCPermission.PLAYER_ADMIN,
            'warp_player': RCPermission.PLAYER_ADMIN,
            'get_player_rights': RCPermission.PLAYER_ADMIN,
            'ban_player': RCPermission.PLAYER_ADMIN,
            
            # Account management  
            'create_account': RCPermission.SERVER_ADMIN,
            'delete_account': RCPermission.SERVER_ADMIN,
            'list_accounts': RCPermission.SERVER_ADMIN,
            
            # Server configuration
            'get_server_flags': RCPermission.SERVER_ADMIN,
            'set_server_flags': RCPermission.SERVER_ADMIN,
            'get_server_options': RCPermission.SERVER_ADMIN,
            'update_levels': RCPermission.SERVER_ADMIN,
            
            # File management
            'start_file_browser': RCPermission.FILE_ADMIN,
            'end_file_browser': RCPermission.FILE_ADMIN,
            'change_directory': RCPermission.FILE_ADMIN,
            'list_directory': RCPermission.FILE_ADMIN,
            'download_file': RCPermission.FILE_ADMIN,
            'upload_file': RCPermission.FILE_ADMIN,
            'delete_file': RCPermission.FILE_ADMIN,
            'rename_file': RCPermission.FILE_ADMIN,
            'move_file': RCPermission.FILE_ADMIN,
        }
    
    def _check_permission(self, command: str) -> bool:
        """Check if user has permission for command"""
        required = self.command_permissions.get(command, RCPermission.SUPER_ADMIN)
        has_permission = self.rc_manager.has_permission(required)
        
        if not has_permission:
            logger.warning(f"Permission denied for RC command '{command}' - requires {required.name}")
            
        return has_permission
    
    # Communication Commands
    
    def send_message(self, message: str) -> bool:
        """Send admin message to all players"""
        if not self._check_permission('send_message'):
            return False
        return self.rc_manager.send_admin_message(message)
    
    def send_private_message(self, player_name: str, message: str) -> bool:
        """Send private admin message to specific player"""
        if not self._check_permission('send_private_message'):
            return False
            
        # RC Private Admin Message packet (Client to Server packet 64)
        full_message = f"{player_name}: {message}"
        packet_data = self.rc_manager._build_rc_packet(64, full_message)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Sent private admin message to {player_name}: {message[:30]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send private message: {e}")
            return False
    
    def rc_chat(self, message: str) -> bool:
        """Send message in RC chat channel"""
        if not self._check_permission('rc_chat'):
            return False
            
        # RC Chat packet (Client to Server packet 79)
        packet_data = self.rc_manager._build_rc_packet(79, message)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Sent RC chat: {message[:30]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send RC chat: {e}")
            return False
    
    # Player Management Commands
    
    def disconnect_player(self, player_name: str, reason: str = "") -> bool:
        """Disconnect player with optional reason"""
        if not self._check_permission('disconnect_player'):
            return False
        
        # Apply reason if provided (packet 67)
        if reason:
            reason_packet = self.rc_manager._build_rc_packet(67, reason)
            self.rc_manager.client.send_raw_packet(reason_packet)
        
        return self.rc_manager.disconnect_player(player_name)
    
    def warp_player(self, player_name: str, level: str, x: int = 0, y: int = 0) -> bool:
        """Warp player to specified location"""
        if not self._check_permission('warp_player'):
            return False
            
        # RC Warp Player packet (Client to Server packet 82)
        warp_data = f"{player_name} {level} {x} {y}"
        packet_data = self.rc_manager._build_rc_packet(82, warp_data)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Warped player {player_name} to {level} ({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"Failed to warp player: {e}")
            return False
    
    def get_player_rights(self, player_name: str, callback: Optional[callable] = None) -> bool:
        """Get player rights information"""
        if not self._check_permission('get_player_rights'):
            return False
        return self.rc_manager.get_player_rights(player_name, callback)
    
    def ban_player(self, player_name: str, reason: str = "", duration: int = 0) -> bool:
        """Ban player with reason and duration"""
        if not self._check_permission('ban_player'):
            return False
            
        # RC Player Ban Set packet (Client to Server packet 88)
        ban_data = f"{player_name} {duration} {reason}"
        packet_data = self.rc_manager._build_rc_packet(88, ban_data)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Banned player {player_name}: {reason}")
            return True
        except Exception as e:
            logger.error(f"Failed to ban player: {e}")
            return False
    
    # Account Management Commands
    
    def create_account(self, username: str, password: str, email: str = "") -> bool:
        """Create new server account"""
        if not self._check_permission('create_account'):
            return False
            
        # RC Account Add packet (Client to Server packet 70)
        account_data = f"{username} {password} {email}"
        packet_data = self.rc_manager._build_rc_packet(70, account_data)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Created account: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to create account: {e}")
            return False
    
    def delete_account(self, username: str) -> bool:
        """Delete server account"""
        if not self._check_permission('delete_account'):
            return False
            
        # RC Account Delete packet (Client to Server packet 71)
        packet_data = self.rc_manager._build_rc_packet(71, username)
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Deleted account: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete account: {e}")
            return False
    
    def list_accounts(self, callback: Optional[callable] = None) -> bool:
        """Get list of server accounts"""
        if not self._check_permission('list_accounts'):
            return False
            
        # Register callback for response
        if callback:
            self.rc_manager.response_callbacks[70] = callback
            
        # RC Account List Get packet (Client to Server packet 72)
        packet_data = self.rc_manager._build_rc_packet(72, "")
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info("Requested account list")
            return True
        except Exception as e:
            logger.error(f"Failed to request account list: {e}")
            return False
    
    # Server Configuration Commands
    
    def get_server_flags(self, callback: Optional[callable] = None) -> bool:
        """Get server flags"""
        if not self._check_permission('get_server_flags'):
            return False
        return self.rc_manager.get_server_flags(callback)
    
    def set_server_flags(self, flags: str) -> bool:
        """Set server flags"""
        if not self._check_permission('set_server_flags'):
            return False
        return self.rc_manager.set_server_flags(flags)
    
    def get_server_options(self, callback: Optional[callable] = None) -> bool:
        """Get server configuration options"""
        if not self._check_permission('get_server_options'):
            return False
            
        # Register callback for response
        if callback:
            self.rc_manager.response_callbacks[76] = callback
            
        # RC Server Options Get packet (Client to Server packet 51)
        packet_data = self.rc_manager._build_rc_packet(51, "")
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info("Requested server options")
            return True
        except Exception as e:
            logger.error(f"Failed to request server options: {e}")
            return False
    
    def update_levels(self) -> bool:
        """Update server levels"""
        if not self._check_permission('update_levels'):
            return False
            
        # RC Update Levels packet (Client to Server packet 62)
        packet_data = self.rc_manager._build_rc_packet(62, "")
        
        try:
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info("Sent level update command")
            return True
        except Exception as e:
            logger.error(f"Failed to update levels: {e}")
            return False
    
    # File Management Commands (Comprehensive Implementation)
    
    def start_file_browser(self, callback: Optional[callable] = None) -> bool:
        """Start file browser session"""
        if not self._check_permission('list_directory'):
            return False
        return self.file_manager.start_session(callback)
    
    def end_file_browser(self) -> bool:
        """End file browser session"""
        if not self._check_permission('list_directory'):
            return False
        return self.file_manager.end_session()
    
    def change_directory(self, directory: str, callback: Optional[callable] = None) -> bool:
        """Change directory in file browser"""
        if not self._check_permission('list_directory'):
            return False
        return self.file_manager.change_directory(directory, callback)
    
    def list_directory(self, directory: str = "", callback: Optional[callable] = None) -> bool:
        """List directory contents"""
        if not self._check_permission('list_directory'):
            return False
        return self.file_manager.list_directory(directory, callback)
    
    def download_file(self, file_path: str, callback: Optional[callable] = None) -> bool:
        """Download file from server"""
        if not self._check_permission('download_file'):
            return False
        return self.file_manager.download_file(file_path, callback)
    
    def upload_file(self, local_path: str, remote_path: str = "", callback: Optional[callable] = None) -> bool:
        """Upload file to server"""
        if not self._check_permission('upload_file'):
            return False
        return self.file_manager.upload_file(local_path, remote_path, callback)
    
    def delete_file(self, file_path: str, callback: Optional[callable] = None) -> bool:
        """Delete file or directory"""
        if not self._check_permission('delete_file'):
            return False
        return self.file_manager.delete_file(file_path, callback)
    
    def rename_file(self, old_path: str, new_path: str, callback: Optional[callable] = None) -> bool:
        """Rename file or directory"""
        if not self._check_permission('move_file'):
            return False
        return self.file_manager.rename_file(old_path, new_path, callback)
    
    def move_file(self, source_path: str, dest_path: str, callback: Optional[callable] = None) -> bool:
        """Move file or directory"""
        if not self._check_permission('move_file'):
            return False
        return self.file_manager.move_file(source_path, dest_path, callback)
    
    def get_available_commands(self) -> List[str]:
        """Get list of available RC commands based on permissions"""
        available = []
        for command, required_permission in self.command_permissions.items():
            if self.rc_manager.has_permission(required_permission):
                available.append(command)
        return available
    
    def get_command_info(self, command: str) -> Dict[str, Any]:
        """Get information about a specific command"""
        if command not in self.command_permissions:
            return {'error': 'Command not found'}
            
        required_permission = self.command_permissions[command]
        has_access = self.rc_manager.has_permission(required_permission)
        
        return {
            'command': command,
            'required_permission': required_permission.name,
            'has_access': has_access,
            'description': getattr(getattr(self, command), '__doc__', 'No description available')
        }