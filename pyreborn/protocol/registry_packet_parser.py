#!/usr/bin/env python3
"""
Registry-Based Packet Parser

This is a simplified packet parser that uses the new file-organized packet registry
to automatically parse packets based on their structure definitions.

This replaces the monolithic 2000+ line PacketHandler with a clean, registry-driven approach.
"""

import logging
from typing import Dict, Any, Optional, List
from ..packets import PACKET_REGISTRY
from ..packets.incoming import INCOMING_PACKET_REGISTRY
from ..packets.base import PacketFieldType, PacketStructure

logger = logging.getLogger(__name__)


class RegistryPacketParser:
    """Simplified packet parser using the packet registry"""
    
    def __init__(self):
        # Try incoming registry first, fall back to main registry
        self.registry = INCOMING_PACKET_REGISTRY
        self.fallback_registry = PACKET_REGISTRY
        
        # Import and use the static packet index
        from ..packets.incoming.packet_index import get_packet_module, preload_all_modules
        self.get_packet_module = get_packet_module
        
        # Preload all modules for maximum performance
        preload_all_modules()
    
    def parse_packet(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """Parse a packet using its registry definition"""
        structure = self.registry.get_structure(packet_id)
        if not structure and self.fallback_registry:
            structure = self.fallback_registry.get_structure(packet_id)
        
        if not structure:
            logger.warning(f"Unknown packet ID: {packet_id}")
            return None
        
        try:
            # Get the module that contains this packet
            module = self._get_packet_module(structure.packet_id)
            if module and hasattr(module, 'parse_packet'):
                # Use the packet's own parse_packet function
                return module.parse_packet(data, announced_size)
            else:
                # Only log error if this is not a fallback attempt
                if structure == self.registry.get_structure(packet_id):
                    logger.error(f"Packet {structure.name} ({packet_id}) missing parse_packet() function")
                return None
            
        except Exception as e:
            logger.error(f"Error parsing packet {packet_id} ({structure.name}): {e}")
            return None
    
    def _get_packet_module(self, packet_id: int):
        """Get the module that contains a packet definition"""
        # Use the static index for instant lookup
        return self.get_packet_module(packet_id)
    
    def get_supported_packets(self) -> List[int]:
        """Get list of all supported packet IDs"""
        return sorted(self.registry.get_all_structures().keys())
    
    def get_packet_info(self, packet_id: int) -> Optional[str]:
        """Get information about a packet"""
        structure = self.registry.get_structure(packet_id)
        if structure:
            return f"{structure.name}: {structure.description}"
        return None


# Global parser instance
packet_parser = RegistryPacketParser()


def parse_packet(packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
    """Convenience function to parse a packet"""
    return packet_parser.parse_packet(packet_id, data, announced_size)


def get_supported_packets() -> List[int]:
    """Get list of supported packet IDs"""
    return packet_parser.get_supported_packets()


# Example usage
def example_usage():
    """Demonstrate the simplified packet parser"""
    print("🔍 Registry-Based Packet Parser Example")
    print("=" * 40)
    
    # Show supported packets
    supported = get_supported_packets()
    print(f"Supported packets: {len(supported)}")
    print(f"Packet IDs: {supported[:10]}...")  # Show first 10
    
    # Example: Parse a simple packet (PLO_BOMBDEL)
    print("\nExample: Parsing PLO_BOMBDEL (12)")
    # Create sample data: x=10, y=20 (GCHAR encoded)
    sample_data = bytes([10 + 32, 20 + 32])  # Add 32 for GCHAR encoding
    
    result = parse_packet(12, sample_data)
    if result:
        print(f"Parsed: {result['packet_name']}")
        print(f"Fields: {result['fields']}")
    
    print("\n✅ This parser is much simpler than the 2000+ line PacketHandler!")
    print("✅ All parsing logic is now in the packet files themselves!")


if __name__ == "__main__":
    example_usage()