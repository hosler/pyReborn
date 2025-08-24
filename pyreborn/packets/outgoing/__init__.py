#!/usr/bin/env python3
"""
Outgoing Packet Registry with Auto-Discovery

This module provides a registry-driven system for constructing and sending
packets to the server, dramatically simplifying the packet building process.
"""

import os
import importlib
import importlib.util
import logging
from typing import Dict, Optional, List, Any, Union
from ..base import PacketFieldType

logger = logging.getLogger(__name__)


class OutgoingPacketField:
    """Field definition for outgoing packets"""
    
    def __init__(self, name: str, field_type: PacketFieldType, 
                 description: str = "", default: Any = None, 
                 encoder: Optional[callable] = None):
        self.name = name
        self.field_type = field_type
        self.description = description
        self.default = default
        self.encoder = encoder  # Custom encoding function
    
    def __repr__(self):
        return f"OutgoingPacketField({self.name}, {self.field_type})"


class OutgoingPacketStructure:
    """Structure definition for outgoing packets"""
    
    def __init__(self, packet_id: int, name: str, fields: List[OutgoingPacketField],
                 description: str = "", variable_length: bool = False,
                 builder_class: Optional[type] = None):
        self.packet_id = packet_id
        self.name = name
        self.fields = fields
        self.description = description
        self.variable_length = variable_length
        self.builder_class = builder_class  # Custom packet builder class
        
        # Create field lookup for easy access
        self.field_map = {field.name: field for field in fields}
    
    def create_packet(self, **kwargs) -> 'OutgoingPacket':
        """Create a packet instance with specified field values"""
        return OutgoingPacket(self, **kwargs)
    
    def __repr__(self):
        return f"OutgoingPacketStructure({self.name}, {len(self.fields)} fields)"


class OutgoingPacket:
    """Instance of an outgoing packet with field values"""
    
    def __init__(self, structure: OutgoingPacketStructure, **field_values):
        self.structure = structure
        self.field_values = {}
        
        # Set field values with defaults
        for field in structure.fields:
            if field.name in field_values:
                self.field_values[field.name] = field_values[field.name]
            elif field.default is not None:
                self.field_values[field.name] = field.default
            else:
                # Field is required
                raise ValueError(f"Required field '{field.name}' not provided for packet {structure.name}")
    
    def set_field(self, field_name: str, value: Any) -> 'OutgoingPacket':
        """Set a field value (fluent interface)"""
        if field_name not in self.structure.field_map:
            raise ValueError(f"Unknown field '{field_name}' for packet {self.structure.name}")
        self.field_values[field_name] = value
        return self
    
    def get_field(self, field_name: str) -> Any:
        """Get a field value"""
        return self.field_values.get(field_name)
    
    def to_bytes(self) -> bytes:
        """Convert packet to bytes for sending"""
        if self.structure.builder_class:
            # Use custom builder class
            builder = self.structure.builder_class()
            return builder.build_packet(self)
        else:
            # Use default field-driven building
            return self._build_with_fields()
    
    def _build_with_fields(self) -> bytes:
        """Build packet using field definitions"""
        from pyreborn.protocol.enums import PlayerToServer
        
        # Simple packet builder for outgoing packets
        data = bytearray()
        
        # Add packet ID
        if hasattr(PlayerToServer, f"PLI_{self.structure.name.split('_', 1)[1]}"):
            packet_enum = getattr(PlayerToServer, f"PLI_{self.structure.name.split('_', 1)[1]}")
            data.append(int(packet_enum) + 32)  # Reborn protocol adds 32
        else:
            data.append(self.structure.packet_id + 32)
        
        # Add fields based on their types
        for field in self.structure.fields:
            value = self.field_values.get(field.name)
            if value is None:
                continue
                
            # Apply custom encoder if available
            if field.encoder:
                value = field.encoder(value)
            
            # Encode based on field type - simple implementation
            if field.field_type == PacketFieldType.GCHAR:
                data.append(min(223, int(value)) + 32)
            elif field.field_type == PacketFieldType.GSHORT:
                # Simplified GSHORT encoding
                encoded = int(value) + 0x1020
                b1 = (encoded >> 7) & 0xFF
                b2 = encoded & 0x7F
                data.extend([b1, b2])
            elif field.field_type == PacketFieldType.VARIABLE_DATA:
                if isinstance(value, str):
                    # Reborn string (newline terminated)
                    data.extend(value.encode('ascii', errors='replace'))
                    data.append(ord('\n'))
                else:
                    data.extend(value)
            elif field.field_type == PacketFieldType.BYTE:
                data.append(min(223, int(value)) + 32)
        
        # End packet if needed (add newline terminator)
        if not self.structure.variable_length:
            data.append(ord('\n'))
        
        return bytes(data)
    
    def __repr__(self):
        return f"OutgoingPacket({self.structure.name}, {len(self.field_values)} fields)"


class OutgoingPacketRegistry:
    """Registry of all outgoing packet structures with auto-discovery"""
    
    def __init__(self):
        self.structures: Dict[int, OutgoingPacketStructure] = {}
        self.name_to_structure: Dict[str, OutgoingPacketStructure] = {}
        
        # Try auto-discovery
        try:
            self._auto_discover_packets()
        except Exception as e:
            logger.warning(f"Outgoing packet auto-discovery failed: {e}")
    
    def _auto_discover_packets(self):
        """Automatically discover and load all outgoing packet definitions"""
        packets_dir = os.path.dirname(__file__)
        logger.debug(f"OutgoingPacketRegistry auto-discovery starting in: {packets_dir}")
        
        # Categories to scan
        categories = ['core', 'communication', 'combat', 'items', 'npcs', 'system', 'movement']
        
        for category in categories:
            logger.debug(f"Loading outgoing category: {category}")
            self._load_category(category, packets_dir)
    
    def _load_category(self, category: str, packets_dir: str):
        """Load all outgoing packets from a specific category directory"""
        category_path = os.path.join(packets_dir, category)
        
        if not os.path.exists(category_path):
            logger.debug(f"Outgoing category directory not found: {category}")
            return
        
        # Find all Python files in the category
        for filename in os.listdir(category_path):
            if filename.endswith('.py') and filename != '__init__.py':
                module_name = filename[:-3]  # Remove .py extension
                logger.debug(f"Loading outgoing packet module: {category}.{module_name}")
                self._load_packet_module(category, module_name)
    
    def _load_packet_module(self, category: str, module_name: str):
        """Load a specific outgoing packet module and extract packet definitions"""
        try:
            # Import the module using the proper package path
            full_module_path = f"pyreborn.packets.outgoing.{category}.{module_name}"
            module = importlib.import_module(full_module_path)
            
            # Look for OutgoingPacketStructure objects in the module
            structures_found = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, OutgoingPacketStructure):
                    # Check for duplicates
                    if attr.packet_id in self.structures:
                        logger.warning(f"Duplicate outgoing packet ID {attr.packet_id}: {attr.name} conflicts with {self.structures[attr.packet_id].name}")
                    else:
                        self.structures[attr.packet_id] = attr
                        self.name_to_structure[attr.name] = attr
                        structures_found += 1
            
            if structures_found > 0:
                logger.debug(f"Loaded {structures_found} outgoing packet(s) from {category}.{module_name}")
            
        except ImportError as e:
            logger.error(f"Failed to import outgoing {category}.{module_name}: {e}")
        except Exception as e:
            logger.error(f"Error loading outgoing packets from {category}.{module_name}: {e}")
    
    def get_structure(self, packet_id: int) -> Optional[OutgoingPacketStructure]:
        """Get outgoing packet structure by ID"""
        return self.structures.get(packet_id)
    
    def get_structure_by_name(self, name: str) -> Optional[OutgoingPacketStructure]:
        """Get outgoing packet structure by name"""
        return self.name_to_structure.get(name)
    
    def create_packet(self, packet_id_or_name: Union[int, str], **kwargs) -> Optional[OutgoingPacket]:
        """Create an outgoing packet by ID or name"""
        if isinstance(packet_id_or_name, str):
            structure = self.get_structure_by_name(packet_id_or_name)
        else:
            structure = self.get_structure(packet_id_or_name)
        
        if structure:
            return structure.create_packet(**kwargs)
        return None
    
    def get_all_structures(self) -> Dict[int, OutgoingPacketStructure]:
        """Get all outgoing packet structures"""
        return self.structures.copy()
    
    def get_statistics(self) -> Dict[str, int]:
        """Get registry statistics"""
        return {
            'total_outgoing_packets': len(self.structures),
            'categories': len(set(struct.name.split('_')[0] for struct in self.structures.values())),
        }


# Create the default outgoing registry instance
OUTGOING_PACKET_REGISTRY = OutgoingPacketRegistry()

# Log statistics
stats = OUTGOING_PACKET_REGISTRY.get_statistics()
logger.info(f"Outgoing packet registry loaded: {stats['total_outgoing_packets']} packets")