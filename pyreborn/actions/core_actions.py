"""
Player actions for PyReborn.
Encapsulates all player actions like movement, chat, appearance changes.
"""

import logging
import time
from typing import Optional, TYPE_CHECKING
from ..protocol.enums import PlayerProp, Direction, ClientVersion
from ..protocol.packets import (
    PlayerPropsPacket, ToAllPacket, BombAddPacket,
    ArrowAddPacket, FireSpyPacket, PrivateMessagePacket,
    RequestUpdateBoardPacket, RequestTextPacket, SendTextPacket
)
from ..utils.property_version_manager import get_property_manager

if TYPE_CHECKING:
    from .client import RebornClient

class PlayerActions:
    """Handles all player action methods"""
    
    def __init__(self, client: 'RebornClient'):
        self.client = client
        self._property_sent_callback = None
        from ..utils.logging_config import ModuleLogger
        self.logger = ModuleLogger.get_logger(__name__)
        self._last_property_send_time = 0
        self._property_send_interval = 0.05  # 50ms between any property packets
        self._player_in_warp_areas = set()  # Track which warp areas player is currently in
        self._transition_this_frame = False  # Prevent multiple transitions in one frame
        
    def set_property_sent_callback(self, callback):
        """Set callback to be called when properties are sent"""
        self._property_sent_callback = callback
        
    def _notify_property_sent(self, prop: PlayerProp):
        """Notify callback that a property was sent"""
        if self._property_sent_callback:
            self._property_sent_callback(prop)
            
    def _can_send_property(self) -> bool:
        """Check if enough time has passed to send another property packet"""
        import time
        current_time = time.time()
        if current_time - self._last_property_send_time >= self._property_send_interval:
            self._last_property_send_time = current_time
            return True
        return False
        
    # Movement
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None, check_edges: bool = True):
        """Move to position"""
        if direction is None:
            direction = self.client.local_player.direction
            
        self.logger.debug(f"[MOVE_TO] Called with x={x}, y={y}, current segment=({self.client.local_player.gmaplevelx},{self.client.local_player.gmaplevely})")
        
        # Check if we just completed a transition
        was_transitioning = getattr(self, '_transition_this_frame', False)
        
        # Store original segment before any updates
        original_segment_x = self.client.local_player.gmaplevelx if self.client.local_player else None
        original_segment_y = self.client.local_player.gmaplevely if self.client.local_player else None
        
        # First update position and check for transitions (this may change segment)
        self._update_player_position(x, y, direction, check_edges)
        
        # If we just completed a transition, skip this ONE movement update
        if was_transitioning:
            self.logger.debug("[MOVE] Skipping server update for first movement after transition")
            # Clear the flag now that we've skipped one update
            self._transition_this_frame = False
            return
        
        # Check if segment changed during position update (only relevant in GMAP mode)
        if self.client.is_gmap_mode:
            new_segment_x = self.client.local_player.gmaplevelx if self.client.local_player else None
            new_segment_y = self.client.local_player.gmaplevely if self.client.local_player else None
            segment_changed = (original_segment_x != new_segment_x or original_segment_y != new_segment_y)
            
            if segment_changed:
                self.logger.info(f"[MOVE_TO] Segment changed during movement: ({original_segment_x},{original_segment_y}) -> ({new_segment_x},{new_segment_y})")
                # Don't send movement packet when segment changes - let the transition complete
                return
        
        # Get the actual position after any wrapping/transitions
        actual_x = self.client.local_player.x
        actual_y = self.client.local_player.y
        
        # Check if we need to send to server
        should_send_to_server = True
        if hasattr(self, '_last_sent_x') and hasattr(self, '_last_sent_y') and hasattr(self, '_last_sent_dir'):
            dx = abs(actual_x - self._last_sent_x)
            dy = abs(actual_y - self._last_sent_y)
            if dx < 0.25 and dy < 0.25 and direction == self._last_sent_dir:
                # Position change too small, skip server update but still do local checks
                should_send_to_server = False
            
        if should_send_to_server:
            packet = PlayerPropsPacket()
            
            # Get version string
            version_name = self.client.version_config.name if hasattr(self.client, 'version_config') else "2.1"
            
            # Get property manager to determine which properties to send
            prop_manager = get_property_manager()
            
            # Get the appropriate movement properties for this version
            movement_props = prop_manager.get_movement_properties(version_name, self.client.is_gmap_mode)
            
            # Determine if we should use high-precision coordinates
            use_high_precision = (PlayerProp.PLPROP_X2 in movement_props)
            
            if use_high_precision:
                # New protocol: Send X2/Y2
                
                # Only send X2/Y2 coordinates if GMAP is fully ready or not in GMAP mode
                gmap_ready = hasattr(self.client, 'gmap_manager') and self.client.gmap_manager.is_ready
                in_gmap_mode = self.client.is_gmap_mode
                
                if in_gmap_mode and not gmap_ready:
                    # In GMAP mode but data not ready - skip X2/Y2 coordinates
                    self.logger.info(f"[X2Y2] GMAP mode active but data not ready - skipping X2/Y2 coordinates")
                elif in_gmap_mode and gmap_ready and self.client.local_player:
                    # In GMAP mode with full data ready - send world coordinates
                    gmap_x = self.client.local_player.gmaplevelx
                    gmap_y = self.client.local_player.gmaplevely
                    
                    # Calculate world coordinates: segment * 64 + local position
                    world_x = gmap_x * 64 + actual_x
                    world_y = gmap_y * 64 + actual_y
                    world_x_pixels = int(world_x * 16)
                    world_y_pixels = int(world_y * 16)
                    self.logger.info(f"[X2Y2] GMAP ready - segment: ({gmap_x}, {gmap_y}), local: ({actual_x}, {actual_y})")
                    self.logger.info(f"[X2Y2] Sending world coordinates: ({world_x}, {world_y}) tiles = ({world_x_pixels}, {world_y_pixels}) pixels")
                    packet.add_property(PlayerProp.PLPROP_X2, world_x_pixels)
                    packet.add_property(PlayerProp.PLPROP_Y2, world_y_pixels)
                else:
                    # Not in GMAP mode, send local coordinates as pixels
                    self.logger.info(f"[X2Y2] Sending local coordinates: ({actual_x}, {actual_y}) tiles = ({int(actual_x * 16)}, {int(actual_y * 16)}) pixels")
                    packet.add_property(PlayerProp.PLPROP_X2, int(actual_x * 16))
                    packet.add_property(PlayerProp.PLPROP_Y2, int(actual_y * 16))
                
                # In GMAP mode, also send the segment coordinates AND local coordinates
                if (self.client.is_gmap_mode and 
                    PlayerProp.PLPROP_GMAPLEVELX in movement_props and
                    self.client.local_player and
                    self.client.local_player.gmaplevelx is not None and 
                    self.client.local_player.gmaplevely is not None):
                    self.logger.info(f"[GMAP] Also sending segment coords: ({self.client.local_player.gmaplevelx}, {self.client.local_player.gmaplevely})")
                    packet.add_property(PlayerProp.PLPROP_GMAPLEVELX, self.client.local_player.gmaplevelx)
                    packet.add_property(PlayerProp.PLPROP_GMAPLEVELY, self.client.local_player.gmaplevely)
                    
                # Always send local X/Y coordinates for account saving (even in GMAP mode)
                self.logger.info(f"[LOCAL_XY] Also sending local coordinates: ({actual_x}, {actual_y}) for account saving")
                packet.add_property(PlayerProp.PLPROP_X, actual_x)
                packet.add_property(PlayerProp.PLPROP_Y, actual_y)
                    
                packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
                
                # Notify callbacks for properties we actually sent
                if PlayerProp.PLPROP_X2 in packet.properties:
                    self._notify_property_sent(PlayerProp.PLPROP_X2)
                if PlayerProp.PLPROP_Y2 in packet.properties:
                    self._notify_property_sent(PlayerProp.PLPROP_Y2)
                if PlayerProp.PLPROP_X in packet.properties:
                    self._notify_property_sent(PlayerProp.PLPROP_X)
                if PlayerProp.PLPROP_Y in packet.properties:
                    self._notify_property_sent(PlayerProp.PLPROP_Y)
                self._notify_property_sent(PlayerProp.PLPROP_SPRITE)
                
                # Notify GMAP callbacks if coordinates were sent
                if PlayerProp.PLPROP_GMAPLEVELX in movement_props and PlayerProp.PLPROP_GMAPLEVELX in packet.properties:
                    self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELX)
                    self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELY)
            else:
                # Old protocol: Send X/Y/SPRITE only (but NOT in GMAP mode)
                if not self.client.is_gmap_mode:
                    packet.add_property(PlayerProp.PLPROP_X, actual_x)
                    packet.add_property(PlayerProp.PLPROP_Y, actual_y)
                    packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
                    
                    # Notify callbacks
                    self._notify_property_sent(PlayerProp.PLPROP_X)
                    self._notify_property_sent(PlayerProp.PLPROP_Y)
                    self._notify_property_sent(PlayerProp.PLPROP_SPRITE)
                else:
                    # In GMAP mode with old protocol, we shouldn't send position at all
                    self.logger.warning("[GMAP] In GMAP mode but using old protocol - no position update sent")
                    return
                
            self.client._send_packet(packet)
            
            # Track what we sent
            self._last_sent_x = actual_x
            self._last_sent_y = actual_y
            self._last_sent_dir = direction
        
    def _update_player_position(self, x: float, y: float, direction: Direction, check_edges: bool):
        """Update player position and check for warps"""
        self.logger.info(f"[UPDATE_POS] Called with x={x}, y={y}, check_edges={check_edges}")
        
        # Debug: trace calls
        import traceback
        if x >= 64:
            self.logger.debug(f"[UPDATE_POS] Called with x={x} >= 64!")
            for line in traceback.format_stack()[-5:-1]:
                if 'pyreborn' in line:
                    self.logger.debug(f"  {line.strip()}")
        
        # Store original GMAP coordinates before any changes
        original_gx = getattr(self.client.local_player, 'gmaplevelx', 0) or 0
        original_gy = getattr(self.client.local_player, 'gmaplevely', 0) or 0
        
        # Check for GMAP segment changes first (this updates coordinates)
        if self.client.is_gmap_mode and hasattr(self.client, 'level_manager'):
            self.logger.debug(f"[UPDATE_POS] Checking GMAP segment for x={x}, y={y}")
            wrapped_x, wrapped_y, segment_changed = self._check_gmap_segment_change(x, y)
            # Use wrapped coordinates if segment changed
            if segment_changed:
                self.logger.debug(f"[UPDATE_POS] Segment changed, using wrapped coords: x={wrapped_x}, y={wrapped_y}")
                x = wrapped_x
                y = wrapped_y
        
        # Update local state
        self.client.local_player.x = x
        self.client.local_player.y = y
        self.client.local_player.direction = direction
        
        # Check for edge warps using ORIGINAL coordinates
        # In GMAP mode: Let server handle via GMAP coordinate updates
        # In non-GMAP mode: Check for level links at edges
        if check_edges and not self.client.is_gmap_mode:
            self.check_edge_warp(original_gx, original_gy)
        
        # Reset transition flag for new movement frame
        self._transition_this_frame = False
        
        # Check for level link warps at the new position
        self._check_level_links(x, y)
        
    # Chat
    def set_chat(self, message: str):
        """Set chat bubble"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURCHAT, message)
        self.client._send_packet(packet)
        self.client.local_player.chat = message
        
    def say(self, message: str):
        """Send chat message to all"""
        packet = ToAllPacket(message)
        self.client._send_packet(packet)
        
    def send_pm(self, player_id: int, message: str):
        """Send private message"""
        packet = PrivateMessagePacket(player_id, message)
        self.client._send_packet(packet)
        
    # Appearance
    def set_nickname(self, nickname: str):
        """Set nickname"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_NICKNAME, nickname)
        self.client._send_packet(packet)
        self._notify_property_sent(PlayerProp.PLPROP_NICKNAME)
        self.client.local_player.nickname = nickname
        
    def set_current_level(self, level_name: str):
        """Set current level property to notify server"""
        # Always send the actual level name (e.g., "chicken1.nw")
        # The server needs to know which specific segment we're in, not just the GMAP name
        level_to_send = level_name
        self.logger.debug(f"[ACTIONS] Setting current level to: {level_name}")
            
        # Don't send redundant updates
        if hasattr(self, '_last_sent_level') and self._last_sent_level == level_to_send:
            return
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURLEVEL, level_to_send)
        self.client._send_packet(packet)
        self._notify_property_sent(PlayerProp.PLPROP_CURLEVEL)
        self._last_sent_level = level_to_send
        self.logger.debug(f"[ACTIONS] Set current level property to: {level_to_send}")
        
    def set_head_image(self, image: str):
        """Set head image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_HEADGIF, image)
        self.client._send_packet(packet)
        self.client.local_player.head_image = image
        
    def set_body_image(self, image: str):
        """Set body image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BODYIMG, image)
        self.client._send_packet(packet)
        self.client.local_player.body_image = image
        
    def set_colors(self, colors: list):
        """Set player colors"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_COLORS, colors)
        self.client._send_packet(packet)
        self.client.local_player.colors = colors
        
    def set_gani(self, gani: str):
        """Set animation (gani)"""
        # Don't send redundant updates
        if self.client.local_player.gani == gani:
            return
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_GANI, gani)
        self.client._send_packet(packet)
        self._notify_property_sent(PlayerProp.PLPROP_GANI)
        self.client.local_player.gani = gani
        
    def set_carry_sprite(self, sprite_id: int):
        """Set carry sprite (item being carried)
        
        Args:
            sprite_id: The sprite ID to carry (-1 for none)
        """
        # Don't send redundant updates
        if self.client.local_player.carry_sprite == sprite_id:
            return
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CARRYSPRITE, sprite_id)
        self.client._send_packet(packet)
        self.client.local_player.carry_sprite = sprite_id
    
    def send_initial_properties(self):
        """Send initial properties after login (OSTYPE, TEXTCODEPAGE, UDPPORT)"""
        packet = PlayerPropsPacket()
        
        # Operating system type
        import platform
        os_type = "wind" if platform.system() == "Windows" else "linux"
        packet.add_property(PlayerProp.PLPROP_OSTYPE, os_type)
        
        # Text encoding code page (1252 = Western European)
        packet.add_property(PlayerProp.PLPROP_TEXTCODEPAGE, 1252)
        
        # UDP port (0 = no UDP support)
        packet.add_property(PlayerProp.PLPROP_UDPPORT, 0)
        
        self.client._send_packet(packet)
        self.logger.info(f"[ACTIONS] Sent initial properties: OS={os_type}, CodePage=1252, UDPPort=0")
    
    def set_gmap_position(self, gmap_x: int, gmap_y: int):
        """Set GMAP segment position when changing levels"""
        # Don't send redundant updates
        if (hasattr(self, '_last_sent_gmap_x') and hasattr(self, '_last_sent_gmap_y') and
            self._last_sent_gmap_x == gmap_x and self._last_sent_gmap_y == gmap_y):
            return
            
        # Check if version supports GMAP properties
        version_name = self.client.version_config.name if hasattr(self.client, 'version_config') else "2.1"
        prop_manager = get_property_manager()
        
        if not prop_manager.is_property_supported(PlayerProp.PLPROP_GMAPLEVELX, version_name):
            self.logger.debug(f"[ACTIONS] Version {version_name} doesn't support GMAP properties, skipping")
            return
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_GMAPLEVELX, gmap_x)
        packet.add_property(PlayerProp.PLPROP_GMAPLEVELY, gmap_y)
        self.client._send_packet(packet)
        self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELX)
        self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELY)
        self._last_sent_gmap_x = gmap_x
        self._last_sent_gmap_y = gmap_y
        self.logger.debug(f"[ACTIONS] Set GMAP position to: ({gmap_x}, {gmap_y})")
    
    def set_player_status(self, status_flags: int):
        """Set player status flags (paused, hidden, male, dead, etc.)"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_STATUS, status_flags)
        self.client._send_packet(packet)
        self.logger.debug(f"[ACTIONS] Set player status flags to: {status_flags}")
        
    # Combat
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, power: int = 1):
        """Drop a bomb"""
        if x is None:
            x = self.client.local_player.x
        if y is None:
            y = self.client.local_player.y
        packet = BombAddPacket(x, y, power)
        self.client._send_packet(packet)
        
    def shoot_arrow(self):
        """Shoot an arrow"""
        packet = ArrowAddPacket()
        self.client._send_packet(packet)
        
    def fire_effect(self):
        """Fire effect"""
        packet = FireSpyPacket()
        self.client._send_packet(packet)
        
    # Items
    def set_arrows(self, count: int):
        """Set arrow count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_ARROWSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.arrows = count
        
    def set_bombs(self, count: int):
        """Set bomb count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BOMBSCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.bombs = count
        
    def set_rupees(self, count: int):
        """Set rupee count"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_RUPEESCOUNT, count)
        self.client._send_packet(packet)
        self.client.local_player.rupees = count
        
    def set_hearts(self, current: float, maximum: Optional[float] = None):
        """Set hearts"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURPOWER, current)
        if maximum is not None:
            packet.add_property(PlayerProp.PLPROP_MAXPOWER, maximum)
        self.client._send_packet(packet)
        self.client.local_player.hearts = current
        if maximum is not None:
            self.client.local_player.max_hearts = maximum
            
    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.0, use_serverwarp: bool = False):
        """Warp to a specific level
        
        Args:
            level_name: Target level name
            x: X coordinate in target level
            y: Y coordinate in target level
            use_serverwarp: Use PLI_SERVERWARP instead of PLI_LEVELWARP
        """
        from ..protocol.enums import PlayerToServer
        
        # Ensure level name has .nw extension if not a gmap
        if not level_name.endswith('.nw') and not level_name.endswith('.gmap'):
            level_name = f"{level_name}.nw"
        
        # Build warp packet manually
        # Format: ID + x*2 + y*2 + level_name
        packet_data = bytearray()
        
        if use_serverwarp:
            # Try PLI_SERVERWARP (41)
            packet_data.append(PlayerToServer.PLI_SERVERWARP + 32)
            self.logger.debug(f"Using PLI_SERVERWARP to warp to '{level_name}' at ({x}, {y})")
        else:
            # Use standard PLI_LEVELWARP (0)
            packet_data.append(PlayerToServer.PLI_LEVELWARP + 32)
            self.logger.debug(f"Using PLI_LEVELWARP to warp to '{level_name}' at ({x}, {y})")
            
        # Convert pixel coordinates to wire format (pixel / 2)
        # The protocol expects coordinates in the same format as movement packets
        wire_x = int(x * 2)  # Convert to wire format
        wire_y = int(y * 2)  # Convert to wire format
        packet_data.append(wire_x + 32)  # x coordinate + 32
        packet_data.append(wire_y + 32)  # y coordinate + 32
        
        # Add level name as null-terminated string (not gstring)
        level_bytes = level_name.encode('ascii')
        packet_data.extend(level_bytes)
        packet_data.append(0)  # null terminator
        
        self.client.queue_packet(bytes(packet_data))
        
        # Send current level property to notify server
        self.set_current_level(level_name)
        
        # Don't automatically request files - let the server send them
        # Requesting non-existent files may cause server to disconnect us
        self.logger.debug(f"[WARP] Not auto-requesting file for {level_name} - waiting for server")
        
    def request_adjacent_level(self, x: int, y: int):
        """Request adjacent level data for gmap streaming
        
        Args:
            x: X offset (-1, 0, or 1)
            y: Y offset (-1, 0, or 1)
        """
        from ..protocol.enums import PlayerToServer
        
        # Build adjacent level request packet
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_ADJACENTLEVEL + 32)
        packet_data.append(x + 32)  # X offset + 32
        packet_data.append(y + 32)  # Y offset + 32
        
        self.client.queue_packet(bytes(packet_data))
        self.logger.debug(f"Requesting adjacent level at offset ({x}, {y})")
        
    def get_gmap_position(self) -> tuple:
        """Get current GMAP segment position
        
        Returns:
            (gmaplevelx, gmaplevely, x2, y2) or None if not in a gmap
        """
        if not self.client.local_player:
            return None
            
        player = self.client.local_player
        gmaplevelx = getattr(player, 'gmaplevelx', None)
        gmaplevely = getattr(player, 'gmaplevely', None)
        x2 = getattr(player, 'x2', None)
        y2 = getattr(player, 'y2', None)
        
        if gmaplevelx is not None and gmaplevely is not None:
            return (gmaplevelx, gmaplevely, x2 or 0, y2 or 0)
        return None
    
    def _check_gmap_segment_change(self, x: float, y: float):
        """Check if player has moved to a new GMAP segment
        
        Args:
            x: Current local x position  
            y: Current local y position
            
        Returns:
            (wrapped_x, wrapped_y, segment_changed) tuple
        """
        
        # Check if we've crossed a segment boundary
        if not self.client.local_player:
            return x, y, False
            
        current_gx = self.client.local_player.gmaplevelx or 0
        current_gy = self.client.local_player.gmaplevely or 0
        
        # Calculate which segment this position should be in based on the raw position
        # Don't modify the position multiple times
        wrapped_x = x
        wrapped_y = y
        new_gx = current_gx
        new_gy = current_gy
        
        # Only check for segment changes if we're at exact boundaries
        # This prevents double-processing
        if x < 0:
            new_gx = current_gx - 1
            wrapped_x = x + 64  # Wrap to other side
        elif x >= 64:
            new_gx = current_gx + 1
            wrapped_x = x - 64  # Wrap to other side
            self.logger.info(f"[GMAP] Boundary cross at x={x}: segment {current_gx} -> {new_gx}, wrapped x={wrapped_x}")
            
        if y < 0:
            new_gy = current_gy - 1
            wrapped_y = y + 64  # Wrap to other side
        elif y >= 64:
            new_gy = current_gy + 1
            wrapped_y = y - 64  # Wrap to other side
            
        # Update segment if changed
        segment_changed = (new_gx != current_gx or new_gy != current_gy)
        if segment_changed:
            self.logger.info(f"[GMAP] Segment boundary crossed: ({current_gx},{current_gy}) -> ({new_gx},{new_gy})")
            self.client.local_player.gmaplevelx = new_gx
            self.client.local_player.gmaplevely = new_gy
            
            # In GMAP mode, we need to send the GMAP name as current level when segment changes
            if self.client.level_manager.current_gmap:
                self.set_current_level(self.client.level_manager.current_gmap)
                self.logger.debug(f"[GMAP] Sending current level as GMAP: {self.client.level_manager.current_gmap}")
                
            # Update the level manager's current level to the new segment
            # Try both gmap_manager and level_manager for GMAP data
            gmap_data = None
            if self.client.gmap_manager and self.client.gmap_manager.current_gmap:
                self.logger.debug(f"[GMAP] Checking gmap_manager for segment ({new_gx},{new_gy})")
                gmap_data = self.client.gmap_manager.gmaps.get(self.client.gmap_manager.current_gmap)
                if gmap_data:
                    self.logger.debug(f"[GMAP] Found GMAP data in gmap_manager")
                else:
                    self.logger.debug(f"[GMAP] No GMAP data in gmap_manager, checking level_manager")
                    
            # Fallback to level_manager if gmap_manager doesn't have data
            if not gmap_data and hasattr(self.client, 'level_manager'):
                gmap_name = self.client.gmap_manager.current_gmap if self.client.gmap_manager else None
                if gmap_name and gmap_name in self.client.level_manager.gmap_data:
                    parser = self.client.level_manager.gmap_data[gmap_name]
                    self.logger.debug(f"[GMAP] Found GMAP data in level_manager with {len(parser.segments)} segments")
                    # Convert parser data to segment lookup
                    if (new_gx, new_gy) in range(parser.width) and (new_gy) in range(parser.height):
                        idx = new_gy * parser.width + new_gx
                        if idx < len(parser.segments):
                            new_level_name = parser.segments[idx]
                            if new_level_name:
                                self.logger.info(f"[GMAP] Updating level manager to new segment level: {new_level_name}")
                                # Check if we have this level loaded
                                if self.client.level_manager.has_level_data(new_level_name):
                                    self.client.level_manager.set_current_level(new_level_name)
                                    self.logger.info(f"[GMAP] Successfully updated current level to: {new_level_name}")
                                else:
                                    self.logger.warning(f"[GMAP] New segment level {new_level_name} not loaded yet")
                            else:
                                self.logger.warning(f"[GMAP] Empty segment at ({new_gx},{new_gy})")
                        else:
                            self.logger.warning(f"[GMAP] Segment index {idx} out of range (max {len(parser.segments)})")
                    else:
                        self.logger.warning(f"[GMAP] Segment ({new_gx},{new_gy}) out of bounds ({parser.width}x{parser.height})")
                else:
                    self.logger.warning(f"[GMAP] No GMAP data found in either manager")
            elif gmap_data:
                # Use gmap_manager data
                if (new_gx, new_gy) in gmap_data.segments:
                    new_level_name = gmap_data.segments[(new_gx, new_gy)]
                    self.logger.info(f"[GMAP] Updating level manager to new segment level: {new_level_name}")
                    # Check if we have this level loaded
                    if self.client.level_manager.has_level_data(new_level_name):
                        self.client.level_manager.set_current_level(new_level_name)
                        self.logger.info(f"[GMAP] Successfully updated current level to: {new_level_name}")
                    else:
                        self.logger.warning(f"[GMAP] New segment level {new_level_name} not loaded yet")
                else:
                    self.logger.warning(f"[GMAP] Segment ({new_gx},{new_gy}) not found in GMAP data")
            
        return wrapped_x, wrapped_y, segment_changed
    
    def _send_gmap_coordinates(self, gmapx: int, gmapy: int):
        """Send GMAP coordinate update to server
        
        Args:
            gmapx: GMAP X segment coordinate
            gmapy: GMAP Y segment coordinate
        """
        # Check if version supports GMAP properties
        version_name = self.client.version_config.name if hasattr(self.client, 'version_config') else "2.1"
        prop_manager = get_property_manager()
        
        if not prop_manager.is_property_supported(PlayerProp.PLPROP_GMAPLEVELX, version_name):
            self.logger.debug(f"[GMAP] Version {version_name} doesn't support GMAP properties, skipping coordinate update")
            return
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_GMAPLEVELX, gmapx)
        packet.add_property(PlayerProp.PLPROP_GMAPLEVELY, gmapy)
        
        self.client._send_packet(packet)
        self.logger.info(f"Sent GMAP coordinates to server: [{gmapx}, {gmapy}]")
        
        # Notify callbacks
        self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELX)
        self._notify_property_sent(PlayerProp.PLPROP_GMAPLEVELY)
    
    # New GServer-V2 features
    def request_board_update(self, level: str, x: int, y: int, width: int, height: int, mod_time: int = 0):
        """Request partial board update for a level region"""
        packet = RequestUpdateBoardPacket(level, mod_time, x, y, width, height)
        self.client._send_packet(packet)
    
    def request_text(self, key: str):
        """Request a text value from the server"""
        packet = RequestTextPacket(key)
        self.client._send_packet(packet)
    
    def send_text(self, key: str, value: str):
        """Send a text value to the server"""
        packet = SendTextPacket(key, value)
        self.client._send_packet(packet)
    
    def set_group(self, group: str):
        """Set player group (for group maps)"""
        # Store locally - server handles via triggeraction
        self.client.local_player.group = group
    
    def move_with_precision(self, x: float, y: float, z: float = 0.0, direction: Optional[Direction] = None):
        """Move using high-precision coordinates"""
        if direction is None:
            direction = self.client.local_player.direction
            
        packet = PlayerPropsPacket()
        # Use high-precision properties
        packet.add_property(PlayerProp.PLPROP_X2, int(x * 16))
        packet.add_property(PlayerProp.PLPROP_Y2, int(y * 16))
        packet.add_property(PlayerProp.PLPROP_Z2, int(z))
        packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
        self.client._send_packet(packet)
        
        # Update local state
        self.client.local_player.x = x
        self.client.local_player.y = y
        self.client.local_player.z = z
        self.client.local_player.direction = direction
    
    def _should_disable_edge_link(self, link) -> bool:
        """Check if this edge link should be disabled in GMAP mode
        
        Returns True if:
        - We're in GMAP mode with an active GMAP
        - The link is at an edge and spans most of that edge
        - The destination is another segment in the same GMAP
        """
        # Only check in GMAP mode with active GMAP
        if not (self.client.is_gmap_mode and self.client.level_manager.current_gmap):
            return False
            
        # Check if it's a full edge link (with tolerance)
        is_full_edge = False
        
        # Left edge: x=0, height >= 62
        if link.x == 0 and link.height >= 62:
            is_full_edge = True
        # Right edge: extends to x >= 63, height >= 62
        elif link.x + link.width >= 63 and link.height >= 62:
            is_full_edge = True
        # Top edge: y=0, width >= 62
        elif link.y == 0 and link.width >= 62:
            is_full_edge = True
        # Bottom edge: extends to y >= 63, width >= 62
        elif link.y + link.height >= 63 and link.width >= 62:
            is_full_edge = True
            
        if not is_full_edge:
            return False
            
        # Check if destination is in the same GMAP
        current_gmap_name = self.client.level_manager.current_gmap
        # Remove .gmap extension if present
        if current_gmap_name and current_gmap_name.endswith('.gmap'):
            current_gmap_name = current_gmap_name[:-5]
        gmap_parser = self.client.level_manager.gmap_data.get(current_gmap_name)
        
        if not gmap_parser:
            return False
            
        # Check if destination is a segment in this GMAP
        if link.dest_level in gmap_parser.segments:
            self.logger.info(f"[EDGE_LINK] Disabling GMAP edge link: {self.client.level_manager.current_level.name} -> {link.dest_level}")
            return True
            
        return False
    
    def _check_level_links(self, x: float, y: float):
        """Check if player position triggers a level link warp"""
        self.logger.info(f"[LINK_CHECK] Called at ({x:.1f}, {y:.1f}), GMAP mode: {self.client.is_gmap_mode}")
        
        # Only check if we have a level manager and current level
        if not hasattr(self.client, 'level_manager') or not self.client.level_manager.current_level:
            self.logger.debug(f"[LINK_CHECK] No level manager or current level")
            return
            
        # Initialize warp areas on first check for a new level
        level = self.client.level_manager.current_level
        if not hasattr(self, '_last_checked_level') or self._last_checked_level != level.name:
            self._last_checked_level = level.name
            self._player_in_warp_areas.clear()
            
            # Check if player is already in any warp areas
            for i, link in enumerate(level.links):
                if (x >= link.x and x < link.x + link.width and 
                    y >= link.y and y < link.y + link.height):
                    self._player_in_warp_areas.add(i)
                    self.logger.info(f"[LINK_CHECK] Player already in warp area {i} on level entry")
            
            self.logger.info(f"[LINK_CHECK] Initialized warp areas for {level.name}, player in {len(self._player_in_warp_areas)} areas")
            
        # In GMAP mode, level links should still work for warping into non-GMAP levels
        # Only skip GMAP-to-GMAP segment transitions (those are handled by coordinate wrapping)
        # But allow GMAP-to-level warps (houses, dungeons, etc.)
        self.logger.info(f"[LINK_CHECK] Current level: {self.client.level_manager.current_level.name}, links: {len(self.client.level_manager.current_level.links)}")
            
        # Prevent multiple transitions in the same movement frame
        if self._transition_this_frame:
            return
            
        # For positions outside level bounds, check edge links by clamping to valid coordinates
        check_x, check_y = x, y
        if x < 0:
            check_x = 0.5  # Just inside west edge
        elif x >= 64:
            check_x = 63.5  # Just inside east edge
        if y < 0:
            check_y = 0.5  # Just inside north edge  
        elif y >= 64:
            check_y = 63.5  # Just inside south edge
            
        # Debug: Log every call to ensure it's being called
        if hasattr(self, '_link_check_counter'):
            self._link_check_counter += 1
        else:
            self._link_check_counter = 0
            
        if self._link_check_counter % 20 == 0:  # Every 20 calls
            self.logger.info(f"[LINK_CHECK] Called at ({x:.1f},{y:.1f}) - call #{self._link_check_counter}")
            
        level = self.client.level_manager.current_level
        current_warp_areas = set()
        
        # Check all links in the current level
        for i, link in enumerate(level.links):
            # Special debug for house links
            if "house" in link.dest_level.lower() and abs(x - link.x) < 5 and abs(y - link.y) < 5:
                self.logger.info(f"[HOUSE_LINK] Near house link {i}: player at ({x:.1f},{y:.1f}), link at ({link.x},{link.y}) size {link.width}x{link.height}")
                self.logger.info(f"[HOUSE_LINK] In bounds check: x {x} >= {link.x} and < {link.x + link.width} = {x >= link.x and x < link.x + link.width}")
                self.logger.info(f"[HOUSE_LINK] In bounds check: y {y} >= {link.y} and < {link.y + link.height} = {y >= link.y and y < link.y + link.height}")
            
            # Check if player is within the link area (using clamped coordinates for edge detection)
            if (check_x >= link.x and check_x < link.x + link.width and 
                check_y >= link.y and check_y < link.y + link.height):
                # Player is in a link area
                current_warp_areas.add(i)
                self.logger.info(f"Player in link area {i}: {link.dest_level} at ({link.x},{link.y}) size {link.width}x{link.height}")
                
                # Only trigger warp if player just entered this area (wasn't in it before)
                if i not in self._player_in_warp_areas:
                    # Check if this is a GMAP edge link that should be disabled
                    if self._should_disable_edge_link(link):
                        self.logger.info(f"[LINK_CHECK] Skipping disabled GMAP edge link to {link.dest_level}")
                        continue
                    # Handle special playerx/playery values
                    if link.dest_x is None or (isinstance(link.dest_x, str) and link.dest_x in ('playerx', '-1')):
                        dest_x = x
                    else:
                        dest_x = float(link.dest_x) if isinstance(link.dest_x, str) else link.dest_x
                        
                    if link.dest_y is None or (isinstance(link.dest_y, str) and link.dest_y in ('playery', '-1')):
                        dest_y = y
                    else:
                        dest_y = float(link.dest_y) if isinstance(link.dest_y, str) else link.dest_y
                    
                    
                    # Format destination coords (might be None for playerx/playery)
                    dest_x_str = f"{dest_x:.1f}" if dest_x is not None else "playerx"
                    dest_y_str = f"{dest_y:.1f}" if dest_y is not None else "playery"
                    link_type = "edge" if (link.x == 0 or link.y == 0 or link.x + link.width >= 64 or link.y + link.height >= 64) else "interior"
                    self.logger.info(f"Player entered {link_type} level link at ({x:.1f}, {y:.1f}) -> {link.dest_level} at ({dest_x_str}, {dest_y_str})")
                    
                    # Determine if this is a GMAP-to-GMAP transition or GMAP-to-level transition
                    is_gmap_to_gmap = self.client.is_gmap_mode and link.dest_level.endswith('.gmap')
                    
                    # Handle GMAP-to-level and non-GMAP transitions client-side
                    # Only GMAP-to-GMAP transitions are handled by server/coordinate wrapping
                    if not is_gmap_to_gmap:
                        if self.client.is_gmap_mode:
                            self.logger.info(f"GMAP-to-level transition to {link.dest_level}")
                        else:
                            self.logger.info(f"Client-side level transition to {link.dest_level}")
                        
                        # Send warp packet to server - this is the proper way to warp
                        self.logger.info(f"Sending PLI_LEVELWARP packet for {link.dest_level} at ({dest_x}, {dest_y})")
                        self.warp_to_level(link.dest_level, dest_x, dest_y)
                        
                        # Set transition flag to prevent movement updates during warp
                        self._transition_this_frame = True
                        self._player_in_warp_areas.clear()
                        # Find any warp areas at the destination position and mark them as "already in"
                        dest_level_obj = self.client.level_manager.levels.get(link.dest_level)
                        if dest_level_obj:
                            for j, dest_link in enumerate(dest_level_obj.links):
                                if (dest_x >= dest_link.x and dest_x < dest_link.x + dest_link.width and 
                                    dest_y >= dest_link.y and dest_y < dest_link.y + dest_link.height):
                                    self._player_in_warp_areas.add(j)
                                    self.logger.debug(f"Pre-marked warp area {j} as occupied at destination")
                        
                        self.logger.info(f"Client-side transition complete to {link.dest_level}")
                        return  # Exit after successful transition
                    else:
                        # GMAP-to-GMAP transitions are handled by coordinate wrapping system
                        self.logger.info(f"GMAP-to-GMAP transition to {link.dest_level} - handled by coordinate wrapping")
                        
        # Update the set of warp areas the player is currently in
        self._player_in_warp_areas = current_warp_areas
        
        # Debug: Log position and nearby links every few calls (to avoid spam)
        if hasattr(self, '_debug_counter'):
            self._debug_counter += 1
        else:
            self._debug_counter = 0
            
        if self._debug_counter % 30 == 0:  # Every 30 calls (~1-2 seconds)
            if level and level.links:
                self.logger.debug(f"Player at ({x:.1f},{y:.1f}) in {level.name}, {len(current_warp_areas)} active areas")
                for i, link in enumerate(level.links):
                    # Show links within reasonable distance
                    if abs(x - (link.x + link.width/2)) < 10 and abs(y - (link.y + link.height/2)) < 10:
                        distance = ((x - (link.x + link.width/2))**2 + (y - (link.y + link.height/2))**2)**0.5
                        self.logger.debug(f"  Nearby link {i}: {link.dest_level} at ({link.x},{link.y}) size {link.width}x{link.height}, distance {distance:.1f}")
                
    def check_edge_warp(self, original_gx=None, original_gy=None):
        """Check if player is at level edge and should warp
        
        In traditional Graal, levels are 64x64 tiles and players warp when
        moving beyond the edges.
        
        Args:
            original_gx: Original GMAP X coordinate before any updates
            original_gy: Original GMAP Y coordinate before any updates
        """
        if not self.client.local_player:
            return
            
        x = self.client.local_player.x
        y = self.client.local_player.y
        
        # Check if at edge (levels are 64 tiles, 0-63)
        edge_triggered = False
        new_x, new_y = x, y
        offset_x, offset_y = 0, 0
        
        if x < 0:
            # West edge
            offset_x = -1
            new_x = 63 + x  # Wrap to east side
            edge_triggered = True
        elif x >= 64:
            # East edge  
            offset_x = 1
            new_x = x - 64  # Wrap to west side
            edge_triggered = True
            
        if y < 0:
            # North edge
            offset_y = -1
            new_y = 63 + y  # Wrap to south side
            edge_triggered = True
        elif y >= 64:
            # South edge
            offset_y = 1 
            new_y = y - 64  # Wrap to north side
            edge_triggered = True
            
        if edge_triggered:
            # In a GMAP, let server handle the transition
            if hasattr(self.client, 'level_manager'):
                if self.client.is_gmap_mode:
                    self.logger.info(f"Edge warp in GMAP: position ({x}, {y}) -> ({new_x}, {new_y})")
                    
                    # Calculate expected target segment using original coordinates
                    current_level = self.client.level_manager.current_level
                    if current_level and original_gx is not None and original_gy is not None:
                        current_gx = original_gx
                        current_gy = original_gy
                        
                        # Calculate new segment position
                        new_gx = current_gx + offset_x
                        new_gy = current_gy + offset_y
                        
                        # Try to determine expected level name from GMAP data
                        expected_level = None
                        if self.client.level_manager.current_gmap:
                            gmap_name = self.client.level_manager.current_gmap.replace('.gmap', '')
                            gmap_data = self.client.level_manager.gmap_data.get(gmap_name)
                            if gmap_data and hasattr(gmap_data, 'segments'):
                                index = new_gy * gmap_data.width + new_gx
                                if 0 <= index < len(gmap_data.segments):
                                    expected_level = gmap_data.segments[index]
                        
                        self.logger.info(f"GMAP transition: [{current_gx},{current_gy}] -> [{new_gx},{new_gy}] (expected: {expected_level})")
                        
                        # Mark that we're starting a transition with expected level
                        self.client.level_manager.start_edge_transition(expected_level)
                    else:
                        # Fallback - no GMAP coordinates available
                        self.client.level_manager.start_edge_transition()
                    
                    # Update local position to wrapped coordinates
                    self.client.local_player.x = new_x
                    self.client.local_player.y = new_y
                    
                    # Send the new position to server (without checking edges again)
                    self.move_to(new_x, new_y, self.client.local_player.direction, check_edges=False)
                    
                    # Request adjacent level in the direction we're moving
                    self.request_adjacent_level(offset_x, offset_y)
                else:
                    # For regular levels (non-GMAP mode), check for level links at the edge
                    level_name = self.client.level_manager.current_level.name if self.client.level_manager.current_level else "unknown"
                    self.logger.info(f"Edge reached in non-GMAP level {level_name} at ({x:.1f}, {y:.1f})")
                    
                    # Look for level links at the edge position
                    # In traditional Graal, edge warps happen when you walk off the edge
                    # The link should be at the edge tile (0, 63, etc.)
                    edge_x = x
                    edge_y = y
                    
                    # Adjust position to be on the edge tile for link checking
                    if x < 0:
                        edge_x = 0
                    elif x >= 64:
                        edge_x = 63
                    if y < 0:
                        edge_y = 0
                    elif y >= 64:
                        edge_y = 63
                    
                    # Check for links at the edge position
                    # Also check for links that might be placed outside normal bounds
                    links = []
                    
                    # First check normal position
                    links = self.client.level_manager.find_level_links_at(edge_x, edge_y)
                    
                    # If no links found and we're at an edge, check for out-of-bounds links
                    if not links and self.client.level_manager.current_level:
                        # Check all links to see if any are meant for this edge
                        for link in self.client.level_manager.current_level.links:
                            # Links at coordinates >= 64 are edge links
                            if link.x >= 64 or link.y >= 64:
                                # Check which edge this link is for based on its position
                                if x < 0 and link.x < 4:  # West edge - link at x=0-3
                                    links.append(link)
                                elif x >= 64 and link.x >= 64:  # East edge - link at x>=64
                                    links.append(link)
                                elif y < 0 and link.y < 4:  # North edge - link at y=0-3  
                                    links.append(link)
                                elif y >= 64 and link.y >= 64:  # South edge - link at y>=64
                                    links.append(link)
                                    
                    if links:
                        # Use the first link found
                        link = links[0]
                        # Handle playerx/playery - None means keep player position
                        # For edge warps, use the wrapped position on the new level
                        if link.dest_x is None:
                            # Use current player x, or wrapped position if at edge
                            dest_x = self.client.local_player.x if -1 <= self.client.local_player.x <= 64 else new_x
                        else:
                            dest_x = link.dest_x
                            
                        if link.dest_y is None:
                            # Use current player y, or wrapped position if at edge
                            dest_y = self.client.local_player.y if -1 <= self.client.local_player.y <= 64 else new_y
                        else:
                            dest_y = link.dest_y
                        
                        self.logger.info(f"Found edge link to {link.dest_level} at ({dest_x:.1f}, {dest_y:.1f})")
                        
                        # For non-GMAP mode, handle client-side level transition
                        if not self.client.is_gmap_mode:
                            self.logger.info(f"Client-side edge transition to {link.dest_level}")
                            
                            # Request the level file if we don't have it
                            if not self.client.level_manager.has_level_data(link.dest_level):
                                self.logger.info(f"Requesting level file: {link.dest_level}")
                                self.client.level_manager.request_file(link.dest_level)
                            
                            # Update our local state
                            self.client.level_manager.set_current_level(link.dest_level)
                            self.client.local_player.level = link.dest_level
                            self.client.local_player.x = dest_x
                            self.client.local_player.y = dest_y
                            
                            # Send updated properties to server
                            packet = PlayerPropsPacket()
                            packet.add_property(PlayerProp.PLPROP_CURLEVEL, link.dest_level)
                            self.client._send_packet(packet)
                            
                            # Request board data for the new level (only if we don't have it)
                            dest_level_obj = self.client.level_manager.levels.get(link.dest_level)
                            if not dest_level_obj or not dest_level_obj.board_data:
                                board_request = RequestUpdateBoardPacket(
                                    level=link.dest_level,
                                    mod_time=0,  # Request full level data
                                    x=0, y=0, width=64, height=64  # Full level (64x64)
                                )
                                self.client._send_packet(board_request)
                                self.logger.info(f"Requested board data for {link.dest_level} (edge warp)")
                            else:
                                self.logger.info(f"Board data already available for {link.dest_level}, skipping request (edge warp)")
                            
                            # Set transition flag and clear warp areas for new level
                            self._transition_this_frame = True
                            self._player_in_warp_areas.clear()
                            # Find any warp areas at the destination position and mark them as "already in"
                            dest_level_obj = self.client.level_manager.levels.get(link.dest_level)
                            if dest_level_obj:
                                for j, dest_link in enumerate(dest_level_obj.links):
                                    if (dest_x >= dest_link.x and dest_x < dest_link.x + dest_link.width and 
                                        dest_y >= dest_link.y and dest_y < dest_link.y + dest_link.height):
                                        self._player_in_warp_areas.add(j)
                                        self.logger.debug(f"Pre-marked warp area {j} as occupied at destination (edge warp)")
                            
                            self.logger.info(f"Client-side edge transition complete to {link.dest_level}")
                        else:
                            # In GMAP mode, server handles edge transitions
                            self.logger.info("At edge with link - server should handle transition")
                    else:
                        self.logger.info(f"No level link found at edge - player stops at boundary")