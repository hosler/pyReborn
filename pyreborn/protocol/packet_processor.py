"""
Packet Processor - Handles packet parsing, dispatching, and processing pipeline
"""

import logging
from typing import Dict, Callable, Any, List, Tuple, Optional

from .interfaces import IPacketProcessor, IPacketHandler
from ..config.client_config import ClientConfig
from ..session.events import EventManager, EventType
from .unified_reader import StructureAwarePacketParser
from ..protocol.registry_packet_parser import RegistryPacketParser
from ..protocol.manager_packet_processor import ManagerPacketProcessor
from ..session.error_handling import (
    ErrorHandler,
    ErrorCategory,
    ErrorSeverity,
    handle_errors,
)


class PacketProcessor(IPacketProcessor):
    """Processes incoming packets using unified protocol reader and handlers"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None

        # Packet parsing - NEW registry-driven system
        self.registry_parser = RegistryPacketParser()
        self.manager_processor: Optional[ManagerPacketProcessor] = None
        
        # Legacy parser for backward compatibility
        self.parser = StructureAwarePacketParser(enable_validation=True)
        self.packet_handler: Optional['PacketHandler'] = None
        self.custom_handlers: List[IPacketHandler] = []
        self.handler_registry: Dict[int, List[Callable]] = {}

        # Statistics
        self.packets_processed = 0
        self.packets_failed = 0

        # Error handling
        self.error_handler: Optional[ErrorHandler] = None

        # Client context for manager access
        self.client_context = None

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

    def process_structured_packet(
        self, packet_id: int, packet_data: bytes, parsed_fields: Dict[str, Any]
    ) -> None:
        """Process a packet with structured data from the unified parser"""
        try:
            self.packets_processed += 1

            # Log structured packet processing
            if self.config and self.config.debug_packets:
                self.logger.debug(
                    f"Processing structured packet {packet_id}: {parsed_fields}"
                )

            # Let packet handler process with structured data
            if self.packet_handler:
                result = self.packet_handler.handle_structured_packet(
                    packet_id, packet_data, parsed_fields
                )

                if self.config and self.config.debug_packets:
                    self.logger.debug(
                        f"Processed structured packet {packet_id}: {result}"
                    )

                # Dispatch packet results to appropriate managers
                if result:
                    self._dispatch_packet_result(result)
            else:
                self.logger.debug(f"No packet handler available for packet {packet_id}")

            # Let custom handlers process it (with structured data available)
            for handler in self.custom_handlers:
                if handler.can_handle(packet_id):
                    try:
                        context = {
                            "packet_id": packet_id,
                            "events": self.events,
                            "parsed_fields": parsed_fields,
                        }
                        handler.handle(packet_id, packet_data, context)
                    except Exception as e:
                        self.logger.error(
                            f"Custom handler error for structured packet {packet_id}: {e}"
                        )

            # Call registered handlers (pass structured data in context)
            if packet_id in self.handler_registry:
                for handler_func in self.handler_registry[packet_id]:
                    try:
                        # For backward compatibility, also try with just packet_id and data
                        import inspect

                        sig = inspect.signature(handler_func)
                        if len(sig.parameters) >= 3:
                            handler_func(packet_id, packet_data, parsed_fields)
                        else:
                            handler_func(packet_id, packet_data)
                    except Exception as e:
                        self.logger.error(
                            f"Registered handler error for structured packet {packet_id}: {e}"
                        )

            # Emit structured packet event
            if self.events:
                # Check if event type exists
                if hasattr(EventType, 'STRUCTURED_PACKET_RECEIVED'):
                    self.events.emit(
                        EventType.STRUCTURED_PACKET_RECEIVED,
                        {
                            'packet_id': packet_id,
                            'packet_data': packet_data,
                            'parsed_fields': parsed_fields,
                        }
                    )

        except Exception as e:
            self.packets_failed += 1

            # Use error handler with context including structured data
            context = {
                "packet_id": packet_id,
                "packet_data_length": len(packet_data),
                "parsed_fields": parsed_fields,
                "retry_function": lambda: self._retry_structured_packet_processing(
                    packet_id, packet_data, parsed_fields
                ),
                "fallback_function": lambda: self._fallback_structured_packet_processing(
                    packet_id, packet_data, parsed_fields
                ),
            }

            if self.error_handler:
                self.error_handler.handle_packet_error(packet_data, e, context)
            else:
                self.logger.error(
                    f"Structured packet processing failed for ID {packet_id}: {e}"
                )

            if self.events:
                # Use PACKET_RECEIVED for packet errors
                self.events.emit(
                    EventType.PACKET_RECEIVED,
                    {'packet_id': packet_id, 'error': str(e)}
                )

    def process_packet(self, packet_id: int, packet_data: bytes) -> None:
        """Process a single packet using NEW registry-driven system"""
        try:
            self.packets_processed += 1

            # Use NEW registry-driven system first
            if self.manager_processor:
                self.logger.debug(
                    f"[PACKET_PROCESSOR] Using NEW ManagerPacketProcessor for packet {packet_id}"
                )
                
                # Parse with registry parser first
                parsed_packet = self.registry_parser.parse_packet(packet_id, packet_data)
                
                if parsed_packet:
                    # Emit raw packet received event for tracking
                    if self.events:
                        self.events.emit(EventType.RAW_PACKET_RECEIVED, {'packet_id': packet_id, 'data': packet_data})
                    
                    # Use manager processor for business logic (pass raw data, not parsed)
                    self.manager_processor.process_packet(packet_id, packet_data)
                    
                    if self.config and self.config.debug_packets:
                        self.logger.debug(f"NEW: Processed packet {packet_id} with registry system")
                    return
                else:
                    self.logger.debug(f"Registry parser could not handle packet {packet_id}, falling back to legacy")

            # FALLBACK: Let legacy packet handler process it
            if self.packet_handler:
                self.logger.debug(
                    f"[PACKET_PROCESSOR] Using LEGACY PacketHandler to process packet {packet_id}"
                )
                result = self.packet_handler.handle_packet(packet_id, packet_data)

                if self.config and self.config.debug_packets:
                    self.logger.debug(f"LEGACY: Processed packet {packet_id}: {result}")

                # Dispatch packet results to appropriate managers
                if result:
                    self.logger.debug(
                        f"[PRE_DISPATCH] Packet {packet_id} result: {result}"
                    )
                    self._dispatch_packet_result(result)
                else:
                    self.logger.debug(
                        f"[PRE_DISPATCH] Packet {packet_id} returned no result"
                    )
            else:
                self.logger.warning(
                    f"[PACKET_PROCESSOR] No PacketHandler available for packet {packet_id} - parsing will likely fail"
                )

            # Let custom handlers process it
            for handler in self.custom_handlers:
                if handler.can_handle(packet_id):
                    try:
                        context = {"packet_id": packet_id, "events": self.events}
                        handler.handle(packet_id, packet_data, context)
                    except Exception as e:
                        self.logger.error(
                            f"Custom handler error for packet {packet_id}: {e}"
                        )

            # Call registered handlers
            if packet_id in self.handler_registry:
                for handler_func in self.handler_registry[packet_id]:
                    try:
                        handler_func(packet_id, packet_data)
                    except Exception as e:
                        self.logger.error(
                            f"Registered handler error for packet {packet_id}: {e}"
                        )

            # Emit raw packet event for advanced users
            if self.events:
                self.events.emit(
                    EventType.RAW_PACKET_RECEIVED,
                    {
                        'packet_id': packet_id,
                        'packet_data': packet_data,
                    }
                )

        except Exception as e:
            self.packets_failed += 1

            # Use error handler with context
            context = {
                "packet_id": packet_id,
                "packet_data_length": len(packet_data),
                "retry_function": lambda: self._retry_packet_processing(
                    packet_id, packet_data
                ),
                "fallback_function": lambda: self._fallback_packet_processing(
                    packet_id, packet_data
                ),
            }

            if self.error_handler:
                self.error_handler.handle_packet_error(packet_data, e, context)
            else:
                self.logger.error(f"Packet processing failed for ID {packet_id}: {e}")

            if self.events:
                self.events.emit(
                    EventType.PACKET_RECEIVED, {'packet_id': packet_id, 'error': str(e)}
                )

    def process_raw_data(self, raw_data: bytes) -> None:
        """Process raw decrypted data from connection"""
        try:
            self.logger.debug(f"Processing raw data: {len(raw_data)} bytes")

            # Check for PLO_RAWDATA (100) and PLO_BOARDPACKET (101) in the data
            if len(raw_data) > 0:
                first_byte = raw_data[0]
                potential_packet_id = first_byte - 32 if first_byte > 32 else first_byte

                # Debug logging for special packets (reduced verbosity)
                if potential_packet_id in [100, 101]:
                    self.logger.debug(
                        f"Processing packet {potential_packet_id} (size: {len(raw_data)} bytes)"
                    )

            # The raw_data is now properly decrypted by version codec
            # Use unified parser for all packet processing
            try:
                packets = self.parser.parse_packets(raw_data)
                if packets and len(packets) > 0:
                    self.logger.debug(f"Unified parser found {len(packets)} packets")
                    # Process each parsed packet
                    for packet_id, packet_data, parsed_fields in packets:
                        if packet_id >= 0:  # Regular packets
                            self.logger.debug(
                                f"Processing unified packet ID: {packet_id}, size: {len(packet_data)}, fields: {parsed_fields}"
                            )
                            # Try NEW system first
                            if self.manager_processor:
                                # Pass raw data directly to manager processor
                                # It will handle parsing internally
                                self.manager_processor.process_packet(packet_id, packet_data)
                                continue
                            
                            # Fallback to legacy processing
                            self.process_packet(packet_id, packet_data)
                        # Skip raw data chunks and other special packet IDs
                else:
                    self.logger.debug("No packets found in data")
                return

            except Exception as e:
                self.logger.error(f"Unified parser failed: {e}")
                import traceback

                self.logger.debug(f"Unified parser traceback: {traceback.format_exc()}")

                # Only fall back to manual processing in exceptional cases
                self.logger.warning(
                    "Falling back to manual packet processing due to parser failure"
                )
                self._emergency_fallback_processing(raw_data)

        except Exception as e:
            self.packets_failed += 1

            # Use error handler with context
            context = {
                "raw_data_length": len(raw_data),
                "retry_function": lambda: self._retry_raw_data_processing(raw_data),
                "fallback_function": lambda: self._fallback_raw_data_processing(
                    raw_data
                ),
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
    
    def get_handler(self, packet_id: int) -> Optional[Callable]:
        """Get the first registered handler for a packet ID"""
        handlers = self.handler_registry.get(packet_id, [])
        return handlers[0] if handlers else None

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
            "packets_processed": self.packets_processed,
            "packets_failed": self.packets_failed,
            "custom_handlers": len(self.custom_handlers),
            "registered_handlers": sum(
                len(handlers) for handlers in self.handler_registry.values()
            ),
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
            "rawdata_mode": self.parser.rawdata_mode,
            "rawdata_bytes_remaining": self.parser.rawdata_bytes_remaining,
            "rawdata_accumulated_size": len(self.parser.rawdata_accumulated),
        }

    def _setup_error_handlers(self) -> None:
        """Set up category-specific error handlers"""
        if not self.error_handler:
            return

        # Register protocol error handler
        self.error_handler.register_category_handler(
            ErrorCategory.PROTOCOL, self._handle_protocol_error
        )

        # Register parsing error handler
        self.error_handler.register_category_handler(
            ErrorCategory.PARSING, self._handle_parsing_error
        )

    def _handle_protocol_error(self, error_info) -> None:
        """Handle protocol-specific errors"""
        self.logger.warning(f"Protocol error: {error_info.message}")

        # Emit protocol error event
        if self.events:
            self.events.emit(
                EventType.PROTOCOL_ERROR,
                {
                    "message": error_info.message,
                    "severity": error_info.severity.value,
                    "context": error_info.context,
                },
            )

    def _handle_parsing_error(self, error_info) -> None:
        """Handle parsing-specific errors"""
        self.logger.warning(f"Parsing error: {error_info.message}")

        # Try to reset parser state if needed
        if "reset_parser" in error_info.context:
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
            if b"\n" in raw_data:
                chunks = raw_data.split(b"\n")
                for chunk in chunks:
                    if chunk and len(chunk) > 0:
                        # Try to extract packet ID
                        packet_id = chunk[0] - 32 if chunk[0] >= 32 else chunk[0]
                        self.logger.debug(f"Fallback processing packet ID {packet_id}")

                        # Emit as raw packet
                        if self.events:
                            self.events.emit(
                                EventType.RAW_PACKET_RECEIVED,
                                {
                                    'packet_id': packet_id,
                                    'packet_data': chunk[1:],
                                }
                            )
                return raw_data
        except Exception:
            pass

        return None

    def _retry_structured_packet_processing(
        self, packet_id: int, packet_data: bytes, parsed_fields: Dict[str, Any]
    ) -> bool:
        """Retry structured packet processing with simpler approach"""
        try:
            # Try with just the main packet handler in structured mode
            if self.packet_handler:
                result = self.packet_handler.handle_structured_packet(
                    packet_id, packet_data, parsed_fields
                )
                return result is not None
        except Exception:
            # Fall back to regular packet processing
            try:
                return self._retry_packet_processing(packet_id, packet_data)
            except Exception:
                pass

        return False

    def _fallback_structured_packet_processing(
        self, packet_id: int, packet_data: bytes, parsed_fields: Dict[str, Any]
    ) -> bool:
        """Fallback structured packet processing"""
        try:
            # Just emit the structured packet event
            if self.events:
                self.events.emit(
                    EventType.STRUCTURED_PACKET_RECEIVED,
                    {
                        'packet_id': packet_id,
                        'packet_data': packet_data,
                        'parsed_fields': parsed_fields,
                    }
                )
                return True
        except Exception:
            # Fall back to regular fallback processing
            try:
                return self._fallback_packet_processing(packet_id, packet_data)
            except Exception:
                pass

        return False

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
                self.events.emit(
                    EventType.RAW_PACKET_RECEIVED,
                    {
                        'packet_id': packet_id,
                        'packet_data': packet_data,
                    }
                )
                return True
        except Exception:
            pass

        return False

    def _process_raw_data_complete(
        self, raw_data: bytes, parsed_fields: Dict[str, Any]
    ) -> None:
        """Process completed raw data accumulation (usually contains PLO_BOARDPACKET)"""
        try:
            total_size = parsed_fields.get("total_size", len(raw_data))
            self.logger.info(f"Processing complete raw data: {total_size:,} bytes")

            # Check if this looks like PLO_BOARDPACKET data (8194 bytes = 1 + 8192 + 1)
            if total_size == 8194 and len(raw_data) >= 8194:
                # Should start with PLO_BOARDPACKET ID (133 = 101 + 32)
                if raw_data[0] == 133:  # PLO_BOARDPACKET
                    self.logger.info(
                        "Raw data contains PLO_BOARDPACKET with full board data!"
                    )

                    # Extract the board data (skip packet ID, take 8192 bytes)
                    board_data = raw_data[1:8193]  # Skip the packet ID byte

                    self.logger.debug(
                        f"Extracted {len(board_data):,} bytes of board data from raw stream"
                    )

                    # Parse as 64x64 tile grid like the old client
                    import struct

                    tiles = []
                    for i in range(4096):  # 64*64 = 4096 tiles
                        if i * 2 + 1 < len(board_data):
                            tile_id = struct.unpack(
                                "<H", board_data[i * 2 : i * 2 + 2]
                            )[0]
                            tiles.append(tile_id)
                        else:
                            tiles.append(0)

                    # Show first few tiles for debugging
                    first_tiles = tiles[:10] if len(tiles) >= 10 else tiles
                    self.logger.info(f"First 10 tile IDs: {first_tiles}")

                    # Apply to level manager if available
                    if self.packet_handler and self.packet_handler.client:
                        client = self.packet_handler.client
                        if hasattr(client, "level_manager"):
                            client.level_manager.handle_board_packet(board_data)
                            self.logger.info("Applied board data to level manager")

                    # Emit structured board event
                    if self.events:
                        self.events.emit(
                            EventType.STRUCTURED_PACKET_RECEIVED,
                            packet_id=101,
                            packet_data=board_data,
                            parsed_fields={
                                "packet_type": "PLO_BOARDPACKET",
                                "board_data": board_data,
                                "tiles": tiles,
                                "width": 64,
                                "height": 64,
                                "data_format": "reborn_64x64_tiles",
                                "source": "raw_data_accumulation",
                            },
                        )

                    return
                else:
                    self.logger.warning(
                        f"Expected PLO_BOARDPACKET (133) but got {raw_data[0]}"
                    )

            # For other raw data, try to parse as regular packet stream
            self.logger.debug(
                f"Processing raw data as packet stream: {len(raw_data)} bytes"
            )
            self._emergency_fallback_processing(raw_data)

        except Exception as e:
            self.logger.error(f"Error processing raw data complete: {e}")
            import traceback

            self.logger.debug(
                f"Raw data processing traceback: {traceback.format_exc()}"
            )

    def _emergency_fallback_processing(self, raw_data: bytes) -> None:
        """Emergency fallback processing when unified parser fails completely"""
        try:
            # Split on newlines to separate individual packets
            packet_chunks = raw_data.split(b"\n")

            for i, chunk in enumerate(packet_chunks):
                if len(chunk) == 0:
                    continue

                # Each chunk should start with packet_id + 32
                packet_id = chunk[0] - 32 if chunk[0] > 32 else chunk[0]

                # Add back the newline for proper packet format (except last chunk)
                if i < len(packet_chunks) - 1:
                    packet_data = chunk + b"\n"
                else:
                    packet_data = chunk

                self.logger.debug(
                    f"Processing concatenated packet ID: {packet_id}, size: {len(packet_data)}"
                )

                # Special logging for packets we're looking for
                if packet_id in [100, 101]:
                    self.logger.warning(
                        f"*** PROCESSING PACKET {packet_id} *** Size: {len(packet_data)} bytes"
                    )

                # Process the individual packet using legacy method (no structured data)
                self.logger.warning(f"Emergency processing packet ID: {packet_id}")
                self.process_packet(packet_id, packet_data)

        except Exception as e:
            self.logger.error(f"Error processing concatenated packets: {e}")
            # Fallback to single packet processing
            packet_id = raw_data[0] - 32 if raw_data[0] > 32 else raw_data[0]
            self.logger.debug(
                f"Fallback processing packet ID: {packet_id}, size: {len(raw_data)}"
            )
            self.process_packet(packet_id, raw_data)

    def set_client_context(self, client) -> None:
        """Set client context for manager access and create new registry-driven processors"""
        self.logger.info(
            f"[PACKET_PROCESSOR] Setting client context: {type(client).__name__}"
        )
        self.client_context = client

        # Create the NEW registry-driven ManagerPacketProcessor
        if not self.manager_processor:
            try:
                self.manager_processor = ManagerPacketProcessor(client)
                self.logger.info(
                    f"[PACKET_PROCESSOR] NEW ManagerPacketProcessor created successfully with client: {type(client).__name__}"
                )

                # Test that NEW manager processor is working
                if hasattr(self.manager_processor, "process_packet"):
                    self.logger.debug(
                        f"[PACKET_PROCESSOR] NEW ManagerPacketProcessor has process_packet method"
                    )
                else:
                    self.logger.error(
                        f"[PACKET_PROCESSOR] NEW ManagerPacketProcessor missing process_packet method!"
                    )

            except Exception as e:
                self.logger.error(
                    f"[PACKET_PROCESSOR] Failed to create NEW ManagerPacketProcessor: {e}"
                )
                import traceback
                self.logger.error(
                    f"[PACKET_PROCESSOR] ManagerPacketProcessor creation traceback: {traceback.format_exc()}"
                )

        # NO LEGACY FALLBACK - Use registry-driven system only
        self.packet_handler = None

    def _dispatch_packet_result(self, result: Dict[str, Any]) -> None:
        """Dispatch packet handler results to appropriate managers"""
        if not result or not isinstance(result, dict):
            return

        packet_type = result.get("type")
        if not packet_type:
            return

        try:
            # Get managers from client context
            if not self.client_context:
                self.logger.debug("No client context available for packet dispatching")
                return

            # Handle level_name packets
            if packet_type == "level_name":
                level_name = result.get("name")
                if level_name and hasattr(self.client_context, "level_manager"):
                    self.logger.info(
                        f"[DISPATCH] Level name packet processed: '{level_name}' (events already emitted by handler)"
                    )
                    # StandardizedLevelManager uses events, not direct method calls
                    # self.client_context.level_manager.handle_level_name(level_name)

            # Handle board_packet
            elif packet_type == "board_packet":
                board_data = result.get("board_data")
                if board_data and hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Board packet processed: {len(board_data)} bytes"
                    )
                    # StandardizedLevelManager uses events, not direct method calls
                    # self.client_context.level_manager.handle_board_packet(board_data)

            # Handle level_board
            elif packet_type == "level_board":
                board_data = result.get("data")
                if board_data and hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Level board processed: {len(board_data)} bytes"
                    )
                    # StandardizedLevelManager uses events, not direct method calls
                    # self.client_context.level_manager.handle_level_board(board_data)

            # Handle board_modify
            elif packet_type == "board_modify":
                if hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Board modify processed (events already emitted by handler)"
                    )
                    # StandardizedLevelManager uses events, not direct method calls
                    # self.client_context.level_manager.handle_board_modify(
                    #     result.get("x", 0), result.get("y", 0),
                    #     result.get("width", 0), result.get("height", 0),
                    #     result.get("tiles", [])
                    # )

            # Handle level_sign
            elif packet_type == "level_sign":
                if hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Level sign processed (events already emitted by handler)"
                    )
                    # StandardizedLevelManager uses events, not direct method calls
                    # self.client_context.level_manager.handle_level_sign(
                    #     result.get("x", 0), result.get("y", 0), result.get("text", "")
                    # )

            # Handle level_chest
            elif packet_type == "level_chest":
                if hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Calling level_manager.handle_level_chest"
                    )
                    self.client_context.level_manager.handle_level_chest(
                        result.get("x", 0),
                        result.get("y", 0),
                        result.get("item", 0),
                        result.get("sign_text", ""),
                    )

            # Handle level_link
            elif packet_type == "level_link":
                if hasattr(self.client_context, "level_manager"):
                    self.logger.debug(
                        f"[DISPATCH] Calling level_manager.handle_level_link"
                    )
                    self.client_context.level_manager.handle_level_link(result)

            # Handle file packets
            elif packet_type == "file":
                filename = result.get("filename")
                data = result.get("data")
                if filename and data:
                    self.logger.debug(
                        f"[DISPATCH] Emitting FILE_RECEIVED event for '{filename}' ({len(data)} bytes)"
                    )
                    # Emit FILE_RECEIVED event for managers to handle
                    try:
                        if hasattr(self.client_context, "events"):
                            self.client_context.events.emit(EventType.FILE_RECEIVED, {'data': None, 'filename': filename, 'file_data': data})
                            self.logger.debug("[DISPATCH] FILE_RECEIVED event emitted via client.events")
                        elif hasattr(self.client_context, "emit"):
                            self.client_context.emit(EventType.FILE_RECEIVED, {'data': None, 'filename': filename, 'file_data': data})
                            self.logger.debug("[DISPATCH] FILE_RECEIVED event emitted via client.emit")
                        else:
                            self.logger.error("[DISPATCH] No event emission method available!")
                    except Exception as e:
                        self.logger.error(f"[DISPATCH] Exception during FILE_RECEIVED event emission: {e}", exc_info=True)

            # Handle large file start
            elif packet_type == "large_file_start":
                filename = result.get("filename")
                initial_bytes = result.get("initial_bytes", 0)
                if filename:
                    self.logger.debug(f"[DISPATCH] Large file start: {filename} ({initial_bytes} initial bytes)")
                    try:
                        if hasattr(self.client_context, "events"):
                            # For now, emit as FILE_RECEIVED with special type marker
                            self.client_context.events.emit(EventType.FILE_RECEIVED, {'filename': filename, 'file_data': b'', 'large_file_start': True, 'initial_bytes': initial_bytes})
                            self.logger.debug("[DISPATCH] Large file start event emitted")
                    except Exception as e:
                        self.logger.error(f"[DISPATCH] Exception during large file start event: {e}")

            # Handle large file end
            elif packet_type == "large_file_end":
                filename = result.get("filename")
                if filename:
                    self.logger.debug(f"[DISPATCH] Large file end: {filename}")
                    try:
                        if hasattr(self.client_context, "events"):
                            # For now, emit as FILE_RECEIVED with special type marker
                            self.client_context.events.emit(EventType.FILE_RECEIVED, {'filename': filename, 'file_data': b'', 'large_file_end': True})
                            self.logger.debug("[DISPATCH] Large file end event emitted")
                    except Exception as e:
                        self.logger.error(f"[DISPATCH] Exception during large file end event: {e}")

            # Handle file send failed
            elif packet_type == "file_send_failed":
                filename = result.get("filename")
                if filename:
                    self.logger.debug(f"[DISPATCH] File send failed: {filename}")
                    try:
                        if hasattr(self.client_context, "events"):
                            self.client_context.events.emit(EventType.FILE_REQUEST_FAILED, {'filename': filename, 'reason': "server_send_failed"})
                            self.logger.debug("[DISPATCH] FILE_REQUEST_FAILED event emitted")
                    except Exception as e:
                        self.logger.error(f"[DISPATCH] Exception during file send failed event: {e}")

            # Add more packet type dispatchers as needed
            else:
                self.logger.debug(
                    f"[DISPATCH] No dispatcher for packet type: {packet_type}"
                )

        except Exception as e:
            self.logger.error(f"Error dispatching packet result {packet_type}: {e}")
            import traceback

            self.logger.debug(f"Dispatch traceback: {traceback.format_exc()}")

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error handling statistics"""
        if self.error_handler:
            return self.error_handler.get_error_statistics()
        return {}
