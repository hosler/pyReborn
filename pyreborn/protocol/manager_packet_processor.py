#!/usr/bin/env python3
"""
Manager-Based Packet Processor

This replaces the monolithic PacketHandler with a clean, manager-based approach
where business logic is delegated to appropriate managers based on packet type.

This uses the new registry-driven packet parsing system and provides a clean
separation of concerns.
"""

import logging
import time
from typing import Dict, Any, Optional, Callable
from ..packets import PACKET_REGISTRY
from .registry_packet_parser import RegistryPacketParser
from .enums import ServerToPlayer
from ..session.events import EventType
# Packet metrics removed for simplicity
def record_packet_metric(packet_id, success, duration=0, packet_name=None, **kwargs):
    pass  # No-op stub - accepts all arguments

logger = logging.getLogger(__name__)


class ManagerPacketProcessor:
    """
    Registry-driven packet processor that delegates business logic to managers.
    
    This replaces the 2,132-line PacketHandler with a clean, modular approach:
    - Uses registry for automatic packet parsing
    - Delegates business logic to appropriate managers
    - Maintains separation of concerns
    - Easy to extend and test
    """
    
    def __init__(self, client):
        self.client = client
        self.parser = RegistryPacketParser()
        
        # Packet processing statistics
        self.stats = {
            'packets_processed': 0,
            'packets_failed': 0,
            'packets_delegated': 0,
            'unknown_packets': 0
        }
        
        # Manager delegation map - packets are grouped by responsibility
        self.manager_delegation = {
            # Player management packets
            ServerToPlayer.PLO_PLAYERPROPS: 'session_packet_manager',
            ServerToPlayer.PLO_OTHERPLPROPS: 'session_packet_manager', 
            ServerToPlayer.PLO_ADDPLAYER: 'session_packet_manager',
            ServerToPlayer.PLO_DELPLAYER: 'session_packet_manager',
            ServerToPlayer.PLO_PLAYERWARP: 'session_packet_manager',
            ServerToPlayer.PLO_PLAYERWARP2: 'session_packet_manager',  # GMAP warp with world coords
            60: 'session_packet_manager',  # PLO_PLAYERRIGHTS - RC rights management
            
            # Level management packets
            ServerToPlayer.PLO_LEVELNAME: 'level_packet_manager',
            # ServerToPlayer.PLO_LEVELBOARD: 'level_packet_manager',  # Disabled - causes issues with PLO_BOARDPACKET
            ServerToPlayer.PLO_BOARDPACKET: 'level_packet_manager',
            ServerToPlayer.PLO_BOARDMODIFY: 'level_packet_manager',
            ServerToPlayer.PLO_LEVELSIGN: 'level_packet_manager',
            ServerToPlayer.PLO_LEVELCHEST: 'level_packet_manager',
            ServerToPlayer.PLO_LEVELLINK: 'level_packet_manager',
            
            # File transfer packets
            ServerToPlayer.PLO_FILE: 'file_manager',  # Standard file transfers
            102: 'file_manager',  # PLO_FILE by ID - standard file transfers
            
            # Large file download packets - delegate to file_manager
            68: 'file_manager',   # PLO_LARGEFILESTART - Large file transfer start
            84: 'file_manager',   # PLO_LARGEFILESIZE - Large file size info
            100: 'file_manager',  # PLO_RAWDATA - File data chunks
            69: 'file_manager',   # PLO_LARGEFILEEND - Large file transfer complete
            45: 'file_manager',   # PLO_FILEUPTODATE - File up to date check
            30: 'file_manager',   # PLO_FILESENDFAILED - File send failed
            
            # Communication packets  
            ServerToPlayer.PLO_TOALL: 'communication_manager',
            ServerToPlayer.PLO_PRIVATEMESSAGE: 'communication_manager',
            ServerToPlayer.PLO_SERVERTEXT: 'communication_manager',
            ServerToPlayer.PLO_DISCMESSAGE: 'communication_manager',
            
            # Combat packets
            ServerToPlayer.PLO_BOMBDEL: 'combat_manager',
            ServerToPlayer.PLO_BOMBADD: 'combat_manager',
            ServerToPlayer.PLO_ARROWADD: 'combat_manager',
            ServerToPlayer.PLO_EXPLOSION: 'combat_manager',
            
            # Weapon packets (routed to weapon_manager)
            33: 'weapon_manager',  # PLO_NPCWEAPONADD - NPC weapon add
            34: 'weapon_manager',  # PLO_NPCWEAPONDEL - NPC weapon delete
            43: 'weapon_manager',  # PLO_DEFAULTWEAPON - Default weapon assignment
            194: 'weapon_manager', # PLO_CLEARWEAPONS - Clear all weapons
            
            # NPC packets
            ServerToPlayer.PLO_BADDYPROPS: 'npc_manager',  # Baddies are server NPCs
            ServerToPlayer.PLO_NPCPROPS: 'npc_manager',
            ServerToPlayer.PLO_NPCMOVED: 'npc_manager',
            ServerToPlayer.PLO_NPCACTION: 'npc_manager',
            ServerToPlayer.PLO_NPCDEL: 'npc_manager',
            
            # System packets
            ServerToPlayer.PLO_SIGNATURE: 'system_manager',  # Login signature handled by system manager
            ServerToPlayer.PLO_WARPFAILED: 'system_manager',
            # Additional system packets by ID
            16: 'system_manager',  # PLO_DISCONNECT
            28: 'system_manager',  # PLO_FLAGSET
            39: 'system_manager',  # PLO_LEVELMODTIME
            42: 'system_manager',  # PLO_NEWWORLDTIME
            44: 'system_manager',  # PLO_HASNPCSERVER
            47: 'system_manager',  # PLO_STAFFGUILDS
            156: 'system_manager', # PLO_SETACTIVELEVEL
            182: 'system_manager', # PLO_LISTPROCESSES
            
            # Communication packets
            10: 'communication_manager',  # PLO_PRIVATEMESSAGE
            20: 'communication_manager',  # PLO_TOALL
            82: 'communication_manager',  # PLO_SERVERTEXT (also handled by communication)
            
            # Ensure critical packets are routed by ID (in case enum mapping fails)
            2: 'npc_manager',              # PLO_BADDYPROPS - server NPCs
            6: 'level_packet_manager',     # PLO_LEVELNAME - must be handled for correct level setting
            9: 'session_packet_manager',   # PLO_PLAYERPROPS - must be handled for player data
        }
        
        logger.info("Manager-based packet processor initialized")
        logger.info(f"Registry loaded: {len(PACKET_REGISTRY.get_all_structures())} packet types")
        logger.info(f"Manager delegation configured for {len(self.manager_delegation)} packet types")
    
    def process_packet(self, packet_id: int, data: bytes, announced_size: int = 0) -> Optional[Dict[str, Any]]:
        """
        Process a packet using registry-driven parsing and manager delegation.
        
        This is the main entry point that replaces PacketHandler.handle_packet().
        """
        self.stats['packets_processed'] += 1
        start_time = time.perf_counter()  # High-precision timing
        
        try:
            # Emit raw packet event for tracking
            if hasattr(self.client, 'events') and self.client.events:
                from pyreborn.core.events import EventType
                self.client.events.emit(EventType.RAW_PACKET_RECEIVED, {
                    'packet_id': packet_id, 
                    'packet_data': data
                })
            
            # Step 1: Parse packet using registry
            parsed_packet = self.parser.parse_packet(packet_id, data, announced_size)
            if not parsed_packet:
                self.stats['unknown_packets'] += 1
                logger.warning(f"Unknown packet ID {packet_id}, size: {len(data)} bytes")
                return None
            
            # Debug: Log level-related packets to track data flow
            if packet_id in [0, 1, 5, 6, 12]:  # Level-related packets
                packet_name = parsed_packet.get('packet_name', f'PACKET_{packet_id}')
                logger.info(f"🏗️ {packet_name} (ID {packet_id}): {len(data)} bytes")
                if len(data) > 0:
                    # Show first 50 bytes of data
                    data_preview = data[:50]
                    logger.info(f"   Raw: {data_preview}{'...' if len(data) > 50 else ''}")
                    # Show printable characters
                    printable = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data_preview)
                    logger.info(f"   Text: '{printable}'")
            
            # Emit structured packet event with parsed fields (legacy event)
            if hasattr(self.client, 'events') and self.client.events:
                self.client.events.emit(EventType.STRUCTURED_PACKET_RECEIVED, {
                    'packet_id': packet_id, 
                    'packet_data': data,
                    'parsed_fields': parsed_packet
                })
                
                # Emit new comprehensive incoming packet event
                structured_data = {
                    'packet_id': packet_id,
                    'packet_name': parsed_packet.get('packet_name', f'Unknown_{packet_id}'),
                    'direction': 'incoming',
                    'timestamp': time.time(),
                    'raw_data': data,
                    'parsed_fields': parsed_packet.get('fields', {}),
                    'parsed_data': parsed_packet.get('parsed_data', {}),
                    'size': len(data)
                }
                self.client.events.emit(EventType.INCOMING_PACKET_STRUCTURED, structured_data)
            
            # NEW: Check if parse() returned events to emit
            parsed_data = parsed_packet.get('parsed_data', {})
            if 'events' in parsed_data and hasattr(self.client, 'events'):
                for event_info in parsed_data['events']:
                    # Convert string event types to EventType enum if needed
                    event_type = event_info.get('type')
                    event_data = event_info.get('data', {})
                    
                    # Try to get the EventType enum value
                    try:
                        from ..session.events import EventType
                        if isinstance(event_type, str):
                            event_type = getattr(EventType, event_type, None)
                        
                        if event_type:
                            logger.debug(f"📢 Emitting event from packet parse: {event_type}")
                            self.client.events.emit(event_type, event_data)
                    except Exception as e:
                        logger.warning(f"Failed to emit event {event_type}: {e}")
            
            # Step 2: Check if we have manager delegation for this packet
            if packet_id in self.manager_delegation:
                manager_name = self.manager_delegation[packet_id]
                logger.debug(f"📋 Delegating packet {packet_id} to {manager_name}")
                
                # Debug logging for specific packets
                if packet_id == 49:  # PLO_GMAPWARP2
                    logger.info(f"🎯 Delegating packet 49 (PLO_GMAPWARP2) to {manager_name}")
                    parsed_data = parsed_packet.get('parsed_data', {})
                    logger.info(f"   Parsed data: {parsed_data}")
                elif packet_id == 1:  # PLO_LEVELLINK
                    fields = parsed_packet.get('fields', {})
                    link_data = fields.get('link_data', '')
                    if link_data:  # Only log non-empty link data
                        logger.info(f"🔗 Delegating packet 1 (PLO_LEVELLINK) to {manager_name}")
                        logger.info(f"   Link data: {link_data}")
                    else:
                        logger.debug(f"Delegating empty PLO_LEVELLINK to {manager_name}")
                    
                result = self._delegate_to_manager(manager_name, packet_id, parsed_packet)
                if result:
                    self.stats['packets_delegated'] += 1
                    return result
            
            # Step 3: Handle packets without specific manager delegation
            result = self._handle_unmanaged_packet(packet_id, parsed_packet)
            
            # Debug: Look for potential level link data in any packet
            if len(data) > 5:  # Only check packets with meaningful data
                data_str = data.decode('utf-8', errors='ignore').lower()
                if any(keyword in data_str for keyword in ['house', '.nw', 'level', 'warp']):
                    logger.info(f"🔍 Potential level data in packet {packet_id}: '{data_str[:100]}'")
            
            # Record metrics for successful processing
            processing_time_ms = (time.perf_counter() - start_time) * 1000
            packet_name = parsed_packet.get('packet_name', f'PACKET_{packet_id}')
            record_packet_metric(
                packet_id=packet_id,
                packet_name=packet_name,
                size_bytes=len(data),
                processing_time_ms=processing_time_ms,
                success=True,
                direction='incoming'
            )
            
            return result
            
        except Exception as e:
            self.stats['packets_failed'] += 1
            logger.error(f"Failed to process packet {packet_id}: {e}", exc_info=True)
            
            # Record metrics for failed processing
            processing_time_ms = (time.perf_counter() - start_time) * 1000
            record_packet_metric(
                packet_id=packet_id,
                packet_name=f'PACKET_{packet_id}',
                size_bytes=len(data),
                processing_time_ms=processing_time_ms,
                success=False,
                direction='incoming',
                error_message=str(e)
            )
            
            return None
    
    def _delegate_to_manager(self, manager_name: str, packet_id: int, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Delegate packet processing to the appropriate manager"""
        
        try:
            # Get the manager instance from the client
            manager = getattr(self.client, manager_name, None)
            if not manager:
                logger.warning(f"Manager '{manager_name}' not found on client for packet {packet_id}")
                return None
            
            # Try to find a specific handler method for this packet
            packet_name = parsed_packet['packet_name'].lower()
            handler_method_name = f"handle_{packet_name}"
            
            if hasattr(manager, handler_method_name):
                handler_method = getattr(manager, handler_method_name)
                logger.debug(f"Delegating {packet_name} to {manager_name}.{handler_method_name}")
                return handler_method(parsed_packet)
            
            # Fall back to generic packet handler if available
            elif hasattr(manager, 'handle_packet'):
                logger.debug(f"Delegating {packet_name} to {manager_name}.handle_packet")
                return manager.handle_packet(packet_id, parsed_packet)
            
            else:
                logger.warning(f"Manager '{manager_name}' has no handler for {packet_name}")
                return None
                
        except Exception as e:
            logger.error(f"Manager delegation failed for {packet_id}: {e}", exc_info=True)
            return None
    
    def _handle_unmanaged_packet(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle packets that don't have specific manager delegation"""
        
        packet_name = parsed_packet['packet_name']
        fields = parsed_packet['fields']
        
        logger.debug(f"Processing unmanaged packet: {packet_name}")
        
        # Emit events for specific unmanaged packets
        if packet_id == 42 and hasattr(self.client, 'events'):  # PLO_NEWWORLDTIME
            # Parse the packet if it has a custom parser
            custom_data = parsed_packet.get('parsed_data', {})
            if custom_data:
                # Include all custom data plus packet_id
                event_data = {'packet_id': packet_id}
                event_data.update(custom_data)
                self.client.events.emit(EventType.WORLD_TIME_UPDATE, event_data)
            else:
                # Emit with basic fields
                self.client.events.emit(EventType.WORLD_TIME_UPDATE, {
                    'packet_id': packet_id,
                    'world_time': fields.get('world_time', 0)
                })
        
        # Some packets might just need to be acknowledged without specific processing
        # Return basic information for logging/debugging
        return {
            'type': 'unmanaged_packet',
            'packet_id': packet_id,
            'packet_name': packet_name,
            'field_count': len(fields),
            'processed': True
        }
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """Get packet processing statistics"""
        total = self.stats['packets_processed'] 
        success_rate = 0.0
        if total > 0:
            successful = total - self.stats['packets_failed']
            success_rate = (successful / total) * 100
        
        return {
            **self.stats,
            'success_rate': success_rate,
            'registry_packets': len(PACKET_REGISTRY.get_all_structures()),
            'managed_packets': len(self.manager_delegation)
        }
    
    def get_supported_packets(self) -> Dict[str, Any]:
        """Get information about supported packets"""
        registry_packets = set(PACKET_REGISTRY.get_all_structures().keys())
        managed_packets = set(self.manager_delegation.keys())
        
        return {
            'registry_supported': list(registry_packets),
            'manager_delegated': list(managed_packets),
            'fully_supported': list(registry_packets & managed_packets),
            'registry_only': list(registry_packets - managed_packets),
            'delegation_only': list(managed_packets - registry_packets)
        }
    
    def add_manager_delegation(self, packet_id: int, manager_name: str):
        """Add manager delegation for a packet type"""
        self.manager_delegation[packet_id] = manager_name
        logger.info(f"Added manager delegation: packet {packet_id} -> {manager_name}")
    
    def remove_manager_delegation(self, packet_id: int):
        """Remove manager delegation for a packet type"""
        if packet_id in self.manager_delegation:
            manager_name = self.manager_delegation.pop(packet_id)
            logger.info(f"Removed manager delegation: packet {packet_id} from {manager_name}")


def create_packet_processor(client) -> ManagerPacketProcessor:
    """Factory function to create a packet processor for a client"""
    return ManagerPacketProcessor(client)


# Example usage and testing functions
def demonstrate_manager_processor():
    """Demonstrate the manager-based packet processor"""
    print("🔧 Manager-Based Packet Processor Demo")
    print("=" * 45)
    
    # Mock client for demonstration
    class MockClient:
        def __init__(self):
            self.session_manager = MockSessionManager()
            self.level_manager = MockLevelManager()
    
    class MockSessionManager:
        def handle_plo_playerprops(self, parsed_packet):
            return {'type': 'player_props', 'processed': True}
    
    class MockLevelManager:
        def handle_plo_levelname(self, parsed_packet):
            return {'type': 'level_name', 'processed': True}
    
    # Create processor
    client = MockClient()
    processor = ManagerPacketProcessor(client)
    
    # Show statistics
    stats = processor.get_processing_statistics()
    print(f"Initial statistics: {stats}")
    
    # Show supported packets
    supported = processor.get_supported_packets()
    print(f"Registry packets: {len(supported['registry_supported'])}")
    print(f"Managed packets: {len(supported['manager_delegated'])}")
    print(f"Fully supported: {len(supported['fully_supported'])}")
    
    print("\n✅ Manager-based processor ready to replace PacketHandler!")


if __name__ == "__main__":
    demonstrate_manager_processor()