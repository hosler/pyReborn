#!/usr/bin/env python3
"""
RC File Manager - File system management for Remote Control operations

Provides comprehensive file management capabilities for RC sessions including:
- Directory browsing and navigation
- File upload and download operations  
- File operations (move, delete, rename)
- Directory operations (create, delete)
- File permission management

Based on RC_FILEBROWSER_* packets (89-98) from Reborn protocol analysis.
"""

import logging
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from pathlib import Path
from .rc_manager import RCManager, RCPermission

logger = logging.getLogger(__name__)


@dataclass
class FileItem:
    """Represents a file or directory in the server filesystem"""
    name: str
    is_directory: bool
    size: int = 0
    permissions: str = ""
    modified_time: str = ""
    full_path: str = ""


@dataclass
class DirectoryListing:
    """Represents a directory listing response"""
    current_path: str
    items: List[FileItem]
    total_items: int
    can_navigate_up: bool = True


class RCFileManager:
    """Comprehensive file management system for RC operations"""
    
    def __init__(self, rc_manager: RCManager):
        """Initialize file manager with RC manager"""
        self.rc_manager = rc_manager
        self.current_directory = "/"
        self.active_session = False
        self.file_callbacks: Dict[int, Callable] = {}
        
        # File browser packet mappings
        self.fb_packets = {
            # Server responses
            65: "RC_FILEBROWSER_DIRLIST",    # Directory listing
            66: "RC_FILEBROWSER_DIR",        # Directory change response  
            67: "RC_FILEBROWSER_MESSAGE",    # Status messages
        }
        
        # Client commands  
        self.fb_commands = {
            89: "RC_FILEBROWSER_START",      # Start file browser session
            90: "RC_FILEBROWSER_CD",         # Change directory
            91: "RC_FILEBROWSER_END",        # End file browser session
            92: "RC_FILEBROWSER_DOWN",       # Download file
            93: "RC_FILEBROWSER_UP",         # Upload file
            96: "RC_FILEBROWSER_MOVE",       # Move file/directory
            97: "RC_FILEBROWSER_DELETE",     # Delete file/directory
            98: "RC_FILEBROWSER_RENAME",     # Rename file/directory
        }
        
        # Register response handlers
        self._setup_response_handlers()
        logger.info("RC File Manager initialized")
    
    def _setup_response_handlers(self):
        """Register packet handlers for file browser responses"""
        for packet_id in self.fb_packets.keys():
            self.rc_manager.response_callbacks[packet_id] = self._handle_file_response
    
    def _handle_file_response(self, packet_id: int, data: bytes):
        """Handle file browser response packets"""
        packet_name = self.fb_packets.get(packet_id, f"UNKNOWN_FB_{packet_id}")
        logger.debug(f"File browser response: {packet_name} (ID: {packet_id})")
        
        # Call specific callback if registered
        if packet_id in self.file_callbacks:
            try:
                self.file_callbacks[packet_id](data)
            except Exception as e:
                logger.error(f"Error in file callback for {packet_name}: {e}")
    
    # Session Management
    
    def start_session(self, callback: Optional[Callable] = None) -> bool:
        """
        Start file browser session
        
        Args:
            callback: Optional callback for session start response
            
        Returns:
            bool: True if session start command sent successfully
        """
        if not self.rc_manager.has_permission(RCPermission.FILE_ADMIN):
            logger.error("Insufficient permissions for file browser")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[65] = callback
            
        # Send file browser start command
        try:
            packet_data = self.rc_manager._build_rc_packet(89, "")
            self.rc_manager.client.send_raw_packet(packet_data)
            self.active_session = True
            logger.info("File browser session started")
            return True
        except Exception as e:
            logger.error(f"Failed to start file browser session: {e}")
            return False
    
    def end_session(self) -> bool:
        """End file browser session"""
        if not self.active_session:
            return True
            
        try:
            packet_data = self.rc_manager._build_rc_packet(91, "")
            self.rc_manager.client.send_raw_packet(packet_data)
            self.active_session = False
            self.file_callbacks.clear()
            logger.info("File browser session ended")
            return True
        except Exception as e:
            logger.error(f"Failed to end file browser session: {e}")
            return False
    
    # Directory Navigation
    
    def change_directory(self, directory: str, callback: Optional[Callable] = None) -> bool:
        """
        Change to specified directory
        
        Args:
            directory: Target directory path
            callback: Optional callback for directory change response
            
        Returns:
            bool: True if change directory command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[66] = callback
            
        try:
            packet_data = self.rc_manager._build_rc_packet(90, directory)
            self.rc_manager.client.send_raw_packet(packet_data)
            self.current_directory = directory
            logger.info(f"Changed directory to: {directory}")
            return True
        except Exception as e:
            logger.error(f"Failed to change directory to {directory}: {e}")
            return False
    
    def list_directory(self, directory: str = "", callback: Optional[Callable] = None) -> bool:
        """
        List contents of directory
        
        Args:
            directory: Directory to list (empty for current)
            callback: Optional callback for directory listing response
            
        Returns:
            bool: True if directory list command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
        
        # Register callback  
        if callback:
            self.file_callbacks[65] = callback
        
        # Use current directory if none specified
        target_dir = directory or self.current_directory
        
        try:
            # Change directory triggers listing
            return self.change_directory(target_dir, callback)
        except Exception as e:
            logger.error(f"Failed to list directory {target_dir}: {e}")
            return False
    
    def navigate_up(self, callback: Optional[Callable] = None) -> bool:
        """Navigate to parent directory"""
        parent_dir = str(Path(self.current_directory).parent)
        return self.change_directory(parent_dir, callback)
    
    # File Operations
    
    def download_file(self, file_path: str, callback: Optional[Callable] = None) -> bool:
        """
        Download file from server
        
        Args:
            file_path: Path to file to download
            callback: Optional callback for download response
            
        Returns:
            bool: True if download command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[67] = callback
            
        try:
            packet_data = self.rc_manager._build_rc_packet(92, file_path)
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Requested download of: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download file {file_path}: {e}")
            return False
    
    def upload_file(self, local_path: str, remote_path: str = "", callback: Optional[Callable] = None) -> bool:
        """
        Upload file to server
        
        Args:
            local_path: Local file path
            remote_path: Remote destination path (empty for current directory)
            callback: Optional callback for upload response
            
        Returns:
            bool: True if upload command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[67] = callback
        
        # Construct upload path
        if not remote_path:
            remote_path = f"{self.current_directory}/{Path(local_path).name}"
            
        upload_data = f"{local_path}|{remote_path}"
        
        try:
            packet_data = self.rc_manager._build_rc_packet(93, upload_data)
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Requested upload: {local_path} -> {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload file {local_path}: {e}")
            return False
    
    def delete_file(self, file_path: str, callback: Optional[Callable] = None) -> bool:
        """
        Delete file or directory
        
        Args:
            file_path: Path to file/directory to delete
            callback: Optional callback for delete response
            
        Returns:
            bool: True if delete command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[67] = callback
            
        try:
            packet_data = self.rc_manager._build_rc_packet(97, file_path)
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Requested deletion of: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False
    
    def rename_file(self, old_path: str, new_path: str, callback: Optional[Callable] = None) -> bool:
        """
        Rename file or directory
        
        Args:
            old_path: Current file path
            new_path: New file path
            callback: Optional callback for rename response
            
        Returns:
            bool: True if rename command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[67] = callback
        
        rename_data = f"{old_path}|{new_path}"
        
        try:
            packet_data = self.rc_manager._build_rc_packet(98, rename_data)
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Requested rename: {old_path} -> {new_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to rename file {old_path}: {e}")
            return False
    
    def move_file(self, source_path: str, dest_path: str, callback: Optional[Callable] = None) -> bool:
        """
        Move file or directory
        
        Args:
            source_path: Source file path
            dest_path: Destination file path
            callback: Optional callback for move response
            
        Returns:
            bool: True if move command sent successfully
        """
        if not self.active_session:
            logger.error("File browser session not active")
            return False
            
        # Register callback
        if callback:
            self.file_callbacks[67] = callback
        
        move_data = f"{source_path}|{dest_path}"
        
        try:
            packet_data = self.rc_manager._build_rc_packet(96, move_data)
            self.rc_manager.client.send_raw_packet(packet_data)
            logger.info(f"Requested move: {source_path} -> {dest_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to move file {source_path}: {e}")
            return False
    
    # Utility Methods
    
    def get_status(self) -> Dict[str, Any]:
        """Get file manager status"""
        return {
            'active_session': self.active_session,
            'current_directory': self.current_directory,
            'registered_callbacks': len(self.file_callbacks),
            'available_commands': list(self.fb_commands.values()),
            'supported_operations': [
                'start_session', 'end_session', 'change_directory',
                'list_directory', 'download_file', 'upload_file',
                'delete_file', 'rename_file', 'move_file'
            ]
        }
    
    def parse_directory_listing(self, data: bytes) -> DirectoryListing:
        """
        Parse directory listing response (placeholder implementation)
        
        Args:
            data: Raw directory listing data from server
            
        Returns:
            DirectoryListing: Parsed directory information
        """
        # TODO: Implement actual parsing based on server response format
        # This is a placeholder implementation
        try:
            # Basic parsing - actual format depends on server implementation
            content = data.decode('latin1', errors='ignore')
            items = []
            
            # Parse items from server response
            for line in content.split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        name = parts[0]
                        is_dir = parts[1] == 'dir'
                        size = int(parts[2]) if len(parts) > 2 else 0
                        
                        items.append(FileItem(
                            name=name,
                            is_directory=is_dir,
                            size=size,
                            full_path=f"{self.current_directory}/{name}"
                        ))
            
            return DirectoryListing(
                current_path=self.current_directory,
                items=items,
                total_items=len(items)
            )
            
        except Exception as e:
            logger.error(f"Failed to parse directory listing: {e}")
            return DirectoryListing(
                current_path=self.current_directory,
                items=[],
                total_items=0
            )
    
    # Context manager support
    def __enter__(self):
        self.start_session()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()


# Example usage and integration
if __name__ == "__main__":
    # This would typically be used with a real RC manager
    class MockRCManager:
        def __init__(self):
            self.response_callbacks = {}
        
        def has_permission(self, permission):
            return True
            
        def _build_rc_packet(self, packet_id, data):
            return bytes([packet_id]) + data.encode('latin1', errors='ignore')
        
        @property
        def client(self):
            class MockClient:
                def send_raw_packet(self, data):
                    print(f"Would send file browser packet: {data}")
            return MockClient()
    
    # Example usage
    mock_rc_manager = MockRCManager()
    file_manager = RCFileManager(mock_rc_manager)
    
    # Context manager usage
    with file_manager:
        print("File browser session active")
        
        # Show status
        status = file_manager.get_status()
        print(f"Status: {status}")
        
        # Basic operations
        file_manager.list_directory("/home/reborn/worlds")
        file_manager.download_file("/home/reborn/worlds/test.nw")
        file_manager.upload_file("local_file.txt", "/home/reborn/worlds/")
        
    print("File browser session ended")