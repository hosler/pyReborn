#!/usr/bin/env python3
"""
Real RebornClient Implementation

This is the actual client that connects to servers and receives level data.
It uses the internal connection and protocol components.
"""

import logging
import time
from typing import Optional, Dict, Any, List
from threading import Thread, Event
import queue

from ..connection.connection_manager import ConnectionManager as ConnManager
from ..session.session_manager import SessionManager
from ..world.world_manager import WorldManager
from ..world.level_manager import LevelManager
from ..world.gmap_manager import GMAPManager
# Gameplay manager removed for simplicity
from ..protocol.packet_processor import PacketProcessor
from ..config.client_config import ClientConfig
from ..models.player import Player
from ..models.level import Level
from .events import EventManager, EventType

logger = logging.getLogger(__name__)


class RebornClient:
    """Real client implementation with full server connectivity"""
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037"):
        """Initialize the real client"""
        self.logger = logging.getLogger(__name__)
        
        # Connection parameters
        self.host = host
        self.port = port
        self.version = version
        
        # Initialize configuration
        self.config = ClientConfig(
            host=host,
            port=port,
            version=version
        )
        
        # Initialize event system
        self.events = EventManager()
        
        # Initialize managers
        self.connection_manager = ConnManager(host, port, version)
        self.session_manager = SessionManager()
        self.level_manager = LevelManager()
        self.gmap_manager = GMAPManager()
        self.world_manager = WorldManager()
        # Gameplay manager removed for simplicity
        
        # Initialize individual gameplay managers from the gameplay system
        from ..gameplay.item_manager import ItemManager
        from ..gameplay.combat_manager import CombatManager
        from ..gameplay.npc_manager import NPCManager
        from ..gameplay.weapon_manager import WeaponManager
        # Communication manager removed - functionality moved to client
        from ..session.file_manager import FileManager
        from ..session.cache_manager import CacheManager
        
        self.item_manager = ItemManager()
        self.combat_manager = CombatManager()
        self.npc_manager = NPCManager()
        self.weapon_manager = WeaponManager()
        # Communication functionality moved to client methods
        
        # Initialize file download system
        self.cache_manager = CacheManager()
        self.cache_manager.set_server(host, port)  # Set server for cache organization
        self.file_manager = FileManager(
            client=self,
            event_manager=self.events,
            cache_manager=self.cache_manager
        )
        
        # Create a simple actions interface for compatibility
        from types import SimpleNamespace
        self.actions = SimpleNamespace()
        self.actions.send_chat = self._send_chat_action
        self.actions.attack = self._attack_action
        self.actions.use_sword = self._use_sword_action
        self.actions.move_to = self._move_to_action
        self.actions.say = self._send_chat_action
        
        # Import and create packet managers for handling packets
        from ..session.system_manager import SystemManager
        from ..session.session_packet_manager import SessionPacketManager
        from ..world.level_packet_manager import LevelPacketManager
        self.system_manager = SystemManager()
        self.session_packet_manager = SessionPacketManager()
        self.level_packet_manager = LevelPacketManager()
        # Set up manager references
        self.system_manager.session_manager = self.session_manager
        self.session_packet_manager.set_session_manager(self.session_manager)
        self.level_packet_manager.set_level_manager(self.level_manager)
        self.level_packet_manager.set_session_manager(self.session_manager)  # 🎯 Critical fix!
        self.level_packet_manager.set_client(self)  # 🚀 Enable GMAP level auto-requests
        
        # Connect GMAP manager to session manager for level resolution
        self.session_manager.set_gmap_manager(self.gmap_manager)
        
        # 🚀 Connect GMAP manager to client for automatic downloads
        self.gmap_manager.set_client(self)
        
        # Initialize managers that implement IManager
        self.system_manager.initialize(self.config, self.events)
        self.session_packet_manager.initialize(self.config, self.events)
        self.level_packet_manager.initialize(self.config, self.events)
        
        # Initialize packet processor
        self.packet_processor = PacketProcessor()
        # Configure packet processor after initialization
        if hasattr(self.packet_processor, 'initialize'):
            self.packet_processor.initialize(self.config, self.events)
        
        # Set up the manager packet processor for the new architecture
        from ..protocol.manager_packet_processor import ManagerPacketProcessor
        manager_processor = ManagerPacketProcessor(self)  # Pass self as client reference
        self.packet_processor.manager_processor = manager_processor
        
        # Set up packet routing
        self.connection_manager.set_packet_callback(self._handle_packet)
        
        # Packet queue for thread-safe processing
        self.packet_queue = queue.Queue()
        self.running = False
        self.processing_thread = None
        
        # State
        self.connected = False
        self.authenticated = False
        
        self.logger.info("🎆 Real RebornClient initialized")
    
    def _handle_packet(self, data: bytes):
        """Handle incoming packet from connection"""
        # Queue the packet for processing
        self.packet_queue.put(data)
    
    def _process_packets(self):
        """Process packets in background thread"""
        while self.running:
            try:
                # Get packet with timeout
                data = self.packet_queue.get(timeout=0.1)
                
                # Process the packet - extract packet ID from first byte
                try:
                    if data and len(data) > 0:
                        # Socket manager already subtracted 32, so first byte is the actual packet ID
                        packet_id = data[0]
                        packet_data = data[1:] if len(data) > 1 else b''
                        
                        # Log suspicious packets
                        if packet_id < 0:
                            self.logger.warning(f"❌ NEGATIVE PACKET ID: raw={data[0]}, corrected_id={packet_id}, size={len(packet_data)}, data={data[:10].hex()}")
                        else:
                            # Throttle common packet logging to reduce spam
                            common_packets = {3, 6, 0, 4, 174, 10, 42, 156}  # NPC, level, board, chest, ghost, private, time, active
                            if packet_id not in common_packets:
                                self.logger.debug(f"Processing packet: raw={data[0]}, corrected_id={packet_id}, size={len(packet_data)}")
                        
                        self.packet_processor.process_packet(packet_id, packet_data)
                except Exception as e:
                    self.logger.error(f"Error processing packet: {e}")
                    
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Packet processing error: {e}")
    
    def connect(self) -> bool:
        """Connect to server"""
        self.logger.info(f"Connecting to {self.host}:{self.port}")
        
        result = self.connection_manager.connect()
        if result:
            self.connected = True
            self.running = True
            
            # Start packet processing thread
            self.processing_thread = Thread(target=self._process_packets, daemon=True)
            self.processing_thread.start()
            
            # Fire connected event
            self.events.emit(EventType.CONNECTED, {"host": self.host, "port": self.port})
            
        return result
    
    def login(self, account: str, password: str) -> bool:
        """Login to server"""
        if not self.connected:
            return False
        
        self.logger.info(f"Login: {account}")
        
        # Send login packet
        result = self.connection_manager.login(account, password)
        
        if result:
            # Wait for authentication response
            timeout = time.time() + 5.0
            while time.time() < timeout:
                session_auth = self.session_manager.is_authenticated() if self.session_manager else False
                self.logger.debug(f"🔍 Checking authentication: session_manager={bool(self.session_manager)}, is_authenticated={session_auth}")
                
                if session_auth:
                    self.authenticated = True
                    self.logger.info(f"🔐 Authentication successful - set authenticated = True")
                    
                    # Process any deferred file requests now that authentication is complete
                    self.logger.info(f"🔄 Processing deferred file requests after authentication...")
                    self._process_deferred_file_requests()
                    
                    self.events.emit(EventType.LOGIN_SUCCESS, {"account": account})
                    return True
                time.sleep(0.1)
            
            self.logger.error("Login timed out")
            self.events.emit(EventType.LOGIN_FAILED, {"reason": "timeout"})
            
        return False
    
    def disconnect(self):
        """Disconnect from server"""
        self.logger.info("Disconnecting")
        
        self.running = False
        if self.processing_thread:
            self.processing_thread.join(timeout=1.0)
        
        self.connection_manager.disconnect()
        self.connected = False
        self.authenticated = False
        
        self.events.emit(EventType.DISCONNECTED, {})
    
    def is_connected(self) -> bool:
        """Check connection status"""
        return self.connected and self.connection_manager.is_connected()
    
    def is_authenticated(self) -> bool:
        """Check authentication status"""
        return self.authenticated and self.session_manager.is_authenticated()
    
    def is_logged_in(self) -> bool:
        """Alias for is_authenticated"""
        return self.is_authenticated()
    
    def get_local_player(self) -> Optional[Player]:
        """Get local player"""
        return self.session_manager.get_player()
    
    def get_player(self) -> Optional[Player]:
        """Get the local player object (alias for compatibility)"""
        return self.get_local_player()
    
    def send_packet(self, packet_bytes: bytes) -> bool:
        """Send packet to server
        
        Args:
            packet_bytes: Raw packet bytes to send
            
        Returns:
            True if sent successfully
        """
        if not self.connection_manager:
            return False
            
        try:
            self.connection_manager.send_packet(packet_bytes)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send packet: {e}")
            return False
    
    def get_manager(self, manager_name: str):
        """Get manager by name"""
        managers = {
            'session': self.session_manager,
            'session_packet_manager': self.session_packet_manager,
            'level': self.level_manager,
            'level_packet_manager': self.level_packet_manager,
            'gmap': self.gmap_manager,
            'world': self.world_manager,
            # gameplay manager removed
            'system_manager': self.system_manager,
            'event': self.events,
            # Individual managers for test compatibility
            'item': self.item_manager,
            'combat': self.combat_manager,
            'npc': self.npc_manager,
            'communication': self.communication_manager
        }
        return managers.get(manager_name)
    
    def get_event_manager(self):
        """Get event manager - compatibility method for tests"""
        return self.events
    
    def send_packet(self, data: bytes):
        """Send packet to server"""
        self.connection_manager.send_packet(data)
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            'packets_received': self.packet_processor.packets_processed,
            'packets_sent': 0,  # TODO: Track sent packets
            'connected': self.connected
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get client status"""
        player = self.get_local_player()
        return {
            'architecture': 'REAL_CLIENT',
            'connected': self.connected,
            'authenticated': self.authenticated,
            'player_id': player.player_id if player else None,
            'account': player.account if player else None,
            'level': self.level_manager.get_current_level_name()
        }
    
    def update(self):
        """Update client state"""
        # Process any pending events
        self.events.process_queue()
        
        # Update managers
        if self.world_manager:
            self.world_manager.update()
    
    def move(self, dx: int, dy: int):
        """Send movement to server with GMAP-aware coordinate handling"""
        if not self.authenticated:
            return
        
        # Get the player manager directly for position updates
        player_manager = self.session_manager.player
        
        # 🎯 GMAP-AWARE MOVEMENT: Check if we're in GMAP mode
        is_gmap_mode = (hasattr(self, 'gmap_manager') and 
                       self.gmap_manager and 
                       self.gmap_manager.is_gmap_mode())
        
        if is_gmap_mode:
            # GMAP mode: Calculate world coordinates and handle segment transitions
            self._handle_gmap_movement(dx, dy, player_manager)
        else:
            # Single level mode: Use local coordinates  
            self._handle_single_level_movement(dx, dy, player_manager)
        
    
    def _handle_gmap_movement(self, dx: int, dy: int, player_manager):
        """Handle movement in GMAP mode with world coordinates and segment transitions"""
        try:
            # Get current world coordinates from GMAP manager
            current_world_x = getattr(self.gmap_manager, 'current_world_x', None)
            current_world_y = getattr(self.gmap_manager, 'current_world_y', None)
            
            if current_world_x is None or current_world_y is None:
                self.logger.warning("⚠️ No world coordinates available, falling back to single level movement")
                self._handle_single_level_movement(dx, dy, player_manager)
                return
            
            # Calculate new world coordinates
            new_world_x = current_world_x + dx
            new_world_y = current_world_y + dy
            
            # Calculate segments
            old_segment_x = int(current_world_x // 64)
            old_segment_y = int(current_world_y // 64)
            new_segment_x = int(new_world_x // 64)
            new_segment_y = int(new_world_y // 64)
            
            # Calculate local coordinates within segment
            new_local_x = new_world_x % 64
            new_local_y = new_world_y % 64
            
            # 🎯 FIX: Use movement-aware coordinate update to prevent wrapping
            resolved_level = self.gmap_manager.update_from_client_movement(new_world_x, new_world_y)
            
            # Update player manager local coordinates
            player_manager.update_position(new_local_x, new_local_y)
            
            # Determine direction
            direction = self._calculate_direction(dx, dy)
            player_manager.update_property('direction', int(direction))
            
            self.logger.debug(f"🗺️ GMAP Movement: world({current_world_x:.1f},{current_world_y:.1f}) → ({new_world_x:.1f},{new_world_y:.1f})")
            self.logger.debug(f"   Local coords: ({new_local_x:.1f},{new_local_y:.1f})")
            self.logger.debug(f"   Segment: ({old_segment_x},{old_segment_y}) → ({new_segment_x},{new_segment_y})")
            
            # Import the packet helper
            from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
            
            # Get GMAP filename for CURLEVEL property (as per user requirements)
            gmap_filename = "chicken.gmap"  # Default for this server
            if hasattr(self.gmap_manager, 'current_gmap') and self.gmap_manager.current_gmap:
                gmap_filename = self.gmap_manager.current_gmap.name
            
            # Get resolved level name for CURLEVEL (from movement-aware update)
            if not resolved_level:
                resolved_level = "chicken1.nw"  # Fallback default
                if hasattr(self.gmap_manager, 'resolved_level_name') and self.gmap_manager.resolved_level_name:
                    resolved_level = self.gmap_manager.resolved_level_name
            
            # 🎯 FIX: In GMAP mode, send world coordinates (x2/y2) as per user-approved assumptions
            # "When in gmap mode and in a gmap level, send gserver our world coords and not local level x,y coords"
            packet_props = {
                'x2': new_world_x,  # World X coordinates in GMAP mode
                'y2': new_world_y,  # World Y coordinates in GMAP mode
                'sprite': int(direction),
                'curlevel': gmap_filename,  # Always send GMAP filename in GMAP mode
                #'gmaplevelx': new_segment_x,  # Send segment coordinates
                #'gmaplevely': new_segment_y
            }
            
            self.logger.debug(f"   Sending world coords (x2/y2): ({new_world_x:.1f},{new_world_y:.1f})")
            self.logger.debug(f"   Sending CURLEVEL: {gmap_filename}")
            self.logger.debug(f"   Sending segment: ({new_segment_x},{new_segment_y})")
            
            # Log segment transitions specifically
            if new_segment_x != old_segment_x or new_segment_y != old_segment_y:
                self.logger.info(f"🗺️ Segment transition: ({old_segment_x},{old_segment_y}) → ({new_segment_x},{new_segment_y})")
            
            packet = PlayerPropsPacketHelper.create_with_properties(**packet_props)
            self._send_packet(packet)
            
            # Movement state will timeout automatically via movement_timeout in GMAP manager
            # This allows server responses to be processed while maintaining coordinate continuity
            
        except Exception as e:
            self.logger.error(f"❌ GMAP movement failed: {e}")
            # Fallback to single level movement
            self._handle_single_level_movement(dx, dy, player_manager)
    
    def _handle_single_level_movement(self, dx: int, dy: int, player_manager):
        """Handle movement in single level mode with local coordinates"""
        try:
            # Update local position prediction in the manager
            old_x, old_y = player_manager.x, player_manager.y
            new_x = old_x + dx
            new_y = old_y + dy
            
            # Update the player manager's position
            player_manager.update_position(new_x, new_y)
            
            # Send movement packet using local coordinates
            # Convert tile coordinates to pixels (16 pixels per tile)
            pixel_x = int(new_x * 16)
            pixel_y = int(new_y * 16)
            
            # Determine direction
            direction = self._calculate_direction(dx, dy)
            player_manager.update_property('direction', int(direction))
            
            self.logger.debug(f"🏠 Single Level Movement: ({old_x:.1f},{old_y:.1f}) → ({new_x:.1f},{new_y:.1f}), pixels=({pixel_x},{pixel_y})")
            
            # Import the packet helper
            from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
            
            # Create movement packet with local coordinates
            packet = PlayerPropsPacketHelper.create_with_properties(
                x2=pixel_x,
                y2=pixel_y,
                sprite=int(direction)
            )
            
            self._send_packet(packet)
            
        except Exception as e:
            self.logger.error(f"❌ Single level movement failed: {e}")
    
    def _calculate_direction(self, dx: int, dy: int):
        """Calculate direction enum from movement deltas"""
        from pyreborn.protocol.enums import Direction
        
        # Get current direction from player for fallback
        player = self.get_local_player()
        direction = player.direction if player else Direction.DOWN
        
        if dx > 0:
            direction = Direction.RIGHT
        elif dx < 0:
            direction = Direction.LEFT
        elif dy > 0:
            direction = Direction.DOWN
        elif dy < 0:
            direction = Direction.UP
            
        return direction
    
    def _send_packet(self, packet):
        """Send packet to server using connection manager"""
        try:
            if self.connection_manager:
                # Use the builder to convert packet to bytes
                if packet.structure.builder_class:
                    builder = packet.structure.builder_class()
                    packet_bytes = builder.build_packet(packet)
                    self.connection_manager.send_packet(packet_bytes)
                else:
                    self.logger.error("No builder for PlayerProps packet")
            else:
                self.logger.warning("Cannot send movement - no connection manager")
        except Exception as e:
            self.logger.error(f"❌ Failed to send packet: {e}")
    
    def _process_deferred_file_requests(self):
        """Process any deferred file requests from managers"""
        try:
            self.logger.info(f"🔍 Checking for deferred file requests...")
            
            # 🎯 FIX: Level packet manager is accessed directly on client, not stored in manager processor
            level_packet_manager = getattr(self, 'level_packet_manager', None)
            
            if level_packet_manager:
                self.logger.info(f"✅ Found level packet manager directly on client")
            else:
                self.logger.warning(f"⚠️ No level_packet_manager attribute on client")
                
            if level_packet_manager:
                # Check deferred requests
                deferred_requests = getattr(level_packet_manager, 'deferred_requests', set())
                self.logger.info(f"📋 Level packet manager deferred requests: {deferred_requests if deferred_requests else 'None'}")
                
                if hasattr(level_packet_manager, 'process_deferred_requests'):
                    self.logger.info(f"🔄 Calling level_packet_manager.process_deferred_requests()...")
                    level_packet_manager.process_deferred_requests()
                    
                    # 🎯 FIX: After processing deferred requests, trigger cache loading for GMAP files
                    if hasattr(self, 'level_manager') and self.level_manager:
                        if hasattr(self.level_manager, 'load_levels_from_cache_directory'):
                            # Get cache directory from cache manager - try server-specific directory first
                            cache_dir = None
                            if hasattr(self, 'cache_manager') and self.cache_manager:
                                # Try server-specific cache directory first
                                if hasattr(self.cache_manager, '_get_server_dir'):
                                    try:
                                        server_dir = self.cache_manager._get_server_dir()
                                        if server_dir and server_dir.exists():
                                            cache_dir = str(server_dir)
                                            self.logger.info(f"Using server-specific cache: {cache_dir}")
                                    except:
                                        pass
                                
                                # Fallback to levels_dir
                                if not cache_dir:
                                    cache_dir = getattr(self.cache_manager, 'levels_dir', None)
                                    if cache_dir:
                                        cache_dir = str(cache_dir)
                            
                            if cache_dir:
                                self.logger.info(f"🔄 Auto-loading cached GMAP levels from: {cache_dir}")
                                self.level_manager.load_levels_from_cache_directory(cache_dir)
                                
                                # Report results
                                levels_count = len(getattr(self.level_manager, 'levels', {}))
                                self.logger.info(f"✅ Level manager now has {levels_count} total levels loaded")
                            else:
                                self.logger.warning(f"⚠️ No cache directory available for auto-loading")
                        else:
                            self.logger.warning(f"⚠️ Level manager doesn't support cache directory loading")
                else:
                    self.logger.warning(f"⚠️ Level packet manager has no process_deferred_requests method")
            
            # Check GMAP manager for failed requests to retry
            if hasattr(self, 'gmap_manager') and self.gmap_manager:
                if hasattr(self.gmap_manager, 'retry_failed_requests'):
                    self.logger.info(f"🔄 Calling gmap_manager.retry_failed_requests()...")
                    self.gmap_manager.retry_failed_requests()
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing deferred file requests: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def attack(self):
        """Perform sword attack"""
        return self._attack_action()
    
    def drop_bomb(self, power: int = 1, timer: int = 55):
        """Drop a bomb at current position
        
        Args:
            power: Bomb power (1-10)
            timer: Bomb timer in ticks
        """
        if not self.authenticated:
            return False
            
        # Get current player position
        player = self.get_local_player()
        if not player:
            return False
            
        # Import packet helper
        from pyreborn.packets.outgoing.combat.bomb_add import BombAddPacketHelper
        
        # Create bomb packet at player position
        packet = BombAddPacketHelper.create(player.x, player.y, power, timer)
        
        # Send the packet
        if self.connection_manager:
            try:
                packet_bytes = packet.to_bytes()
                self.connection_manager.send_packet(packet_bytes)
                self.logger.debug(f"Dropped bomb at ({player.x:.1f}, {player.y:.1f}) with power={power}")
                return True
            except Exception as e:
                self.logger.error(f"Failed to drop bomb: {e}")
                return False
        
        return False
    
    def take_item(self, x: float, y: float):
        """Take an item at specified coordinates
        
        Args:
            x: X coordinate of item (in tiles)
            y: Y coordinate of item (in tiles)
        """
        if not self.authenticated:
            return False
            
        # Import packet helper
        from pyreborn.packets.outgoing.items.item_take import ItemTakePacketHelper
        
        # Create item take packet
        packet = ItemTakePacketHelper.create(x, y)
        
        # Send the packet
        if self.connection_manager:
            try:
                packet_bytes = packet.to_bytes()
                self.connection_manager.send_packet(packet_bytes)
                self.logger.debug(f"Sent item take at ({x:.1f}, {y:.1f})")
                return True
            except Exception as e:
                self.logger.error(f"Failed to send item take: {e}")
                return False
        
        return False
    
    def say(self, message: str):
        """Send chat message"""
        if not self.authenticated:
            return
        
        # Import the packet helper
        from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
        from pyreborn.protocol.enums import PlayerProp
        
        # Create chat packet
        packet = PlayerPropsPacketHelper.create_with_properties(
            chat=message  # PLPROP_CURCHAT
        )
        
        # Send the packet using the builder
        if self.connection_manager:
            # Use the builder to convert packet to bytes
            if packet.structure.builder_class:
                builder = packet.structure.builder_class()
                packet_bytes = builder.build_packet(packet)
                self.connection_manager.send_packet(packet_bytes)
                self.logger.debug(f"Sent chat: {message}")
            else:
                self.logger.error("No builder for PlayerProps packet")
        else:
            self.logger.warning("Cannot send chat - no connection manager")
    
    def set_nickname(self, nickname: str):
        """Set player nickname"""
        if not self.authenticated:
            return False
        
        # Import the packet helper
        from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
        
        # Create nickname packet
        packet = PlayerPropsPacketHelper.create_with_properties(
            nickname=nickname
        )
        
        # Send the packet
        if self.connection_manager and packet.structure.builder_class:
            builder = packet.structure.builder_class()
            packet_bytes = builder.build_packet(packet)
            self.connection_manager.send_packet(packet_bytes)
            self.logger.debug(f"Set nickname: {nickname}")
            return True
        else:
            self.logger.warning("Cannot set nickname - no connection manager or builder")
            return False
    
    def set_head(self, head_image: str):
        """Set player head image"""
        if not self.authenticated:
            return False
        
        # Import the packet helper
        from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
        
        # Create head packet
        packet = PlayerPropsPacketHelper.create_with_properties(
            headimg=head_image
        )
        
        # Send the packet
        if self.connection_manager and packet.structure.builder_class:
            builder = packet.structure.builder_class()
            packet_bytes = builder.build_packet(packet)
            self.connection_manager.send_packet(packet_bytes)
            self.logger.debug(f"Set head: {head_image}")
            return True
        else:
            self.logger.warning("Cannot set head - no connection manager or builder")
            return False
    
    def set_body(self, body_image: str):
        """Set player body image"""
        if not self.authenticated:
            return False
        
        # Import the packet helper
        from pyreborn.packets.outgoing.core.player_props import PlayerPropsPacketHelper
        
        # Create body packet
        packet = PlayerPropsPacketHelper.create_with_properties(
            bodyimg=body_image
        )
        
        # Send the packet
        if self.connection_manager and packet.structure.builder_class:
            builder = packet.structure.builder_class()
            packet_bytes = builder.build_packet(packet)
            self.connection_manager.send_packet(packet_bytes)
            self.logger.debug(f"Set body: {body_image}")
            return True
        else:
            self.logger.warning("Cannot set body - no connection manager or builder")
            return False
    
    def _send_chat_action(self, message: str):
        """Action interface for sending chat - compatibility method"""
        self.say(message)
        return True
    
    def _attack_action(self):
        """Action interface for attack - compatibility method"""
        if not self.authenticated:
            return False
        
        # Get current player position
        player = self.get_local_player()
        if not player:
            return False
            
        # Import packet helpers
        from pyreborn.packets.outgoing.combat.shoot import ShootPacketHelper
        from pyreborn.protocol.enums import Direction
        import math
        
        # Calculate angle based on direction
        angle_map = {
            Direction.DOWN: math.pi / 2,   # Down = π/2
            Direction.LEFT: math.pi,        # Left = π
            Direction.UP: math.pi * 3 / 2,  # Up = 3π/2  
            Direction.RIGHT: 0              # Right = 0
        }
        angle = angle_map.get(player.direction, 0)
        
        # Create shoot packet (sword swing)
        packet = ShootPacketHelper.create(
            x=player.x,
            y=player.y,
            angle=angle,
            speed=20,
            gani="sword"  # Sword animation
        )
        
        # Send the packet
        if self.connection_manager:
            try:
                packet_bytes = packet.to_bytes()
                self.connection_manager.send_packet(packet_bytes)
                self.logger.debug(f"Sent attack at ({player.x:.1f}, {player.y:.1f}), dir={player.direction.name}")
                return True
            except Exception as e:
                self.logger.error(f"Failed to send attack packet: {e}")
                return False
        
        return False
    
    def _use_sword_action(self):
        """Action interface for using sword - same as attack"""
        return self._attack_action()
    
    def _move_to_action(self, x: float, y: float):
        """Action interface for move_to - moves to absolute position"""
        if not self.authenticated:
            return False
        
        # Get current player position
        player = self.get_local_player()
        if not player:
            return False
        
        # Calculate movement delta
        dx = x - player.x
        dy = y - player.y
        
        # Use the existing move method
        return self.move(dx, dy)
    
    def request_file(self, filename: str) -> bool:
        """Request a file from the server using proper packet format
        
        Args:
            filename: Name of the file to request
            
        Returns:
            True if request was sent successfully
        """
        if not self.authenticated:
            self.logger.warning(f"Cannot request file - not authenticated (authenticated={self.authenticated})")
            return False
        
        try:
            # Use the proper WantFile packet structure
            from pyreborn.packets.outgoing.system.want_file import WantFilePacketHelper
            
            self.logger.info(f"🔧 Creating WantFile packet for: {filename}")
            
            # Create proper WantFile packet
            packet = WantFilePacketHelper.create(filename)
            packet_bytes = packet.to_bytes()
            
            self.logger.info(f"🔧 Packet created: {len(packet_bytes)} bytes")
            
            if self.connection_manager:
                self.connection_manager.send_packet(packet_bytes)
                self.logger.info(f"✅ Requested file using proper packet format: {filename}")
                
                # Register the file request with file manager for correct filename detection
                if hasattr(self, 'file_manager') and self.file_manager:
                    self.file_manager.register_file_request(filename)
                    self.logger.info(f"✅ Registered file request with file manager")
                
                return True
            else:
                self.logger.error("❌ No connection manager available")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Failed to request file {filename}: {e}")
            import traceback
            traceback.print_exc()
            
        return False
    
    def request_file_multiple_methods(self, filename: str) -> bool:
        """Request file using proper packet structure and alternative methods
        
        Args:
            filename: Name of the file to request
            
        Returns:
            True if at least one request was sent successfully
        """
        success_count = 0
        
        # Method 1: Use proper WantFile packet structure
        try:
            if self.request_file(filename):
                success_count += 1
                self.logger.info(f"Sent proper WantFile packet for {filename}")
        except Exception as e:
            self.logger.error(f"WantFile packet failed: {e}")
        
        # Wait briefly between requests
        import time
        time.sleep(0.5)
        
        # Method 2: Try UpdateFile packet (34) if available
        try:
            from pyreborn.packets.outgoing.system.want_file import WantFilePacketHelper
            # Create packet with ID 34 instead of 23
            packet_data = bytearray()
            packet_data.append(34)  # UpdateFile packet ID
            packet_data.extend(filename.encode('latin-1'))
            packet_data.append(0)
            
            if self.connection_manager:
                self.connection_manager.send_packet(bytes(packet_data))
                success_count += 1
                self.logger.info(f"Sent UpdateFile request (ID 34) for {filename}")
        except Exception as e:
            self.logger.error(f"UpdateFile request failed: {e}")
        
        time.sleep(0.5)
        
        # Method 3: Try AdjacentLevel packet (35) - for level files  
        if filename.endswith(('.nw', '.gmap')):
            try:
                from pyreborn.packets.outgoing.core.adjacent_level import AdjacentLevelPacketHelper
                packet = AdjacentLevelPacketHelper.create(filename)
                packet_bytes = packet.to_bytes()
                
                if self.connection_manager:
                    self.connection_manager.send_packet(packet_bytes)
                    success_count += 1
                    self.logger.info(f"Sent AdjacentLevel packet for {filename}")
            except Exception as e:
                self.logger.error(f"AdjacentLevel packet failed: {e}")
            
        return success_count > 0