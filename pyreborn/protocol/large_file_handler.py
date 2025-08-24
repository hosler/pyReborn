#!/usr/bin/env python3
"""
Large File Handler - Handles large file downloads from server

This is a new implementation that replaces the old LargeFilePacketHandler,
designed to work with the registry-driven architecture.
"""

import logging
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import os

logger = logging.getLogger(__name__)


class LargeFileHandler:
    """Handles large file downloads split across multiple packets"""
    
    def __init__(self, event_manager=None, cache_manager=None):
        self.event_manager = event_manager
        self.cache_manager = cache_manager
        self.client = None  # Set by client after creation
        
        # Active downloads - track by download ID for consistency
        self._active_downloads: Dict[int, Dict[str, Any]] = {}
        self._filename_to_id: Dict[str, int] = {}  # Map filenames to download IDs
        self._current_large_file = None
        self._next_download_id = 1  # Auto-generate IDs if not provided
        
        # Inspection directory for downloaded files
        self.inspection_dir = Path("downloads/inspection")
        self.inspection_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Large file handler initialized")
        logger.info(f"Inspection directory: {self.inspection_dir}")
        
    def handle_large_file_start(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILESTART packet (68)"""
        try:
            # Parse packet using registry system
            from ..packets import PACKET_REGISTRY
            structure = PACKET_REGISTRY.get_structure(packet_id)
            if not structure:
                logger.error(f"No packet structure found for packet {packet_id}")
                return None
                
            # Use registry parser to get fields
            from .registry_packet_parser import RegistryPacketParser
            parser = RegistryPacketParser()
            parsed = parser.parse_packet(packet_id, data, announced_size)
            if not parsed:
                logger.error(f"Failed to parse PLO_LARGEFILESTART packet")
                return None
                
            fields = parsed.get('fields', {})
            filename = fields.get('file_name', 'unknown')
            download_id = fields.get('download_id', self._next_download_id)
            
            # Auto-generate ID if not provided
            if download_id == self._next_download_id:
                self._next_download_id += 1
            
            logger.info(f"Large file download started: filename={filename}, download_id={download_id}")
            
            # Initialize download tracking by download ID
            self._active_downloads[download_id] = {
                'filename': filename,
                'download_id': download_id,
                'data': bytearray(),
                'expected_size': 0,
                'received_size': 0,
                'is_large_file': True
            }
            self._filename_to_id[filename] = download_id
            self._current_large_file = download_id
            
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_LARGEFILESTART',
                'fields': {
                    'filename': filename,
                    'download_id': download_id
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling PLO_LARGEFILESTART: {e}")
            return None
    
    def handle_large_file_size(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILESIZE packet (84)"""
        try:
            # Parse packet using registry system
            from .registry_packet_parser import RegistryPacketParser
            parser = RegistryPacketParser()
            parsed = parser.parse_packet(packet_id, data, announced_size)
            if not parsed:
                logger.error(f"Failed to parse PLO_LARGEFILESIZE packet")
                return None
                
            fields = parsed.get('fields', {})
            download_id = fields.get('download_id', 0)
            file_size = fields.get('file_size', 0)
            
            if download_id in self._active_downloads:
                self._active_downloads[download_id]['expected_size'] = file_size
                logger.info(f"Large file size: ID={download_id}, size={file_size} bytes")
            else:
                logger.warning(f"Received file size for unknown download ID: {download_id}")
                
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_LARGEFILESIZE',
                'fields': {
                    'download_id': download_id,
                    'file_size': file_size
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling PLO_LARGEFILESIZE: {e}")
            return None
    
    def handle_raw_data(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """Handle PLO_RAWDATA packet (100) - contains file data chunks"""
        try:
            # Parse packet using registry system
            from .registry_packet_parser import RegistryPacketParser
            parser = RegistryPacketParser()
            parsed = parser.parse_packet(packet_id, data, announced_size)
            if not parsed:
                logger.error(f"Failed to parse PLO_RAWDATA packet")
                return None
                
            fields = parsed.get('fields', {})
            download_id = fields.get('download_id', 0)
            chunk_data = fields.get('data', b'')
            
            if download_id in self._active_downloads:
                download = self._active_downloads[download_id]
                download['data'].extend(chunk_data)
                download['received_size'] += len(chunk_data)
                
                logger.debug(f"Received chunk for download {download_id}: {len(chunk_data)} bytes "
                           f"({download['received_size']}/{download['expected_size']})")
            else:
                logger.warning(f"Received data for unknown download ID: {download_id}")
                
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_RAWDATA',
                'fields': {
                    'download_id': download_id,
                    'chunk_size': len(chunk_data),
                    'total_received': self._active_downloads.get(download_id, {}).get('received_size', 0)
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling PLO_RAWDATA: {e}")
            return None
    
    def handle_large_file_end(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """Handle PLO_LARGEFILEEND packet (69) - signals download complete"""
        try:
            # Parse packet using registry system
            from .registry_packet_parser import RegistryPacketParser
            parser = RegistryPacketParser()
            parsed = parser.parse_packet(packet_id, data, announced_size)
            if not parsed:
                logger.error(f"Failed to parse PLO_LARGEFILEEND packet")
                return None
                
            fields = parsed.get('fields', {})
            filename = fields.get('filename', 'unknown')
            download_id = fields.get('download_id', self._current_large_file)
            
            # Try to find download by ID first, then by filename
            download = None
            actual_download_id = None
            
            if download_id and download_id in self._active_downloads:
                download = self._active_downloads[download_id]
                actual_download_id = download_id
            elif filename in self._filename_to_id:
                actual_download_id = self._filename_to_id[filename]
                download = self._active_downloads[actual_download_id]
            
            if not download:
                logger.warning(f"Received file end for unknown download: filename={filename}, download_id={download_id}")
                return None
                
            actual_filename = download['filename']
            file_data = bytes(download['data'])
            
            logger.info(f"Large file download complete: {actual_filename} ({len(file_data)} bytes)")
            
            # Save to inspection directory
            inspection_path = self.inspection_dir / actual_filename
            try:
                with open(inspection_path, 'wb') as f:
                    f.write(file_data)
                logger.info(f"Saved to inspection: {inspection_path}")
            except Exception as e:
                logger.error(f"Failed to save to inspection: {e}")
            
            # Process the file based on type - decompress if needed
            try:
                from ..utils.compression import safe_decompress
                processed_data = safe_decompress(file_data)
                if processed_data != file_data:
                    logger.info(f"Decompressed large file: {len(file_data)} -> {len(processed_data)} bytes")
                    file_data = processed_data
            except Exception as e:
                logger.warning(f"Decompression failed, using raw data: {e}")
            
            # Save to cache
            if self.cache_manager:
                cache_path = self.cache_manager.save_file(actual_filename, file_data)
                logger.info(f"Cached large file: {cache_path}")
            
            # Emit event
            if self.event_manager:
                from ..session.events import EventType
                self.event_manager.emit(EventType.FILE_DOWNLOADED, {
                    'filename': actual_filename,
                    'size': len(file_data),
                    'data': file_data
                })
            
            # Clean up
            del self._active_downloads[actual_download_id]
            if actual_filename in self._filename_to_id:
                del self._filename_to_id[actual_filename]
            self._current_large_file = None
            
            return {
                'packet_id': packet_id,
                'packet_name': 'PLO_LARGEFILEEND', 
                'fields': {
                    'download_id': actual_download_id,
                    'filename': actual_filename,
                    'file_size': len(file_data)
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling PLO_LARGEFILEEND: {e}")
            return None
    
    def _process_downloaded_file(self, filename: str, file_data: bytes):
        """Process downloaded file based on type"""
        try:
            # Handle potential compression
            processed_data = file_data
            try:
                from ..utils.compression import safe_decompress
                processed_data = safe_decompress(file_data)
                if processed_data != file_data:
                    logger.info(f"Decompressed file data: {len(file_data)} -> {len(processed_data)} bytes")
            except Exception as e:
                logger.warning(f"Decompression attempt failed, using original data: {e}")
                processed_data = file_data
            
            # Use cache manager if available
            if self.cache_manager:
                # Use the save_file method which handles file type detection automatically
                cache_path = self.cache_manager.save_file(filename, processed_data)
                logger.info(f"Cached file: {cache_path}")
                    
            # Emit event for file download complete
            if self.event_manager:
                from ..session.events import EventType
                self.event_manager.emit(EventType.FILE_DOWNLOADED, {
                    'filename': filename,
                    'size': len(file_data),
                    'data': file_data
                })
                
        except Exception as e:
            logger.error(f"Error processing downloaded file {filename}: {e}")
    
    def is_receiving_file(self) -> bool:
        """Check if currently receiving any file"""
        return len(self._active_downloads) > 0
    
    def cleanup(self):
        """Clean up any active downloads"""
        if self._active_downloads:
            logger.warning(f"Cleaning up {len(self._active_downloads)} incomplete downloads")
            self._active_downloads.clear()
            self._filename_to_id.clear()