#!/usr/bin/env python3
"""
Simplified Packet API

This module provides a simple, clean interface for clients to work with
the new file-organized packet registry. It hides the complexity of the 
underlying packet system and provides easy-to-use methods.

Usage:
    from pyreborn.packet_api import PacketAPI
    
    api = PacketAPI()
    
    # Get packet information
    level_board = api.get_packet_info(0)
    print(f"Packet 0: {level_board.name}")
    
    # Check if packet exists
    if api.has_packet(100):
        print("Packet 100 (PLO_RAWDATA) is supported")
    
    # Get packets by category
    core_packets = api.get_packets_by_category('core')
    print(f"Core packets: {[p.name for p in core_packets]}")
"""

from typing import List, Optional, Dict, Any
import sys
import os

# Add the parent directory to the path for imports
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .packets import PACKET_REGISTRY, PacketStructure
except ImportError:
    # Try direct import if we're already in the right path
    from pyreborn.packets import PACKET_REGISTRY, PacketStructure


class PacketInfo:
    """Simple packet information container"""
    
    def __init__(self, structure: PacketStructure):
        self.id = structure.packet_id
        self.packet_id = structure.packet_id  # Add packet_id attribute for compatibility
        self.name = structure.name
        self.description = structure.description
        self.field_count = len(structure.fields)
        self.is_variable_length = structure.variable_length
        self.fields = [
            {
                'name': field.name,
                'type': field.field_type.name,
                'description': field.description
            }
            for field in structure.fields
        ]
    
    def __str__(self):
        return f"{self.name} (ID: {self.id}, Fields: {self.field_count})"
    
    def __repr__(self):
        return f"PacketInfo(id={self.id}, name='{self.name}')"


class PacketAPI:
    """Simplified API for packet registry access"""
    
    def __init__(self):
        self.registry = PACKET_REGISTRY
        self._categories_cache = None
    
    def get_packet_info(self, packet_id: int) -> Optional[PacketInfo]:
        """Get information about a specific packet"""
        structure = self.registry.get_structure(packet_id)
        if structure:
            return PacketInfo(structure)
        return None
    
    def has_packet(self, packet_id: int) -> bool:
        """Check if a packet is supported"""
        return self.registry.has_structure(packet_id)
    
    def get_all_packets(self) -> List[PacketInfo]:
        """Get information about all supported packets"""
        structures = self.registry.get_all_structures()
        return [PacketInfo(structure) for structure in structures.values()]
    
    def get_packets_by_category(self, category: str) -> List[PacketInfo]:
        """Get all packets in a specific category"""
        if self._categories_cache is None:
            self._categories_cache = self.registry.get_structures_by_category()
        
        if category in self._categories_cache:
            return [PacketInfo(structure) for structure in self._categories_cache[category]]
        return []
    
    def get_categories(self) -> List[str]:
        """Get list of all packet categories"""
        if self._categories_cache is None:
            self._categories_cache = self.registry.get_structures_by_category()
        return list(self._categories_cache.keys())
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get packet registry statistics"""
        stats = self.registry.get_statistics()
        
        # Add more useful stats
        all_packets = self.get_all_packets()
        variable_count = sum(1 for p in all_packets if p.is_variable_length)
        fixed_count = len(all_packets) - variable_count
        
        stats.update({
            'variable_length_packets': variable_count,
            'fixed_length_packets': fixed_count,
            'categories': self.get_categories()
        })
        
        return stats
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Alias for get_statistics() for compatibility"""
        return self.get_statistics()
    
    def find_packets_by_name(self, name_pattern: str) -> List[PacketInfo]:
        """Find packets whose names contain the given pattern"""
        all_packets = self.get_all_packets()
        return [p for p in all_packets if name_pattern.upper() in p.name.upper()]
    
    def get_packet_summary(self) -> str:
        """Get a human-readable summary of the packet registry"""
        stats = self.get_statistics()
        categories = self.get_categories()
        
        summary = f"Packet Registry Summary:\n"
        summary += f"  Total packets: {stats['total_packets']}\n"
        summary += f"  Categories: {len(categories)}\n"
        summary += f"  Variable length: {stats['variable_length_packets']}\n"
        summary += f"  Fixed length: {stats['fixed_length_packets']}\n\n"
        
        summary += "Categories:\n"
        for category in sorted(categories):
            packets = self.get_packets_by_category(category)
            summary += f"  {category}: {len(packets)} packets\n"
            for packet in packets[:3]:  # Show first 3
                summary += f"    - {packet.name} ({packet.id})\n"
            if len(packets) > 3:
                summary += f"    ... and {len(packets) - 3} more\n"
        
        return summary


# Create a global instance for easy import
packet_api = PacketAPI()


def get_packet_info(packet_id: int) -> Optional[PacketInfo]:
    """Convenience function to get packet information"""
    return packet_api.get_packet_info(packet_id)


def has_packet(packet_id: int) -> bool:
    """Convenience function to check if packet exists"""
    return packet_api.has_packet(packet_id)


def get_packets_by_category(category: str) -> List[PacketInfo]:
    """Convenience function to get packets by category"""
    return packet_api.get_packets_by_category(category)


def print_packet_summary():
    """Convenience function to print packet summary"""
    print(packet_api.get_packet_summary())


# Example usage functions for testing
def example_usage():
    """Example usage of the PacketAPI"""
    print("🔍 Packet API Example Usage")
    print("=" * 30)
    
    # Basic packet lookup
    board_packet = get_packet_info(0)
    if board_packet:
        print(f"Found: {board_packet}")
        print(f"Description: {board_packet.description}")
        print(f"Fields: {board_packet.field_count}")
    
    # Category browsing
    print(f"\nCore packets:")
    for packet in get_packets_by_category('core'):
        print(f"  - {packet}")
    
    # Statistics
    print(f"\nStatistics:")
    stats = packet_api.get_statistics()
    for key, value in stats.items():
        if key != 'categories':  # Skip the list for cleaner output
            print(f"  {key}: {value}")
    
    # Search functionality
    print(f"\nLevel-related packets:")
    level_packets = packet_api.find_packets_by_name('level')
    for packet in level_packets:
        print(f"  - {packet}")


if __name__ == "__main__":
    example_usage()