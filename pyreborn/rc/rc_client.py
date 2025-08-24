#!/usr/bin/env python3
"""
RC Client - Complete Remote Control client implementation

Provides a ready-to-use RC client that can be integrated with existing 
pyReborn clients or used as a standalone administrative tool.
"""

import logging
from typing import Optional, Dict, Any, List
from .rc_manager import RCManager, RCPermission
from .rc_commands import RCCommands

logger = logging.getLogger(__name__)


class RCClient:
    """Complete Remote Control client for server administration"""
    
    def __init__(self, pyreborn_client):
        """
        Initialize RC Client with existing pyReborn client
        
        Args:
            pyreborn_client: ModularRebornClient or RebornClient instance
        """
        self.client = pyreborn_client
        self.rc_manager = RCManager(pyreborn_client)
        self.rc_commands = RCCommands(self.rc_manager)
        
        # Session state
        self.connected = False
        self.authenticated = False
        
        logger.info("RC Client initialized")
    
    def connect_and_authenticate(self, username: str, password: str) -> bool:
        """
        Connect to server and authenticate RC session
        
        Args:
            username: RC username
            password: RC password
            
        Returns:
            bool: True if successfully connected and authenticated
        """
        logger.info(f"RC Client connecting as {username}")
        
        # Ensure underlying client is connected
        if not hasattr(self.client, 'connected') or not self.client.connected:
            logger.error("Underlying pyReborn client not connected")
            return False
        
        # Authenticate RC session
        if self.rc_manager.authenticate(username, password):
            self.connected = True
            self.authenticated = True
            logger.info(f"RC Client authenticated successfully as {username}")
            return True
        else:
            logger.error("RC authentication failed")
            return False
    
    def disconnect(self):
        """Disconnect RC session"""
        if self.authenticated:
            self.rc_manager.logout()
            self.connected = False
            self.authenticated = False
            logger.info("RC Client disconnected")
    
    # Administrative Operations
    
    def send_admin_message(self, message: str) -> bool:
        """Send admin message to all players"""
        return self.rc_commands.send_message(message)
    
    def send_private_admin_message(self, player_name: str, message: str) -> bool:
        """Send private admin message to specific player"""
        return self.rc_commands.send_private_message(player_name, message)
    
    def disconnect_player(self, player_name: str, reason: str = "") -> bool:
        """Disconnect player from server"""
        return self.rc_commands.disconnect_player(player_name, reason)
    
    def warp_player(self, player_name: str, level: str, x: int = 0, y: int = 0) -> bool:
        """Warp player to location"""
        return self.rc_commands.warp_player(player_name, level, x, y)
    
    def ban_player(self, player_name: str, reason: str = "", duration: int = 0) -> bool:
        """Ban player from server"""
        return self.rc_commands.ban_player(player_name, reason, duration)
    
    # Account Management
    
    def create_account(self, username: str, password: str, email: str = "") -> bool:
        """Create new server account"""
        return self.rc_commands.create_account(username, password, email)
    
    def delete_account(self, username: str) -> bool:
        """Delete server account"""
        return self.rc_commands.delete_account(username)
    
    def list_accounts(self, callback: Optional[callable] = None) -> bool:
        """Get list of server accounts"""
        return self.rc_commands.list_accounts(callback)
    
    # Server Configuration
    
    def get_server_flags(self, callback: Optional[callable] = None) -> bool:
        """Get server flags"""
        return self.rc_commands.get_server_flags(callback)
    
    def set_server_flags(self, flags: str) -> bool:
        """Set server flags"""
        return self.rc_commands.set_server_flags(flags)
    
    def get_server_options(self, callback: Optional[callable] = None) -> bool:
        """Get server configuration options"""
        return self.rc_commands.get_server_options(callback)
    
    def update_server_levels(self) -> bool:
        """Update server levels"""
        return self.rc_commands.update_levels()
    
    # File Management
    
    def start_file_browser(self, callback: Optional[callable] = None) -> bool:
        """Start file browser session"""
        return self.rc_commands.start_file_browser(callback)
    
    def end_file_browser(self) -> bool:
        """End file browser session"""
        return self.rc_commands.end_file_browser()
    
    def browse_directory(self, directory: str, callback: Optional[callable] = None) -> bool:
        """Browse server directory"""
        return self.rc_commands.change_directory(directory, callback)
    
    def list_directory(self, directory: str = "", callback: Optional[callable] = None) -> bool:
        """List directory contents"""
        return self.rc_commands.list_directory(directory, callback)
    
    def download_file(self, file_path: str, callback: Optional[callable] = None) -> bool:
        """Download file from server"""
        return self.rc_commands.download_file(file_path, callback)
    
    def upload_file(self, local_path: str, remote_path: str = "", callback: Optional[callable] = None) -> bool:
        """Upload file to server"""
        return self.rc_commands.upload_file(local_path, remote_path, callback)
    
    def delete_file(self, file_path: str, callback: Optional[callable] = None) -> bool:
        """Delete file or directory"""
        return self.rc_commands.delete_file(file_path, callback)
    
    def rename_file(self, old_path: str, new_path: str, callback: Optional[callable] = None) -> bool:
        """Rename file or directory"""
        return self.rc_commands.rename_file(old_path, new_path, callback)
    
    def move_file(self, source_path: str, dest_path: str, callback: Optional[callable] = None) -> bool:
        """Move file or directory"""
        return self.rc_commands.move_file(source_path, dest_path, callback)
    
    # Utility Methods
    
    def get_status(self) -> Dict[str, Any]:
        """Get RC client status information"""
        session_info = self.rc_manager.get_session_info()
        available_commands = self.rc_commands.get_available_commands()
        
        return {
            'connected': self.connected,
            'authenticated': self.authenticated,
            'session': session_info,
            'available_commands': len(available_commands),
            'commands': available_commands[:10],  # First 10 commands
            'total_commands': len(self.rc_commands.command_permissions)
        }
    
    def list_available_commands(self) -> List[Dict[str, Any]]:
        """Get detailed list of available commands"""
        commands = []
        for command in self.rc_commands.get_available_commands():
            info = self.rc_commands.get_command_info(command)
            commands.append(info)
        return commands
    
    def execute_command(self, command: str, *args, **kwargs) -> bool:
        """
        Execute RC command by name
        
        Args:
            command: Command name (e.g., 'send_message', 'disconnect_player')
            *args: Command arguments
            **kwargs: Command keyword arguments
            
        Returns:
            bool: True if command executed successfully
        """
        if not self.authenticated:
            logger.error("RC Client not authenticated")
            return False
        
        if not hasattr(self.rc_commands, command):
            logger.error(f"Unknown RC command: {command}")
            return False
        
        try:
            method = getattr(self.rc_commands, command)
            result = method(*args, **kwargs)
            logger.info(f"RC Command '{command}' executed: {result}")
            return result
        except Exception as e:
            logger.error(f"RC Command '{command}' failed: {e}")
            return False
    
    # Context manager support
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


# Example usage and testing
if __name__ == "__main__":
    # This would typically be used with a real pyReborn client
    class MockClient:
        def __init__(self):
            self.connected = True
        
        def send_raw_packet(self, data):
            print(f"Would send packet: {data}")
    
    # Example usage
    mock_client = MockClient()
    rc_client = RCClient(mock_client)
    
    if rc_client.connect_and_authenticate("admin", "password"):
        print("RC Client connected!")
        
        # Show status
        status = rc_client.get_status()
        print(f"Status: {status}")
        
        # Show available commands  
        commands = rc_client.list_available_commands()
        print(f"Available commands: {len(commands)}")
        for cmd in commands[:5]:  # Show first 5
            print(f"  - {cmd['command']}: {cmd['description']}")
        
        rc_client.disconnect()
    else:
        print("RC Client connection failed")