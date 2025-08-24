#!/usr/bin/env python3
"""
Incoming Packet Registry with Auto-Discovery

This module provides a registry for all incoming (server-to-player) packets.
It maintains compatibility with the existing PACKET_REGISTRY while providing
a cleaner organization structure.
"""

import os
import importlib
import importlib.util
import logging
from typing import Dict, Optional, List, Any
from ..base import PacketStructure

logger = logging.getLogger(__name__)


class IncomingPacketRegistry:
    """Registry for incoming (server-to-player) packet structures"""
    
    def __init__(self):
        self.structures: Dict[int, PacketStructure] = {}
        self._discovered = False
    
    def register(self, structure: PacketStructure) -> None:
        """Register a packet structure"""
        if structure.packet_id in self.structures:
            existing = self.structures[structure.packet_id]
            logger.warning(
                f"Duplicate packet ID {structure.packet_id} in incoming context: "
                f"{structure.name} conflicts with {existing.name}"
            )
        self.structures[structure.packet_id] = structure
    
    def get_structure(self, packet_id: int) -> Optional[PacketStructure]:
        """Get packet structure by ID"""
        if not self._discovered:
            self._discover_packets()
        return self.structures.get(packet_id)
    
    def get_all_structures(self) -> Dict[int, PacketStructure]:
        """Get all registered structures"""
        if not self._discovered:
            self._discover_packets()
        return self.structures.copy()
    
    def _discover_packets(self) -> None:
        """Auto-discover packet definitions from incoming directory"""
        if self._discovered:
            return
            
        self._discovered = True
        incoming_dir = os.path.dirname(__file__)
        
        # Walk through all subdirectories
        for root, dirs, files in os.walk(incoming_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if file.endswith('.py') and file != '__init__.py':
                    self._load_packet_file(os.path.join(root, file))
    
    def _load_packet_file(self, filepath: str) -> None:
        """Load packet structures from a single file"""
        try:
            # Get module name relative to packets directory
            rel_path = os.path.relpath(filepath, os.path.dirname(os.path.dirname(__file__)))
            module_path = rel_path.replace(os.sep, '.').replace('.py', '')
            full_module_name = f"pyreborn.packets.{module_path}"
            
            # Load the module
            spec = importlib.util.spec_from_file_location(full_module_name, filepath)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Look for PacketStructure instances
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, PacketStructure):
                        self.register(attr)
                        logger.debug(f"Registered incoming packet: {attr.name} (ID: {attr.packet_id})")
                        
        except Exception as e:
            logger.error(f"Failed to load packet file {filepath}: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics"""
        if not self._discovered:
            self._discover_packets()
            
        return {
            'total_incoming_packets': len(self.structures),
            'packet_ids': sorted(self.structures.keys()),
        }


# Global incoming packet registry instance
INCOMING_PACKET_REGISTRY = IncomingPacketRegistry()


# Compatibility function for gradual migration
def get_incoming_packet_structure(packet_id: int) -> Optional[PacketStructure]:
    """Get incoming packet structure with fallback to old registry"""
    # First try the new incoming registry
    structure = INCOMING_PACKET_REGISTRY.get_structure(packet_id)
    
    if not structure:
        # Fall back to the old PACKET_REGISTRY for compatibility
        try:
            from .. import PACKET_REGISTRY
            structure = PACKET_REGISTRY.get_structure(packet_id)
            if structure:
                logger.debug(f"Packet {packet_id} found in old registry (migration pending)")
        except ImportError:
            pass
    
    return structure