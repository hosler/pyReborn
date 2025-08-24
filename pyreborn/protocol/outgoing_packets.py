"""
Simplified Outgoing Packet API

This module provides a high-level, user-friendly API for creating and sending packets
to the server using the new registry-driven system. It dramatically simplifies packet
construction compared to the old manual PacketBuilder approach.
"""

import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from ..protocol.packets.outgoing import OUTGOING_PACKET_REGISTRY, OutgoingPacket
from ..protocol.enums import PlayerProp

logger = logging.getLogger(__name__)


class OutgoingPacketAPI:
    """High-level API for creating and sending packets using the registry system"""
    
    def __init__(self, client=None):
        """Initialize the API with optional client for direct sending
        
        Args:
            client: Optional ModularRebornClient instance for direct packet sending
        """
        self.client = client
        self.registry = OUTGOING_PACKET_REGISTRY
    
    # === Packet Discovery and Information ===
    
    def get_packet_info(self, packet_id_or_name: Union[int, str]) -> Optional[Dict[str, Any]]:
        """Get information about a packet
        
        Args:
            packet_id_or_name: Packet ID or name (e.g., 6 or "PLI_TOALL")
            
        Returns:
            Dict with packet information or None if not found
        """
        if isinstance(packet_id_or_name, str):
            structure = self.registry.get_structure_by_name(packet_id_or_name)
        else:
            structure = self.registry.get_structure(packet_id_or_name)
        
        if not structure:
            return None
            
        return {
            'packet_id': structure.packet_id,
            'name': structure.name,
            'description': structure.description,
            'fields': [
                {
                    'name': field.name,
                    'type': field.field_type,
                    'description': field.description,
                    'default': field.default
                }
                for field in structure.fields
            ],
            'variable_length': structure.variable_length
        }
    
    def find_packets_by_name(self, name_pattern: str) -> List[Dict[str, Any]]:
        """Find packets by name pattern
        
        Args:
            name_pattern: Pattern to search for (case-insensitive)
            
        Returns:
            List of packet information dictionaries
        """
        results = []
        pattern = name_pattern.lower()
        
        for structure in self.registry.get_all_structures().values():
            if pattern in structure.name.lower() or pattern in structure.description.lower():
                results.append(self.get_packet_info(structure.packet_id))
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get outgoing packet registry statistics"""
        stats = self.registry.get_statistics()
        
        # Add more detailed statistics
        structures = self.registry.get_all_structures()
        categories = {}
        
        for structure in structures.values():
            # Extract category from packet name
            if '_' in structure.name:
                category = structure.name.split('_')[1].split('_')[0].lower()
            else:
                category = 'unknown'
                
            if category not in categories:
                categories[category] = 0
            categories[category] += 1
        
        stats['categories_detail'] = categories
        return stats
    
    # === Easy Packet Creation ===
    
    def create_packet(self, packet_id_or_name: Union[int, str], **kwargs) -> Optional[OutgoingPacket]:
        """Create a packet with field values
        
        Args:
            packet_id_or_name: Packet ID or name
            **kwargs: Field values for the packet
            
        Returns:
            OutgoingPacket instance or None if creation failed
        """
        try:
            return self.registry.create_packet(packet_id_or_name, **kwargs)
        except Exception as e:
            logger.error(f"Failed to create packet {packet_id_or_name}: {e}")
            return None
    
    def send_packet(self, packet: OutgoingPacket) -> bool:
        """Send a packet using the configured client
        
        Args:
            packet: OutgoingPacket to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.client:
            logger.error("No client configured for sending packets")
            return False
            
        try:
            packet_bytes = packet.to_bytes()
            
            # Emit event with structured packet data for debugging/inspection
            if hasattr(self.client, 'events') and self.client.events:
                from pyreborn.core.events import EventType
                
                # Prepare structured data for the event
                structured_data = {
                    'packet_id': packet.structure.packet_id,
                    'packet_name': packet.structure.name,
                    'packet_description': packet.structure.description,
                    'fields': {}
                }
                
                # Add field values with special handling for PlayerProps
                for field in packet.structure.fields:
                    value = packet.get_field(field.name)
                    if value is not None:
                        # Special handling for PLI_PLAYERPROPS properties field
                        if packet.structure.name == 'PLI_PLAYERPROPS' and field.name == 'properties':
                            # Convert property list to readable format
                            from pyreborn.protocol.enums import PlayerProp
                            readable_props = []
                            if isinstance(value, list):
                                for prop_item in value:
                                    if isinstance(prop_item, (list, tuple)) and len(prop_item) >= 2:
                                        prop_id, prop_value = prop_item[0], prop_item[1]
                                        try:
                                            # Convert property ID to name
                                            if isinstance(prop_id, PlayerProp):
                                                prop_name = prop_id.name.replace('PLPROP_', '').lower()
                                            elif isinstance(prop_id, int):
                                                prop_enum = PlayerProp(prop_id)
                                                prop_name = prop_enum.name.replace('PLPROP_', '').lower()
                                            else:
                                                prop_name = str(prop_id)
                                        except:
                                            prop_name = f"property_{prop_id}"
                                        
                                        readable_props.append({
                                            'id': prop_id.value if isinstance(prop_id, PlayerProp) else prop_id,
                                            'name': prop_name,
                                            'value': prop_value
                                        })
                            structured_data['fields']['properties'] = readable_props
                        else:
                            structured_data['fields'][field.name] = value
                
                # Emit the event
                self.client.events.emit(EventType.OUTGOING_PACKET_STRUCTURED, {
                    'packet_id': packet.structure.packet_id,
                    'packet_name': packet.structure.name,
                    'packet_data': packet_bytes,
                    'structured_data': structured_data,
                    'size': len(packet_bytes)
                })
            
            self.client.send_packet(packet_bytes)
            logger.debug(f"Sent packet {packet.structure.name} ({len(packet_bytes)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to send packet {packet.structure.name}: {e}")
            return False
    
    def create_and_send(self, packet_id_or_name: Union[int, str], **kwargs) -> bool:
        """Create and send a packet in one operation
        
        Args:
            packet_id_or_name: Packet ID or name
            **kwargs: Field values for the packet
            
        Returns:
            True if created and sent successfully, False otherwise
        """
        packet = self.create_packet(packet_id_or_name, **kwargs)
        if packet:
            return self.send_packet(packet)
        return False
    
    # === Convenient Helper Methods ===
    
    def chat(self, message: str) -> bool:
        """Send a chat message to all players
        
        Args:
            message: Chat message to send
            
        Returns:
            True if sent successfully
        """
        return self.create_and_send('PLI_TOALL', message=message)
    
    def drop_bomb(self, x: float, y: float, power: int = 1, timer: int = 55) -> bool:
        """Drop a bomb at specified position
        
        Args:
            x: X coordinate
            y: Y coordinate  
            power: Bomb power (1-10)
            timer: Bomb timer in ticks
            
        Returns:
            True if sent successfully
        """
        return self.create_and_send('PLI_BOMBADD', x=x, y=y, power=power, timer=timer)
    
    def request_file(self, filename: str) -> bool:
        """Request a file from the server
        
        Args:
            filename: Name of file to request
            
        Returns:
            True if sent successfully
        """
        return self.create_and_send('PLI_WANTFILE', filename=filename)
    
    def set_player_properties(self, **props) -> bool:
        """Set player properties using convenient keyword arguments
        
        Args:
            **props: Player properties (x, y, nickname, etc.)
            
        Returns:
            True if sent successfully
            
        Example:
            api.set_player_properties(x=30.5, y=25.0, nickname="TestPlayer")
        """
        # Try to get PlayerProps helper if available
        try:
            from ..protocol.packets.outgoing.core.player_props import PlayerPropsPacketHelper
            packet = PlayerPropsPacketHelper.create_with_properties(**props)
            return self.send_packet(packet)
        except ImportError:
            logger.error("PlayerProps packet not available")
            return False
    
    def add_player_property(self, packet: OutgoingPacket, prop: Union[PlayerProp, int], value: Any) -> OutgoingPacket:
        """Add a property to a PlayerProps packet (fluent interface)
        
        Args:
            packet: Existing PlayerProps packet
            prop: Property to add
            value: Property value
            
        Returns:
            The packet (for chaining)
        """
        try:
            from ..protocol.packets.outgoing.core.player_props import PlayerPropsPacketHelper
            return PlayerPropsPacketHelper.add_property(packet, prop, value)
        except ImportError:
            logger.error("PlayerProps packet not available")
            return packet
    
    # === Debugging and Development ===
    
    def list_all_packets(self) -> None:
        """Print all available outgoing packets"""
        structures = self.registry.get_all_structures()
        
        print(f"📦 Available Outgoing Packets ({len(structures)}):")
        print("-" * 50)
        
        for packet_id in sorted(structures.keys()):
            structure = structures[packet_id]
            print(f"  {packet_id:3d}: {structure.name}")
            print(f"       {structure.description}")
            print(f"       Fields: {', '.join(field.name for field in structure.fields)}")
            print()
    
    def inspect_packet(self, packet_id_or_name: Union[int, str]) -> None:
        """Print detailed information about a packet"""
        info = self.get_packet_info(packet_id_or_name)
        
        if not info:
            print(f"❌ Packet not found: {packet_id_or_name}")
            return
        
        print(f"📋 Packet: {info['name']} (ID: {info['packet_id']})")
        print(f"📄 Description: {info['description']}")
        print(f"🔄 Variable Length: {info['variable_length']}")
        print(f"📝 Fields ({len(info['fields'])}):")
        
        for field in info['fields']:
            default_str = f" (default: {field['default']})" if field['default'] is not None else ""
            print(f"  - {field['name']}: {field['type']}{default_str}")
            if field['description']:
                print(f"    {field['description']}")
        print()


# Convenience function for creating API instance  
def create_outgoing_api(client=None) -> OutgoingPacketAPI:
    """Create an OutgoingPacketAPI instance
    
    Args:
        client: Optional ModularRebornClient for direct sending
        
    Returns:
        OutgoingPacketAPI instance
    """
    return OutgoingPacketAPI(client)


# Example usage function
def example_usage():
    """Example of how to use the OutgoingPacketAPI"""
    print("🎯 Outgoing Packet API Example Usage")
    print("=" * 40)
    
    # Create API instance
    api = OutgoingPacketAPI()
    
    # Get statistics
    stats = api.get_statistics()
    print(f"📊 Registry loaded: {stats['total_outgoing_packets']} packets")
    
    # List all packets
    api.list_all_packets()
    
    # Inspect a specific packet
    api.inspect_packet('PLI_TOALL')
    
    # Create packets (without sending)
    print("🛠️  Creating example packets:")
    
    chat_packet = api.create_packet('PLI_TOALL', message='Hello world!')
    if chat_packet:
        print(f"✅ Chat packet: {chat_packet}")
    
    bomb_packet = api.create_packet('PLI_BOMBADD', x=30.5, y=25.0, power=3)
    if bomb_packet:
        print(f"✅ Bomb packet: {bomb_packet}")
        
    file_packet = api.create_packet('PLI_WANTFILE', filename='test.nw')
    if file_packet:
        print(f"✅ File request packet: {file_packet}")
    
    print("\n🎉 OutgoingPacketAPI example completed successfully!")


if __name__ == "__main__":
    example_usage()