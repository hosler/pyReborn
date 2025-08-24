"""
Session Packet Manager - Handles session-related packets like player properties

This manager implements IManager to handle session packets:
- PLO_PLAYERPROPS (packet 9) - player properties
- PLO_ADDPLAYER (packet 55) - other player joined
- PLO_DELPLAYER (packet 56) - other player left
- PLO_PLAYERWARP (packet 14) - player movement
- PLO_PLAYERWARP2 (packet 49) - GMAP movement with world coords
"""

import logging
from typing import Dict, Any, Optional
from ..protocol.interfaces import IManager
from ..session.events import EventType

logger = logging.getLogger(__name__)


class SessionPacketManager(IManager):
    """Manager for handling session-related packets"""
    
    def __init__(self):
        self.event_manager = None
        self.config = None
        self.session_manager = None  # Reference to the actual session manager
        self.logger = logger
        
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager"""
        self.config = config
        self.event_manager = event_manager
        logger.info("Session packet manager initialized")
        
    def cleanup(self) -> None:
        """Clean up manager resources"""
        logger.info("Session packet manager cleaned up")
        
    @property
    def name(self) -> str:
        """Get manager name"""
        return "session_packet_manager"
        
    def set_session_manager(self, session_manager):
        """Set reference to the actual session manager"""
        self.session_manager = session_manager
        
    def handle_packet(self, packet_id: int, packet_data: Dict[str, Any]) -> None:
        """Handle incoming session packets"""
        packet_name = packet_data.get('packet_name', 'UNKNOWN')
        
        logger.debug(f"Session packet manager handling packet: {packet_name} ({packet_id})")
        
        # Route based on packet ID
        if packet_id == 9:  # PLO_PLAYERPROPS
            self._handle_player_props(packet_data)
        elif packet_id == 8:  # PLO_OTHERPLPROPS
            self._handle_other_player_props(packet_data)
        elif packet_id == 14:  # PLO_PLAYERWARP
            self._handle_player_warp(packet_data)
        elif packet_id == 49:  # PLO_PLAYERWARP2
            self._handle_player_warp2(packet_data)
        elif packet_id == 55:  # PLO_ADDPLAYER
            self._handle_add_player(packet_data)
        elif packet_id == 56:  # PLO_DELPLAYER
            self._handle_del_player(packet_data)
        else:
            logger.warning(f"Session packet manager received unhandled packet: {packet_name} ({packet_id})")
    
    def _handle_player_props(self, parsed_packet: Dict[str, Any]) -> None:
        """Handle PLO_PLAYERPROPS - main player properties"""
        logger.info("🎯 Received PLO_PLAYERPROPS packet!")
        
        # Get parsed data from packet
        parsed_data = parsed_packet.get('parsed_data', {})
        properties = parsed_data.get('properties', {})
        logger.info(f"Player properties received: {len(properties)} properties")
        
        # Log key properties for debugging
        if 'nickname' in properties:
            logger.info(f"  Nickname: {properties['nickname']}")
        if 'x' in properties:
            logger.info(f"  X: {properties['x']}")
        if 'y' in properties:
            logger.info(f"  Y: {properties['y']}")
        if 'curlevel' in properties:
            logger.info(f"  Level: {properties['curlevel']}")
        
        # 🎯 NEW: Enhanced coordinate tracking with GMAP support
        coordinate_info = parsed_data.get('coordinate_info', {})
        if coordinate_info and coordinate_info.get('in_gmap', False):
            world_pos = coordinate_info.get('world_position', (30.0, 30.0))
            gmap_segment = coordinate_info.get('gmap_segment', (0, 0))
            logger.info(f"🗺️ GMAP coordinates detected: world{world_pos}, segment{gmap_segment}")
            
            # Notify session manager of GMAP coordinates
            if (self.session_manager and 
                hasattr(self.session_manager, 'update_player_coordinates')):
                self.session_manager.update_player_coordinates(
                    world_pos[0], world_pos[1], gmap_segment[0], gmap_segment[1]
                )
                logger.info("✅ Notified session manager of GMAP coordinates")
        
        # Update session manager with the properties
        if self.session_manager and hasattr(self.session_manager, 'player'):
            player_manager = self.session_manager.player
            
            # Update position if available
            x, y = None, None
            level = properties.get('curlevel', None)
            
            # 🎯 NEW: Prioritize world coordinates (x2/y2) for GMAP support
            if 'x2' in properties and 'y2' in properties:
                x = float(properties['x2'])  # x2/y2 are already in tiles
                y = float(properties['y2'])
                logger.info(f"Using world coordinates (x2/y2): ({x:.2f}, {y:.2f})")
            # First try regular coordinates
            elif 'x' in properties and 'y' in properties:
                x = float(properties['x'])
                y = float(properties['y'])
                logger.info(f"Using regular coordinates: ({x}, {y})")
            # Fall back to pixel coordinates (convert from pixels to tiles)
            elif 'pixelx' in properties and 'pixely' in properties:
                x = float(properties['pixelx']) / 16.0  # 16 pixels per tile
                y = float(properties['pixely']) / 16.0
                logger.info(f"Using pixel coordinates: pixelx={properties['pixelx']}, pixely={properties['pixely']} -> tiles=({x:.2f}, {y:.2f})")
            
            # Update position if we found coordinates
            if x is not None and y is not None:
                player_manager.update_position(x, y, level)
                logger.info(f"Updated player position: ({x:.2f}, {y:.2f}) in {level}")
            
            # Update other properties
            for prop_name, value in properties.items():
                player_manager.update_property(prop_name, value)
        
        # Trigger authentication (we got player data, so we're authenticated)
        if self.session_manager:
            # Player ID might be in properties, or use 1 as default
            player_id = properties.get('id', 1)
            if not self.session_manager.is_authenticated():
                self.session_manager.authenticate(player_id)
                logger.info(f"Authentication triggered by PLO_PLAYERPROPS for player ID {player_id}")
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.PLAYER_PROPERTIES_RECEIVED, {
                'properties': properties,
                'parsed_data': parsed_data
            })
    
    def _handle_other_player_props(self, parsed_packet: Dict[str, Any]) -> None:
        """Handle PLO_OTHERPLPROPS - other player properties"""
        logger.debug("Received PLO_OTHERPLPROPS packet")
        
        # Get parsed data from packet
        parsed_data = parsed_packet.get('parsed_data', {})
        player_id = parsed_data.get('player_id', -1)
        properties = parsed_data.get('properties', {})
        
        logger.debug(f"Other player {player_id} properties: {len(properties)} properties")
        
        # Store other player data
        if not hasattr(self.session_manager, 'other_players'):
            self.session_manager.other_players = {}
        
        self.session_manager.other_players[player_id] = properties
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.OTHER_PLAYER_UPDATE, {
                'player_id': player_id,
                'properties': properties,
                'parsed_data': parsed_data
            })
    
    def _handle_player_warp(self, fields: Dict[str, Any]) -> None:
        """Handle PLO_PLAYERWARP - player movement"""
        logger.debug("Received PLO_PLAYERWARP packet")
        
        # Extract movement data
        x = fields.get('x', 0)
        y = fields.get('y', 0)
        
        # Update session manager
        if self.session_manager and hasattr(self.session_manager, 'player'):
            self.session_manager.player.update_position(float(x), float(y))
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.PLAYER_MOVED, {
                'x': x,
                'y': y,
                'fields': fields
            })
    
    def _handle_player_warp2(self, fields: Dict[str, Any]) -> None:
        """Handle PLO_PLAYERWARP2 - GMAP movement with world coordinates"""
        logger.info("🗺️ Received PLO_GMAPWARP2 packet")
        
        # The parsed_data might be nested
        parsed_data = fields.get('parsed_data', fields)
        
        # Extract GMAP data
        gmap_name = parsed_data.get('gmap_name', '')
        world_x = parsed_data.get('x2')  # Now corrected (divided by 2) in packet parser
        world_y = parsed_data.get('y2')  # Now corrected (divided by 2) in packet parser
        segment_x = parsed_data.get('gmaplevelx', 0)
        segment_y = parsed_data.get('gmaplevely', 0)
        
        logger.info(f"🗺️ GMAP Warp: {gmap_name}, segment({segment_x},{segment_y}), world({world_x:.2f},{world_y:.2f})")
        
        # 🎯 CRITICAL: Update session manager with GMAP coordinates
        if (self.session_manager and world_x is not None and world_y is not None and
            hasattr(self.session_manager, 'update_player_coordinates')):
            
            # This will trigger GMAP mode activation and level resolution
            self.session_manager.update_player_coordinates(
                world_x, world_y, segment_x, segment_y
            )
            logger.info("✅ Updated session manager with GMAP coordinates")
            
            # 🎯 FIX: Ensure GMAP manager is also properly enabled
            if (gmap_name and hasattr(self.session_manager, 'gmap_manager') and 
                self.session_manager.gmap_manager):
                gmap_mgr = self.session_manager.gmap_manager
                if not gmap_mgr.is_enabled() and hasattr(gmap_mgr, 'check_and_parse_downloaded_gmap_file'):
                    logger.info(f"🔧 Auto-enabling GMAP manager: {gmap_name}")
                    if gmap_mgr.check_and_parse_downloaded_gmap_file(gmap_name):
                        logger.info(f"✅ GMAP manager now enabled: {gmap_name}")
                    else:
                        logger.warning(f"⚠️ Could not enable GMAP manager: {gmap_name}")
        
        # Update player manager position
        if self.session_manager and hasattr(self.session_manager, 'player'):
            if world_x is not None and world_y is not None:
                # Calculate local coordinates within the segment
                local_x = world_x % 64
                local_y = world_y % 64
                
                self.session_manager.player.update_position(local_x, local_y)
                logger.info(f"Updated player local position: ({local_x:.2f}, {local_y:.2f})")
                
                # Store world and segment coordinates as properties
                self.session_manager.player.update_property('x2', world_x)  # World coordinates
                self.session_manager.player.update_property('y2', world_y)
                self.session_manager.player.update_property('gmaplevelx', segment_x)
                self.session_manager.player.update_property('gmaplevely', segment_y)
                
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.PLAYER_MOVED, {
                'x': world_x if world_x is not None else 0,
                'y': world_y if world_y is not None else 0,
                'world_x': world_x,
                'world_y': world_y,
                'segment_x': segment_x,
                'segment_y': segment_y,
                'gmap_name': gmap_name,
                'fields': fields
            })
    
    def _handle_add_player(self, fields: Dict[str, Any]) -> None:
        """Handle PLO_ADDPLAYER - other player joined"""
        logger.debug("Received PLO_ADDPLAYER packet")
        
        player_id = fields.get('player_id', 0)
        account = fields.get('account', '')
        
        logger.info(f"Player joined: {account} (ID: {player_id})")
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.PLAYER_JOINED, {
                'player_id': player_id,
                'account': account,
                'fields': fields
            })
    
    def _handle_del_player(self, fields: Dict[str, Any]) -> None:
        """Handle PLO_DELPLAYER - other player left"""
        logger.debug("Received PLO_DELPLAYER packet")
        
        player_id = fields.get('player_id', 0)
        
        logger.info(f"Player left: ID {player_id}")
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.PLAYER_LEFT, {
                'player_id': player_id,
                'fields': fields
            })