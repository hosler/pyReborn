"""
Packet Processor - Handles packet parsing, dispatching, and processing pipeline
"""

import logging
from typing import Dict, Callable, Any, List, Tuple, Optional

from ..core.interfaces import IPacketProcessor, IPacketHandler
from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from ..protocol.unified_reader import StructureAwarePacketParser
from ..handlers.packet_handler import PacketHandler
from ..core.error_handling import ErrorHandler, ErrorCategory, ErrorSeverity, handle_errors


class PacketProcessor(IPacketProcessor):
    """Processes incoming packets using unified protocol reader and handlers"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Packet parsing
        self.parser = StructureAwarePacketParser(enable_validation=True)
        
        # Packet handlers
        self.packet_handler: Optional[PacketHandler] = None
        self.custom_handlers: List[IPacketHandler] = []
        self.handler_registry: Dict[int, List[Callable]] = {}
        
        # Statistics
        self.packets_processed = 0
        self.packets_failed = 0
        
        # Error handling
        self.error_handler: Optional[ErrorHandler] = None
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize with configuration and event system"""
        self.config = config
        self.events = event_manager
        
        # Initialize error handler
        self.error_handler = ErrorHandler(event_manager)
        self._setup_error_handlers()
        
        # Create default packet handler (needs the client context)
        # This will be set later when the client is fully constructed
        
    def cleanup(self) -> None:
        """Clean up resources"""
        self.custom_handlers.clear()
        self.handler_registry.clear()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "packet_processor"
    
    def set_client_context(self, client) -> None:
        """Set client context for packet handler (called after client construction)"""
        self.packet_handler = PacketHandler(client)
    
    def process_packet(self, packet_id: int, packet_data: bytes) -> None:
        """Process a single packet"""
        try:
            self.packets_processed += 1
            
            # Let packet handler process it
            if self.packet_handler:
                result = self.packet_handler.handle_packet(packet_id, packet_data)
                
                if self.config and self.config.debug_packets:
                    self.logger.debug(f"Processed packet {packet_id}: {result}")
            
            # Let custom handlers process it
            for handler in self.custom_handlers:
                if handler.can_handle(packet_id):
                    try:
                        context = {'packet_id': packet_id, 'events': self.events}
                        handler.handle(packet_id, packet_data, context)
                    except Exception as e:
                        self.logger.error(f"Custom handler error for packet {packet_id}: {e}")
            
            # Call registered handlers
            if packet_id in self.handler_registry:
                for handler_func in self.handler_registry[packet_id]:
                    try:
                        handler_func(packet_id, packet_data)
                    except Exception as e:
                        self.logger.error(f"Registered handler error for packet {packet_id}: {e}")
            
            # Emit raw packet event for advanced users
            if self.events:
                self.events.emit(EventType.RAW_PACKET_RECEIVED, 
                               packet_id=packet_id, 
                               packet_data=packet_data)
                
        except Exception as e:
            self.packets_failed += 1
            
            # Use error handler with context
            context = {
                'packet_id': packet_id,
                'packet_data_length': len(packet_data),
                'retry_function': lambda: self._retry_packet_processing(packet_id, packet_data),
                'fallback_function': lambda: self._fallback_packet_processing(packet_id, packet_data)
            }
            
            if self.error_handler:
                self.error_handler.handle_packet_error(packet_data, e, context)
            else:
                self.logger.error(f"Packet processing failed for ID {packet_id}: {e}")
            
            if self.events:
                self.events.emit(EventType.PACKET_RECEIVED, 
                               packet_id=packet_id, 
                               error=str(e))
    
    def process_raw_data(self, raw_data: bytes) -> None:
        """Process raw decrypted data from connection"""
        try:
            # Parse packets using unified parser
            packets = self.parser.parse_packets(raw_data)
            
            # Process each parsed packet
            for packet_id, packet_data, parsed_fields in packets:
                if packet_id >= 0:  # Skip raw data chunks (negative IDs)
                    self.process_packet(packet_id, packet_data)
                elif self.config and self.config.debug_packets:
                    # Log raw data events
                    packet_type = parsed_fields.get('type', 'unknown')
                    self.logger.debug(f"Raw data event: {packet_type}")
                    
        except Exception as e:
            self.packets_failed += 1
            
            # Use error handler with context
            context = {
                'raw_data_length': len(raw_data),
                'retry_function': lambda: self._retry_raw_data_processing(raw_data),
                'fallback_function': lambda: self._fallback_raw_data_processing(raw_data)
            }
            
            if self.error_handler:
                self.error_handler.handle_packet_error(raw_data, e, context)
            else:
                self.logger.error(f"Raw data processing failed: {e}")
    
    def register_handler(self, packet_id: int, handler: Callable) -> None:
        """Register a handler function for a specific packet ID"""
        if packet_id not in self.handler_registry:
            self.handler_registry[packet_id] = []
        
        self.handler_registry[packet_id].append(handler)
        self.logger.debug(f"Registered handler for packet {packet_id}")
    
    def unregister_handler(self, packet_id: int, handler: Callable) -> None:
        """Unregister a handler function"""
        if packet_id in self.handler_registry:
            try:
                self.handler_registry[packet_id].remove(handler)
                if not self.handler_registry[packet_id]:
                    del self.handler_registry[packet_id]
            except ValueError:
                pass
    
    def add_custom_handler(self, handler: IPacketHandler) -> None:
        """Add a custom packet handler"""
        # Insert based on priority (higher priority first)
        inserted = False
        for i, existing_handler in enumerate(self.custom_handlers):
            if handler.priority > existing_handler.priority:
                self.custom_handlers.insert(i, handler)
                inserted = True
                break
        
        if not inserted:
            self.custom_handlers.append(handler)
        
        self.logger.debug(f"Added custom handler with priority {handler.priority}")
    
    def remove_custom_handler(self, handler: IPacketHandler) -> None:
        """Remove a custom packet handler"""
        try:
            self.custom_handlers.remove(handler)
        except ValueError:
            pass
    
    def get_packet_statistics(self) -> Dict[str, int]:
        """Get packet processing statistics"""
        return {
            'packets_processed': self.packets_processed,
            'packets_failed': self.packets_failed,
            'custom_handlers': len(self.custom_handlers),
            'registered_handlers': sum(len(handlers) for handlers in self.handler_registry.values())
        }
    
    def reset_statistics(self) -> None:
        """Reset packet processing statistics"""
        self.packets_processed = 0
        self.packets_failed = 0
    
    def set_debug_mode(self, enabled: bool) -> None:
        """Enable or disable debug mode"""
        if self.config:
            self.config.debug_packets = enabled
        
        # Update parser validation
        self.parser.enable_validation = enabled
    
    def get_parser_state(self) -> Dict[str, Any]:
        """Get current parser state (for debugging)"""
        return {
            'rawdata_mode': self.parser.rawdata_mode,
            'rawdata_bytes_remaining': self.parser.rawdata_bytes_remaining,
            'rawdata_accumulated_size': len(self.parser.rawdata_accumulated)
        }
    
    def _setup_error_handlers(self) -> None:
        """Set up category-specific error handlers"""
        if not self.error_handler:
            return
        
        # Register protocol error handler
        self.error_handler.register_category_handler(
            ErrorCategory.PROTOCOL,
            self._handle_protocol_error
        )
        
        # Register parsing error handler
        self.error_handler.register_category_handler(
            ErrorCategory.PARSING,
            self._handle_parsing_error
        )
    
    def _handle_protocol_error(self, error_info) -> None:
        """Handle protocol-specific errors"""
        self.logger.warning(f"Protocol error: {error_info.message}")
        
        # Emit protocol error event
        if self.events:
            self.events.emit(EventType.PROTOCOL_ERROR, {
                'message': error_info.message,
                'severity': error_info.severity.value,
                'context': error_info.context
            })
    
    def _handle_parsing_error(self, error_info) -> None:
        """Handle parsing-specific errors"""
        self.logger.warning(f"Parsing error: {error_info.message}")
        
        # Try to reset parser state if needed
        if 'reset_parser' in error_info.context:
            self.parser.reset_state()
    
    def _retry_raw_data_processing(self, raw_data: bytes) -> bool:
        """Retry raw data processing with fresh parser state"""
        try:
            # Reset parser state and try again
            self.parser.reset_state()
            packets = self.parser.parse_packets(raw_data)
            
            # Process each parsed packet
            for packet_id, packet_data, parsed_fields in packets:
                if packet_id >= 0:
                    self.process_packet(packet_id, packet_data)
            
            return True
        except Exception:
            return False
    
    def _fallback_raw_data_processing(self, raw_data: bytes) -> bytes:
        """Fallback processing for raw data"""
        try:
            # Try simple packet splitting on newlines
            if b'\\n' in raw_data:
                chunks = raw_data.split(b'\\n')
                for chunk in chunks:
                    if chunk and len(chunk) > 0:
                        # Try to extract packet ID
                        packet_id = chunk[0] - 32 if chunk[0] >= 32 else chunk[0]
                        self.logger.debug(f"Fallback processing packet ID {packet_id}")
                        
                        # Emit as raw packet
                        if self.events:
                            self.events.emit(EventType.RAW_PACKET_RECEIVED,
                                           packet_id=packet_id,
                                           packet_data=chunk[1:])
                return raw_data
        except Exception:
            pass
        
        return None
    
    def _retry_packet_processing(self, packet_id: int, packet_data: bytes) -> bool:
        """Retry packet processing with simpler approach"""
        try:
            # Try with just the main packet handler
            if self.packet_handler:
                result = self.packet_handler.handle_packet(packet_id, packet_data)
                return result is not None
        except Exception:
            pass
        
        return False
    
    def _fallback_packet_processing(self, packet_id: int, packet_data: bytes) -> bool:
        """Fallback packet processing"""
        try:
            # Just emit the raw packet event
            if self.events:
                self.events.emit(EventType.RAW_PACKET_RECEIVED,
                               packet_id=packet_id,
                               packet_data=packet_data)
                return True
        except Exception:
            pass
        
        return False
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error handling statistics"""
        if self.error_handler:
            return self.error_handler.get_error_statistics()
        return {}