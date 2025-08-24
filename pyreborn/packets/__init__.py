#!/usr/bin/env python3
"""
Packet Registry with Auto-Discovery

This module automatically discovers and loads all packet definitions from
the organized file structure, providing a unified PacketRegistry interface.
"""

import os
import importlib
import logging
from typing import Dict, Optional, List
from .base import PacketStructure, PacketCategory

logger = logging.getLogger(__name__)


class PacketRegistry:
    """Registry of all known packet structures with auto-discovery and context support"""
    
    def __init__(self):
        # Context-aware storage: {context: {packet_id: structure}}
        self.structures: Dict[str, Dict[int, PacketStructure]] = {
            "client": {},
            "rc": {}
        }
        # Legacy flat access for backward compatibility
        self._flat_structures: Dict[int, PacketStructure] = {}
        
        # Try auto-discovery with better error handling
        try:
            self._auto_discover_packets()
        except Exception as e:
            logger.warning(f"Auto-discovery failed: {e}")
            # Fall back to manual test packets
            self._manual_test_packets()
    
    def _auto_discover_packets(self):
        """Automatically discover and load all packet definitions"""
        packets_dir = os.path.dirname(__file__)
        logger.debug(f"PacketRegistry auto-discovery starting in: {packets_dir}")
        
        # Categories to scan (now all in incoming directory)
        # First scan incoming directory for server-to-client packets
        incoming_path = os.path.join(packets_dir, 'incoming')
        if os.path.exists(incoming_path):
            incoming_categories = os.listdir(incoming_path)
            for category in incoming_categories:
                if os.path.isdir(os.path.join(incoming_path, category)) and category != '__pycache__':
                    logger.debug(f"Loading incoming category: {category}")
                    self._load_category(f'incoming.{category}', packets_dir)
    
    def _load_category(self, category: str, packets_dir: str):
        """Load all packets from a specific category directory"""
        # Handle nested paths like 'incoming.core'
        category_parts = category.split('.')
        category_path = os.path.join(packets_dir, *category_parts)
        logger.debug(f"Checking category path: {category_path}")
        
        if not os.path.exists(category_path):
            logger.warning(f"Category directory not found: {category}")
            return
        
        # Find all Python files in the category
        files = os.listdir(category_path)
        logger.debug(f"Files in {category}: {files}")
        for filename in files:
            if filename.endswith('.py') and filename != '__init__.py':
                module_name = filename[:-3]  # Remove .py extension
                logger.debug(f"Loading packet module: {category}.{module_name}")
                self._load_packet_module(category, module_name)
    
    def _load_packet_module(self, category: str, module_name: str):
        """Load a specific packet module and extract packet definitions"""
        try:
            # Temporarily add the packets directory to sys.modules to help with relative imports
            import sys
            packets_module_name = "pyreborn.packets"
            
            # Make sure the base module is available
            base_module_name = f"{packets_module_name}.base"
            if base_module_name not in sys.modules:
                from . import base
                sys.modules[base_module_name] = base
            
            # Import the module using the proper package path
            # Handle dots in category names (e.g., "incoming.core" -> "incoming/core")
            category_path_parts = category.split('.')
            full_module_path = f"{packets_module_name}.{'.'.join(category_path_parts)}.{module_name}"
            module = importlib.import_module(full_module_path)
            
            # Look for PacketStructure objects in the module
            structures_found = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, PacketStructure):
                    # Determine context - RC packets are in rc/ directory
                    context = attr.context
                    if category == "rc" and context == "client":
                        # Auto-tag RC packets if not already tagged
                        context = "rc"
                    
                    # Add to context-aware registry
                    if context not in self.structures:
                        self.structures[context] = {}
                    
                    if attr.packet_id in self.structures[context]:
                        # Only warn about duplicates within same context
                        logger.warning(f"Duplicate packet ID {attr.packet_id} in {context} context: {attr.name} conflicts with {self.structures[context][attr.packet_id].name}")
                    else:
                        self.structures[context][attr.packet_id] = attr
                        # Also add to flat structure for backward compatibility (client context takes precedence)
                        if context == "client" or attr.packet_id not in self._flat_structures:
                            self._flat_structures[attr.packet_id] = attr
                        structures_found += 1
            
            if structures_found > 0:
                logger.debug(f"Loaded {structures_found} packet(s) from {category}.{module_name}")
            else:
                logger.debug(f"No packet structures found in {category}.{module_name}")
            
        except ImportError as e:
            if "LoginPacket" in str(e):
                logger.error(f"Failed to import {category}.{module_name}: circular import issue with LoginPacket")
            else:
                logger.error(f"Failed to import {category}.{module_name}: {e}")
        except Exception as e:
            logger.error(f"Error loading packets from {category}.{module_name}: {e}")
    
    def get_structure(self, packet_id: int, context: str = "client") -> Optional[PacketStructure]:
        """Get packet structure by ID and context
        
        Args:
            packet_id: The packet ID to look up
            context: The context ("client" or "rc"), defaults to "client"
            
        Returns:
            PacketStructure if found, None otherwise
        """
        # Try context-aware lookup first
        if context in self.structures and packet_id in self.structures[context]:
            return self.structures[context][packet_id]
        
        # Fall back to flat structure for backward compatibility
        return self._flat_structures.get(packet_id)
    
    def has_structure(self, packet_id: int, context: str = "client") -> bool:
        """Check if a packet structure exists
        
        Args:
            packet_id: The packet ID to check
            context: The context ("client" or "rc"), defaults to "client"
        """
        if context in self.structures and packet_id in self.structures[context]:
            return True
        # Also check flat structure for backward compatibility
        return packet_id in self._flat_structures
    
    def get_all_structures(self) -> Dict[int, PacketStructure]:
        """Get all packet structures (flat view for backward compatibility)"""
        return self._flat_structures.copy()
    
    def get_structures_by_context(self, context: str = "client") -> Dict[int, PacketStructure]:
        """Get all packet structures for a specific context"""
        return self.structures.get(context, {}).copy()
    
    def get_structures_by_category(self) -> Dict[str, List[PacketStructure]]:
        """Get packet structures organized by category"""
        categories = {}
        
        # Use flat structures for backward compatibility
        for structure in self._flat_structures.values():
            # Determine category from packet ID ranges (simplified)
            if structure.packet_id <= 20:
                category = 'core'
            elif structure.packet_id in [17, 18, 19, 49]:
                category = 'movement'
            elif structure.packet_id in [11, 12, 14, 35, 36, 40]:
                category = 'combat'
            elif structure.packet_id in [2, 3, 24, 33, 34]:
                category = 'npcs'
            elif structure.packet_id in [68, 69, 84, 100, 101, 102]:
                category = 'files'
            elif structure.packet_id in [25, 41, 47, 56, 57, 58, 82, 92]:
                category = 'system'
            elif structure.packet_id >= 170:
                category = 'ui'
            else:
                category = 'unknown'
            
            if category not in categories:
                categories[category] = []
            categories[category].append(structure)
        
        return categories
    
    def validate_registry(self) -> List[str]:
        """Validate the registry and return any issues found"""
        issues = []
        
        # Validate each context separately
        for context, context_structures in self.structures.items():
            seen_ids = set()
            for packet_id, structure in context_structures.items():
                if packet_id != structure.packet_id:
                    issues.append(f"[{context}] Packet ID mismatch: registry key {packet_id} != structure.packet_id {structure.packet_id}")
                
                if packet_id in seen_ids:
                    issues.append(f"[{context}] Duplicate packet ID: {packet_id}")
                seen_ids.add(packet_id)
        
        # Check for missing critical packets in client context
        critical_packets = [0, 6, 9, 100, 101, 102]  # Level board, name, props, rawdata, boardpacket, file
        for packet_id in critical_packets:
            if packet_id not in self.structures.get("client", {}):
                issues.append(f"Missing critical packet in client context: {packet_id}")
        
        return issues
    
    def get_statistics(self) -> Dict[str, int]:
        """Get registry statistics"""
        categories = self.get_structures_by_category()
        
        # Count total fields across all packets
        total_fields = sum(
            len(packet.fields) for packet in self._flat_structures.values()
        )
        
        stats = {
            'total_packets': len(self._flat_structures),
            'total_fields': total_fields,
            'client_packets': len(self.structures.get("client", {})),
            'rc_packets': len(self.structures.get("rc", {})),
            'categories': len(categories)
        }
        
        for category, packets in categories.items():
            stats[f'{category}_packets'] = len(packets)
        
        return stats
    
    def _manual_test_packets(self):
        """Manually add test packets for initial testing"""
        from .base import PacketStructure, PacketField, PacketFieldType
        
        # Manually create a simple test packet
        test_packet = PacketStructure(
            packet_id=0,
            name="PLO_LEVELBOARD",
            fields=[
                PacketField("compressed_length", PacketFieldType.GSHORT, description="Compressed data length"),
                PacketField("compressed_data", PacketFieldType.VARIABLE_DATA, description="Compressed level board data")
            ],
            description="Level board tile data (test version)",
            variable_length=True
        )
        
        # Add to client context and flat structure
        self.structures["client"][0] = test_packet
        self._flat_structures[0] = test_packet
        logger.debug(f"Manually added test packet: {test_packet.name}")


# Create the default registry instance
PACKET_REGISTRY = PacketRegistry()

# Validate the registry on import (debug level only since timing issues exist)
validation_issues = PACKET_REGISTRY.validate_registry()
if validation_issues:
    for issue in validation_issues:
        logger.debug(f"Packet registry validation: {issue}")

# Log statistics
stats = PACKET_REGISTRY.get_statistics()
logger.info(f"Packet registry loaded: {stats['total_packets']} packets across {stats['categories']} categories")


# TEMPORARY COMPATIBILITY: Import existing packet classes for backward compatibility
# Re-enabled after successful new registry testing

# Legacy packet class imports - removed packet_types dependency
# The new packet registry system handles packet structures automatically
logger.debug("Using new packet registry system - legacy packet_types import removed")

# Create stub classes for missing client-to-server packets to avoid import errors
class RebornPacket:
    """Stub for RebornPacket base class to avoid import errors during transition"""
    pass

class PacketBuilder:
    """Stub for PacketBuilder to avoid import errors during transition"""
    pass

class PacketReader:
    """Stub for PacketReader to avoid import errors during transition"""
    pass

# Import LoginPacket from its new location for backward compatibility
from .system.login import LoginPacket

class WeaponAddPacket:
    """Stub for WeaponAddPacket to avoid import errors during transition"""
    pass

class ShootPacket:
    """Stub for ShootPacket to avoid import errors during transition"""
    pass

class Shoot2Packet:
    """Stub for Shoot2Packet to avoid import errors during transition"""
    pass

class WantFilePacket:
    """Stub for WantFilePacket to avoid import errors during transition"""
    pass

# Add the missing packet from the error message
try:
    from ..packet_types.main import FirespyPacket as FireSpyPacket
except ImportError:
    class FireSpyPacket:
        """Stub for FireSpyPacket to avoid import errors during transition"""
        pass

class RequestUpdateBoardPacket:
    """Stub for RequestUpdateBoardPacket to avoid import errors during transition"""
    def __init__(self, level, mod_time, x, y, width, height):
        self.level = level
        self.mod_time = mod_time
        self.x = x
        self.y = y
        self.width = width
        self.height = height

class RequestTextPacket:
    """Stub for RequestTextPacket to avoid import errors during transition"""
    pass

class SendTextPacket:
    """Stub for SendTextPacket to avoid import errors during transition"""
    pass

logger.debug("Added stub classes for client-to-server packets")