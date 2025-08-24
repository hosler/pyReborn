#!/usr/bin/env python3
"""
File Manager - Handles file download operations

This manager integrates the LargeFileHandler and provides a clean interface
for handling all file-related packets including large file transfers.
"""

import logging
import time
from typing import Dict, Any, Optional
from ..protocol.large_file_handler import LargeFileHandler
from .events import EventType

logger = logging.getLogger(__name__)


class FileManager:
    """Manages file downloads and caching operations"""
    
    def __init__(self, client, event_manager=None, cache_manager=None):
        self.client = client
        self.event_manager = event_manager
        self.cache_manager = cache_manager
        
        # Initialize large file handler
        self.large_file_handler = LargeFileHandler(
            event_manager=event_manager,
            cache_manager=cache_manager
        )
        
        # Set client reference for the handler
        self.large_file_handler.client = client
        
        # File download statistics
        self.stats = {
            'downloads_started': 0,
            'downloads_completed': 0,
            'downloads_failed': 0,
            'bytes_downloaded': 0,
            'files_cached': 0
        }
        
        # Track recently requested files to fix filename detection
        self.recent_requests = {}  # timestamp -> filename
        self.request_timeout = 30  # seconds
        
        logger.info("File manager initialized")
    
    def register_file_request(self, filename: str):
        """Register that we just requested a specific file"""
        import time
        timestamp = time.time()
        self.recent_requests[timestamp] = filename
        
        # Clean up old requests
        current_time = time.time()
        expired_times = [t for t in self.recent_requests.keys() 
                        if current_time - t > self.request_timeout]
        for t in expired_times:
            del self.recent_requests[t]
        
        logger.debug(f"Registered file request: {filename}")
    
    def get_expected_filename_for_content(self, detected_filename: str, file_content: bytes) -> str:
        """Get the expected filename based on recent requests and content analysis"""
        import time
        current_time = time.time()
        
        # Check if any recent requests match better than the detected filename
        for timestamp, requested_filename in self.recent_requests.items():
            if current_time - timestamp <= self.request_timeout:
                # If the detected filename is found within the content of the requested file,
                # it's likely a false positive from content parsing
                if (requested_filename.endswith('.gmap') and 
                    detected_filename.endswith('.nw') and
                    b'GRMAP001' in file_content):
                    logger.info(f"🔧 Correcting filename: {detected_filename} -> {requested_filename} (GMAP file)")
                    return requested_filename
                    
                # For other file types, use exact match or extension match
                if (requested_filename == detected_filename or 
                    requested_filename.endswith(detected_filename.split('.')[-1])):
                    return requested_filename
        
        return detected_filename
    
    def handle_packet(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle file-related packets"""
        
        packet_name = parsed_packet.get('packet_name', f'PACKET_{packet_id}')
        raw_data = parsed_packet.get('raw_data', b'')
        announced_size = parsed_packet.get('announced_size', len(raw_data))
        
        logger.debug(f"FileManager handling {packet_name} ({packet_id})")
        
        try:
            # Route to appropriate handler based on packet type
            if packet_id == 68:  # PLO_LARGEFILESTART
                self.stats['downloads_started'] += 1
                return self.large_file_handler.handle_large_file_start(packet_id, raw_data, announced_size)
                
            elif packet_id == 84:  # PLO_LARGEFILESIZE
                return self.large_file_handler.handle_large_file_size(packet_id, raw_data, announced_size)
                
            elif packet_id == 100:  # PLO_RAWDATA
                result = self.large_file_handler.handle_raw_data(packet_id, raw_data, announced_size)
                if result:
                    # Track bytes downloaded
                    chunk_size = result.get('fields', {}).get('chunk_size', 0)
                    self.stats['bytes_downloaded'] += chunk_size
                return result
                
            elif packet_id == 69:  # PLO_LARGEFILEEND
                result = self.large_file_handler.handle_large_file_end(packet_id, raw_data, announced_size)
                if result:
                    self.stats['downloads_completed'] += 1
                    self.stats['files_cached'] += 1
                    
                    # Emit file download complete event
                    if self.event_manager:
                        filename = result.get('fields', {}).get('filename', 'unknown')
                        file_size = result.get('fields', {}).get('file_size', 0)
                        
                        self.event_manager.emit(EventType.FILE_DOWNLOADED, {
                            'filename': filename,
                            'size': file_size,
                            'packet_id': packet_id
                        })
                        
                return result
                
            elif packet_id == 45:  # PLO_FILEUPTODATE
                return self._handle_file_uptodate(packet_id, parsed_packet)
                
            elif packet_id == 30:  # PLO_FILESENDFAILED  
                self.stats['downloads_failed'] += 1
                return self._handle_file_send_failed(packet_id, parsed_packet)
                
            elif packet_id == 102:  # PLO_FILE - standard file transfer
                return self._handle_standard_file(packet_id, parsed_packet)
                
            else:
                logger.warning(f"Unknown file packet: {packet_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error handling file packet {packet_id}: {e}", exc_info=True)
            self.stats['downloads_failed'] += 1
            return None
    
    def _handle_file_uptodate(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Dict[str, Any]:
        """Handle PLO_FILEUPTODATE packet"""
        fields = parsed_packet.get('fields', {})
        filename = fields.get('file_name', 'unknown')
        modification_time = fields.get('modification_time', 0)
        
        logger.info(f"File up to date: {filename} (mod time: {modification_time})")
        
        # Emit event for file up to date
        if self.event_manager:
            self.event_manager.emit(EventType.FILE_UP_TO_DATE, {
                'filename': filename,
                'modification_time': modification_time,
                'packet_id': packet_id
            })
        
        return {
            'packet_id': packet_id,
            'packet_name': 'PLO_FILEUPTODATE',
            'fields': {
                'filename': filename,
                'modification_time': modification_time,
                'up_to_date': True
            }
        }
    
    def _handle_file_send_failed(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Dict[str, Any]:
        """Handle PLO_FILESEND_FAILED packet"""
        fields = parsed_packet.get('fields', {})
        filename = fields.get('filename', 'unknown')
        
        logger.warning(f"File send failed: {filename}")
        
        # Emit event for file send failure
        if self.event_manager:
            self.event_manager.emit(EventType.FILE_DOWNLOAD_FAILED, {
                'filename': filename,
                'packet_id': packet_id
            })
        
        return {
            'packet_id': packet_id,
            'packet_name': 'PLO_FILESEND_FAILED',
            'fields': {
                'filename': filename,
                'failed': True
            }
        }
    
    def _handle_standard_file(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Dict[str, Any]:
        """Handle PLO_FILE packet - standard file transfer"""
        
        logger.info(f"📄 Standard file transfer received: packet {packet_id}")
        
        # Use the sophisticated PLO_FILE parsing logic
        parsed_data = parsed_packet.get('parsed_data', {})
        
        if not parsed_data:
            logger.error("   ❌ No parsed data in PLO_FILE packet")
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_FILE',
                'fields': {'error': 'No parsed data'}
            }
        
        detected_filename = parsed_data.get('filename', 'unknown')
        file_content = parsed_data.get('content', b'')
        file_size = parsed_data.get('size', len(file_content))
        
        # Apply filename correction based on recent requests
        filename = self.get_expected_filename_for_content(detected_filename, file_content)
        
        logger.info(f"   📄 File: {filename} ({file_size} bytes)")
        
        # Large file detection and accumulation
        # Check if we have an active large file download or if this should be one
        is_large_file = False
        current_download = None
        
        # Check if we have an active large file download
        if hasattr(self.large_file_handler, '_active_downloads'):
            # Check by filename first (using the filename-to-ID mapping)
            if hasattr(self.large_file_handler, '_filename_to_id') and filename in self.large_file_handler._filename_to_id:
                download_id = self.large_file_handler._filename_to_id[filename]
                if download_id in self.large_file_handler._active_downloads:
                    current_download = self.large_file_handler._active_downloads[download_id]
                    if current_download.get('is_large_file', False):
                        is_large_file = True
                        actual_filename = filename
            
            # If not found by filename, check all active downloads
            if not is_large_file:
                for download_id, download in self.large_file_handler._active_downloads.items():
                    if download.get('is_large_file', False):
                        # Match by filename or if filename is unknown/empty
                        download_filename = download.get('filename', '')
                        if download_filename == filename or not filename or filename == 'unknown':
                            is_large_file = True
                            current_download = download
                            actual_filename = download_filename if download_filename != 'unknown' else filename
                            break
        
        # If no active large file but this looks like a large file, start tracking
        if not is_large_file and len(file_content) > 30000:  # Large chunk suggests large file
            logger.info(f"   🔍 Large chunk detected for {filename}, starting large file tracking")
            is_large_file = True
            if hasattr(self.large_file_handler, '_active_downloads'):
                # Generate a new download ID
                download_id = self.large_file_handler._next_download_id
                self.large_file_handler._next_download_id += 1
                
                self.large_file_handler._active_downloads[download_id] = {
                    'filename': filename,
                    'download_id': download_id,
                    'data': bytearray(),
                    'expected_size': 0,
                    'received_size': 0,
                    'is_large_file': True
                }
                self.large_file_handler._filename_to_id[filename] = download_id
                self.large_file_handler._current_large_file = download_id
                current_download = self.large_file_handler._active_downloads[download_id]
                actual_filename = filename
        
        # Handle large file accumulation - FIXED to extract just file content
        if is_large_file and current_download:
            # For large files, we need to extract just the file content from PLO_FILE
            # The parsed_data from PLO_FILE parser already extracts this correctly
            actual_filename = current_download['filename']
            
            # Use the parsed file content, not raw packet data
            current_download['data'].extend(file_content)
            current_download['received_size'] += len(file_content)
            
            logger.info(f"   📦 Added chunk to large file: {actual_filename} (+{len(file_content)} bytes)")
            logger.info(f"   📊 Total accumulated: {current_download['received_size']} bytes")
            
            # For debugging, check if accumulated data has PNG signature
            if len(current_download['data']) > 8:
                if bytes(current_download['data'][:8]).startswith(b'\x89PNG'):
                    logger.info(f"   ✅ Accumulated data has valid PNG signature")
                else:
                    logger.warning(f"   ⚠️ Accumulated data missing PNG signature: {bytes(current_download['data'][:8]).hex()}")
            
            # Don't cache yet - wait for PLO_LARGEFILEEND
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_FILE',
                'fields': {
                    'filename': actual_filename,
                    'chunk_size': len(file_content),
                    'total_size': current_download['received_size']
                }
            }
        
        # Process and cache small files immediately
        if self.cache_manager and filename and filename != 'unknown':
            from ..utils.compression import safe_decompress
            processed_data = safe_decompress(file_content)
            
            try:
                cache_path = self.cache_manager.save_file(filename, processed_data)
                logger.info(f"   💾 Cached: {cache_path}")
                
                self.stats['files_cached'] += 1
                self.stats['downloads_completed'] += 1
                
                # Emit file download event
                if self.event_manager:
                    self.event_manager.emit(EventType.FILE_DOWNLOADED, {
                        'filename': filename,
                        'size': len(processed_data),
                        'packet_id': packet_id
                    })
                
            except Exception as e:
                logger.error(f"   ❌ Failed to cache file: {e}")
                
        else:
            logger.warning(f"   ⚠️ Cannot cache file with invalid filename: '{filename}'")
        
        return {
            'packet_id': packet_id,
            'packet_name': 'PLO_FILE',
            'fields': {
                'filename': filename,
                'file_size': file_size
            }
        }
    
    def is_downloading_file(self, filename: str = None) -> bool:
        """Check if currently downloading a file (or any file if filename is None)"""
        if filename:
            # Check if specific file is being downloaded using filename-to-ID mapping
            if hasattr(self.large_file_handler, '_filename_to_id'):
                return filename in self.large_file_handler._filename_to_id
            return False
        else:
            # Check if any file is being downloaded
            return self.large_file_handler.is_receiving_file()
    
    def get_download_progress(self, filename: str = None) -> Dict[str, Any]:
        """Get download progress for a file or all files"""
        if filename:
            # Find download by filename using filename-to-ID mapping
            if hasattr(self.large_file_handler, '_filename_to_id') and filename in self.large_file_handler._filename_to_id:
                download_id = self.large_file_handler._filename_to_id[filename]
                if download_id in self.large_file_handler._active_downloads:
                    download = self.large_file_handler._active_downloads[download_id]
                    progress = 0.0
                    if download['expected_size'] > 0:
                        progress = (download['received_size'] / download['expected_size']) * 100
                    
                    return {
                        'filename': filename,
                        'received_size': download['received_size'],
                        'expected_size': download['expected_size'],
                        'progress_percent': progress
                    }
            return {}
        else:
            # Return progress for all active downloads
            all_progress = {}
            for download_id, download in self.large_file_handler._active_downloads.items():
                download_filename = download['filename']
                progress = 0.0
                if download['expected_size'] > 0:
                    progress = (download['received_size'] / download['expected_size']) * 100
                
                all_progress[download_filename] = {
                    'received_size': download['received_size'],
                    'expected_size': download['expected_size'],
                    'progress_percent': progress
                }
            
            return all_progress
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get file cache information"""
        cache_info = {}
        if self.cache_manager:
            cache_info = self.cache_manager.get_cache_info()
        
        return {
            'cache': cache_info,
            'downloads': self.stats,
            'active_downloads': len(self.large_file_handler._active_downloads)
        }
    
    def clear_cache(self, levels_only: bool = False):
        """Clear file cache"""
        if self.cache_manager:
            self.cache_manager.clear_cache(levels_only)
            logger.info(f"Cache cleared ({'levels only' if levels_only else 'all files'})")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get file manager statistics"""
        return {
            **self.stats,
            'active_downloads': len(self.large_file_handler._active_downloads),
            'cache_info': self.get_cache_info()
        }
    
    def cleanup(self):
        """Clean up file manager resources"""
        if self.large_file_handler:
            self.large_file_handler.cleanup()
        logger.info("File manager cleanup complete")


# Specific handler methods for packet delegation
class FileManagerPacketHandlers:
    """Mixin class providing specific packet handler methods"""
    
    def handle_plo_largefilestart(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILESTART packet"""
        return self.handle_packet(68, parsed_packet)
    
    def handle_plo_largefilesize(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILESIZE packet"""
        return self.handle_packet(84, parsed_packet)
    
    def handle_plo_rawdata(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_RAWDATA packet"""
        return self.handle_packet(100, parsed_packet)
    
    def handle_plo_largefileend(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILEEND packet"""
        return self.handle_packet(69, parsed_packet)
    
    def handle_plo_fileuptodate(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_FILEUPTODATE packet"""
        return self.handle_packet(45, parsed_packet)
    
    def handle_plo_filesend_failed(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_FILESEND_FAILED packet"""
        return self.handle_packet(30, parsed_packet)


# Complete FileManager class with handlers
class FileManager(FileManager, FileManagerPacketHandlers):
    """Complete file manager with packet handlers"""
    pass