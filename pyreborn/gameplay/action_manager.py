"""
Modern Action Manager for ModularRebornClient

This replaces the legacy PlayerActions class with a clean implementation
that uses the proper manager interfaces from ModularRebornClient.
"""

import logging
import time
from typing import Optional, Set, TYPE_CHECKING, List

from pyreborn.protocol.enums import PlayerProp, Direction
from ..packets.outgoing.core.player_props import PlayerPropsPacketHelper

if TYPE_CHECKING:
    from .modular_client import ModularRebornClient


class ActionManager:
    """Modern action manager that uses ModularRebornClient's manager interfaces"""
    
    def __init__(self, client: 'ModularRebornClient'):
        """Initialize the action manager
        
        Args:
            client: ModularRebornClient instance
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        # Quick references to managers
        self._session = client.session_manager
        self._levels = client.level_manager
        self._gmap = client.gmap_manager
        self._items = client.item_manager
        
        # Movement state tracking
        self._last_sent_x: Optional[float] = None
        self._last_sent_y: Optional[float] = None
        self._last_sent_dir: Optional[Direction] = None
        self._last_sent_gani: Optional[str] = None
        self._last_property_send_time = 0.0
        self._property_send_interval = 0.05  # 50ms between property packets
        
        # Level links state
        self._player_in_warp_areas: Set[int] = set()
        self._transition_this_frame = False
        self._last_checked_level: Optional[str] = None
        
        self.logger.debug("Modern ActionManager initialized")
    
    # === Movement Actions ===
    
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None, update_gani: bool = True) -> None:
        """Move player to position using modern manager interfaces
        
        Args:
            x: Target x coordinate
            y: Target y coordinate  
            direction: Player facing direction
            update_gani: Whether to automatically update GANI to "walk"
        """
        if direction is None:
            # Get current direction from session manager
            local_player = self._session.get_player()
            direction = local_player.direction if local_player else Direction.DOWN
            
        # Enhanced debug logging to understand coordinate flow
        local_player = self._session.get_player()
        if local_player:
            self.logger.debug(f"[ACTION_MGR] move_to({x:.1f}, {y:.1f}, {direction}) - current segment: ({getattr(local_player, 'gmaplevelx', 0)}, {getattr(local_player, 'gmaplevely', 0)})")
        else:
            self.logger.debug(f"[ACTION_MGR] move_to({x:.1f}, {y:.1f}, {direction})")
        
        # Check if we should skip this movement (prevent transition frame issues)
        if self._transition_this_frame:
            self.logger.debug("[ACTION_MGR] Skipping movement - transition in progress")
            self._transition_this_frame = False
            return
        
        # Check if player is actually moving
        local_player = self._session.get_player()
        is_moving = False
        if local_player:
            # Calculate if this is actual movement
            dx = abs(x - local_player.x) if hasattr(local_player, 'x') else 0
            dy = abs(y - local_player.y) if hasattr(local_player, 'y') else 0
            is_moving = (dx > 0.1 or dy > 0.1)
        
        # Update player position in session manager
        self._update_player_position(x, y, direction)
        
        # Handle coordinate wrapping and segment changes (GMAP)
        actual_x, actual_y = self._handle_coordinate_wrapping(x, y)
        
        # Check for level links at new position
        self._check_level_links(actual_x, actual_y)
        
        # Only send movement packet if no level transition occurred
        if not self._transition_this_frame:
            # Send movement packet to server
            self._send_movement_packet(actual_x, actual_y, direction)
            
            # Update GANI animation if requested
            if update_gani and is_moving:
                # Send walk animation when moving (with proper .gani extension)
                self.update_animation("walk.gani")
        else:
            self.logger.debug("[ACTION_MGR] Skipped movement packet - level transition occurred")
    
    def _update_player_position(self, x: float, y: float, direction: Direction) -> None:
        """Update local player position in session manager"""
        local_player = self._session.get_player()
        if local_player:
            local_player.x = x
            local_player.y = y
            local_player.direction = direction
    
    def _handle_coordinate_wrapping(self, x: float, y: float) -> tuple[float, float]:
        """Handle GMAP coordinate wrapping and segment transitions
        
        Returns:
            tuple: (actual_x, actual_y) after any coordinate adjustments
        """
        if not self._gmap.is_active():
            # Not in GMAP mode, no wrapping needed
            return x, y
        
        # Check for segment boundary crossings
        local_player = self._session.get_player()
        if not local_player:
            return x, y
            
        original_segment_x = getattr(local_player, 'gmaplevelx', 0) or 0
        original_segment_y = getattr(local_player, 'gmaplevely', 0) or 0
        
        self.logger.debug(f"[ACTION_MGR] Coordinate wrapping check - pos: ({x:.1f},{y:.1f}), current segment: ({original_segment_x},{original_segment_y})")
        
        # Calculate new segment coordinates
        new_segment_x = original_segment_x
        new_segment_y = original_segment_y
        wrapped_x = x
        wrapped_y = y
        
        # Check for boundary crossings and wrap coordinates
        if x < 0:
            new_segment_x -= 1
            wrapped_x = 63.5
            self.logger.debug(f"[ACTION_MGR] X < 0 boundary crossing detected: x={x:.1f} -> wrapped={wrapped_x:.1f}, segment {original_segment_x} -> {new_segment_x}")
        elif x >= 64:
            new_segment_x += 1
            wrapped_x = 0.5
            self.logger.debug(f"[ACTION_MGR] X >= 64 boundary crossing detected: x={x:.1f} -> wrapped={wrapped_x:.1f}, segment {original_segment_x} -> {new_segment_x}")
            
        if y < 0:
            new_segment_y -= 1
            wrapped_y = 63.5
            self.logger.debug(f"[ACTION_MGR] Y < 0 boundary crossing detected: y={y:.1f} -> wrapped={wrapped_y:.1f}, segment {original_segment_y} -> {new_segment_y}")
        elif y >= 64:
            new_segment_y += 1
            wrapped_y = 0.5
            self.logger.debug(f"[ACTION_MGR] Y >= 64 boundary crossing detected: y={y:.1f} -> wrapped={wrapped_y:.1f}, segment {original_segment_y} -> {new_segment_y}")
        
        # Update segment coordinates if changed
        if new_segment_x != original_segment_x or new_segment_y != original_segment_y:
            self.logger.info(f"[ACTION_MGR] GMAP segment change detected: ({original_segment_x},{original_segment_y}) -> ({new_segment_x},{new_segment_y})")
            self.logger.info(f"[ACTION_MGR] Wrapped coordinates: ({wrapped_x:.1f}, {wrapped_y:.1f})")
            
            # ALWAYS update player's GMAP coordinates when segment changes
            local_player.gmaplevelx = new_segment_x
            local_player.gmaplevely = new_segment_y
            local_player.x = wrapped_x
            local_player.y = wrapped_y
            
            self.logger.info(f"[ACTION_MGR] Updated player segment to ({local_player.gmaplevelx}, {local_player.gmaplevely})")
            
            # Get the level name for the new segment
            new_level_name = self._gmap.get_level_at_position(new_segment_x, new_segment_y)
            if new_level_name:
                self.logger.info(f"[ACTION_MGR] Seamless transition to GMAP level: {new_level_name}")
                
                # Request the new level if not already cached
                # The level manager and GMAP manager will handle the seamless transition
                if hasattr(self.client, 'request_file'):
                    # Check if level is already cached
                    if self._levels.get_level(new_level_name):
                        self.logger.debug(f"[ACTION_MGR] Level {new_level_name} already cached, no request needed")
                    else:
                        self.logger.debug(f"[ACTION_MGR] Requesting level {new_level_name}")
                        self.client.request_file(new_level_name)
                    
                # Set the current level property for the session
                self.set_current_level(new_level_name)
                
                self.logger.debug(f"[ACTION_MGR] Seamless GMAP navigation - coordinates wrapped to ({wrapped_x}, {wrapped_y})")
                
                return wrapped_x, wrapped_y
            else:
                self.logger.warning(f"[ACTION_MGR] No level found at GMAP segment ({new_segment_x}, {new_segment_y})")
                # Revert segment change
                return x, y
        
        return x, y
    
    def _send_movement_packet(self, x: float, y: float, direction: Direction) -> None:
        """Send movement packet to server using proper protocol handling"""
        
        # Check if we should send (rate limiting)
        if not self._can_send_property():
            return
            
        # Check if movement is significant enough to send
        if self._is_movement_too_small(x, y, direction):
            return
        
        # Create movement packet using the proper helper
        packet = PlayerPropsPacketHelper.create()
        
        # Get version and determine which properties to send
        version = self.client.config.version if hasattr(self.client, 'config') else "6.037"
        
        # Determine movement properties based on version
        # Version 6.037 and 2.30+ use X2/Y2/Z2
        # Older versions use X/Y
        use_high_precision = version in ["6.037", "6.034", "2.30", "2.31"] or (
            isinstance(version, str) and version.startswith("6.")
        )
        
        # Add appropriate coordinate properties based on protocol version
        self._add_coordinate_properties(packet, x, y, use_high_precision)
        
        # Add direction only if it changed or if this is the first update
        if self._last_sent_dir is None or direction != self._last_sent_dir:
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_SPRITE, direction)
            self.logger.debug(f"[ACTION_MGR] Including direction: {direction} (was: {self._last_sent_dir})")
        
        # Send packet
        packet_bytes = packet.to_bytes()
        self.logger.info(f"[ACTION_MGR] Sending movement packet: {len(packet_bytes)} bytes")
        success = self.client.send_packet(packet_bytes)
        if not success:
            self.logger.error("[ACTION_MGR] Failed to send movement packet!")
        else:
            self.logger.debug("[ACTION_MGR] Movement packet sent successfully")
        
        # Update tracking
        self._last_sent_x = x
        self._last_sent_y = y
        self._last_sent_dir = direction
        
        self.logger.debug(f"[ACTION_MGR] Sent movement packet: ({x:.1f}, {y:.1f}, {direction})")
    
    def _can_send_property(self) -> bool:
        """Check if enough time has passed to send another property packet"""
        current_time = time.time()
        if current_time - self._last_property_send_time >= self._property_send_interval:
            self._last_property_send_time = current_time
            return True
        return False
    
    def _is_movement_too_small(self, x: float, y: float, direction: Direction) -> bool:
        """Check if movement change is too small to warrant sending"""
        if (self._last_sent_x is None or self._last_sent_y is None or 
            self._last_sent_dir is None):
            return False
            
        dx = abs(x - self._last_sent_x)
        dy = abs(y - self._last_sent_y)
        
        return dx < 0.25 and dy < 0.25 and direction == self._last_sent_dir
    
    def _add_coordinate_properties(self, packet, x: float, y: float, 
                                 use_high_precision: bool) -> None:
        """Add coordinate properties to packet based on protocol version and GMAP mode"""
        
        if use_high_precision:
            # New protocol (v2.30+, v6.037): Always send X2/Y2 coordinates
            # According to GServer expectations:
            # - X2/Y2 are in pixels (tiles * 16)
            # - Use local coordinates in non-GMAP levels
            # - Use local coordinates in GMAP levels (server handles world conversion)
            
            # Always send local coordinates as pixels
            local_x_pixels = int(x * 16)
            local_y_pixels = int(y * 16)
            
            # Add X2/Y2 properties
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_X2, local_x_pixels)
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_Y2, local_y_pixels)
            
            # Also send X/Y for account saving (server uses these for respawn)
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_X, x)
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_Y, y)
            
            # In GMAP mode, also send segment coordinates
            if self._gmap.is_active() and self._gmap.is_ready():
                local_player = self._session.get_player()
                if local_player:
                    gmap_x = getattr(local_player, 'gmaplevelx', 0) or 0
                    gmap_y = getattr(local_player, 'gmaplevely', 0) or 0
                    packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELX, gmap_x)
                    packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELY, gmap_y)
                    
                    self.logger.debug(f"[ACTION_MGR] Sending coords - Local: ({x:.1f}, {y:.1f}), Pixels: ({local_x_pixels}, {local_y_pixels}), Segment: ({gmap_x}, {gmap_y})")
            else:
                self.logger.debug(f"[ACTION_MGR] Sending coords - Local: ({x:.1f}, {y:.1f}), Pixels: ({local_x_pixels}, {local_y_pixels})")
            
        else:
            # Old protocol (pre-2.30): Send X/Y only
            # X/Y are in half-tiles (tiles * 2)
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_X, x)
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_Y, y)
            
            if self._gmap.is_active():
                # In GMAP mode with old protocol, still send segment coordinates
                local_player = self._session.get_player()
                if local_player:
                    gmap_x = getattr(local_player, 'gmaplevelx', 0) or 0
                    gmap_y = getattr(local_player, 'gmaplevely', 0) or 0
                    packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELX, gmap_x)
                    packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELY, gmap_y)
                    
                    self.logger.debug(f"[ACTION_MGR] Old protocol - Local: ({x:.1f}, {y:.1f}), Segment: ({gmap_x}, {gmap_y})")
            else:
                self.logger.debug(f"[ACTION_MGR] Old protocol - Local: ({x:.1f}, {y:.1f})")
        
        return packet
    
    def send_level_change(self, level_name: str) -> None:
        """Send CURLEVEL property when changing levels
        
        This informs the server which level the client thinks it's in.
        For GMAP mode, send the GMAP name instead of individual level name.
        """
        packet = PlayerPropsPacketHelper.create()
        
        # Determine what level name to send
        if self._gmap.is_active() and self._gmap.is_ready():
            # In GMAP mode, send the GMAP filename
            gmap_name = self._gmap.get_current_gmap()
            if gmap_name:
                packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CURLEVEL, gmap_name)
                self.logger.info(f"[ACTION_MGR] Sending CURLEVEL: {gmap_name} (GMAP mode)")
            else:
                # Fallback to level name if GMAP name not available
                packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CURLEVEL, level_name)
                self.logger.info(f"[ACTION_MGR] Sending CURLEVEL: {level_name} (GMAP mode but no GMAP name)")
        else:
            # Non-GMAP mode, send the actual level name
            packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CURLEVEL, level_name)
            self.logger.info(f"[ACTION_MGR] Sending CURLEVEL: {level_name}")
        
        # Send the packet
        self.client.send_packet(packet.to_bytes())
    
    def update_animation(self, gani_name: str, force: bool = False) -> None:
        """Send GANI property when animation changes
        
        Common GANI values: "idle", "walk", "sword", "carry", "sit", "spin"
        
        Args:
            gani_name: Name of the GANI animation to set
            force: Force sending even if animation hasn't changed
        """
        # Only send if animation changed or forced
        if not force and self._last_sent_gani == gani_name:
            return
        
        # Create packet with GANI property
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GANI, gani_name)
        
        # Send the packet
        self.client.send_packet(packet.to_bytes())
        self._last_sent_gani = gani_name
        
        self.logger.info(f"[ACTION_MGR] Sent GANI update: {gani_name}")
    
    def determine_animation_from_movement(self, is_moving: bool, has_weapon: bool = False) -> str:
        """Determine appropriate GANI based on movement state
        
        Args:
            is_moving: Whether the player is currently moving
            has_weapon: Whether the player has a weapon equipped
            
        Returns:
            Appropriate GANI name (with .gani extension)
        """
        if has_weapon and is_moving:
            return "walk.gani"  # Walking with weapon
        elif is_moving:
            return "walk.gani"  # Regular walking
        elif has_weapon:
            return "idle.gani"  # Standing with weapon
        else:
            return "idle.gani"  # Regular standing
    
    # === Level Links ===
    
    def _check_level_links(self, x: float, y: float) -> None:
        """Check if player position triggers a level link warp"""
        
        # Get current level from level manager
        current_level = self._levels.get_current_level()
        if not current_level:
            return
            
        self.logger.debug(f"[ACTION_MGR] Checking level links at ({x:.1f}, {y:.1f}) in {current_level.name}")
        
        # Initialize warp areas on level change
        if self._last_checked_level != current_level.name:
            self._last_checked_level = current_level.name
            self._player_in_warp_areas.clear()
            
            # Check if player is already in any warp areas
            for i, link in enumerate(current_level.links):
                if self._is_in_link_area(x, y, link):
                    self._player_in_warp_areas.add(i)
        
        # Prevent multiple transitions in same frame
        if self._transition_this_frame:
            return
        
        # Check all links in current level
        current_warp_areas = set()
        for i, link in enumerate(current_level.links):
            if self._is_in_link_area(x, y, link):
                current_warp_areas.add(i)
                
                # Only trigger if just entered this area
                if i not in self._player_in_warp_areas:
                    if self._should_trigger_link(link):
                        self._trigger_level_link(link, x, y)
                        return
        
        # Update current warp areas
        self._player_in_warp_areas = current_warp_areas
    
    def _is_in_link_area(self, x: float, y: float, link) -> bool:
        """Check if position is within link area"""
        return (x >= link.x and x < link.x + link.width and 
                y >= link.y and y < link.y + link.height)
    
    def _should_trigger_link(self, link) -> bool:
        """Check if this link should be triggered (handle GMAP edge link filtering)"""
        
        # If not in GMAP mode, all links are valid
        if not self._gmap.is_active():
            return True
        
        # In GMAP mode, we need to be very selective about which links to trigger
        current_gmap_name = self._gmap.get_current_gmap()
        if not current_gmap_name:
            return True
        
        # Check if destination is in current GMAP
        dest_in_gmap = self._gmap.is_level_in_current_gmap(link.destination)
        
        # Identify edge links - ANY link touching level boundaries
        is_edge_link = (
            link.x == 0 or                           # Left edge
            link.y == 0 or                           # Top edge  
            link.x + link.width >= 64 or            # Right edge
            link.y + link.height >= 64 or           # Bottom edge
            (link.x <= 1 and link.width >= 62) or   # Nearly full horizontal
            (link.y <= 1 and link.height >= 62)     # Nearly full vertical
        )
        
        if is_edge_link and dest_in_gmap:
            # This is an edge link to another GMAP level - should use coordinate wrapping instead
            self.logger.info(f"[ACTION_MGR] Blocking GMAP edge link: {link.destination} (use world navigation)")
            return False
        
        # Allow non-edge links (houses, shops, etc.) and links to non-GMAP levels
        if not is_edge_link:
            self.logger.debug(f"[ACTION_MGR] Allowing interior link: {link.destination}")
        elif not dest_in_gmap:
            self.logger.debug(f"[ACTION_MGR] Allowing edge link to non-GMAP level: {link.destination}")
        
        return True
    
    def _trigger_level_link(self, link, player_x: float, player_y: float) -> None:
        """Trigger a level link warp"""
        
        # Handle special coordinate values (None means use player position)
        dest_x = player_x if link.dest_x is None else float(link.dest_x)
        dest_y = player_y if link.dest_y is None else float(link.dest_y)
        
        self.logger.info(f"[ACTION_MGR] Triggering level link: {link.destination} at ({dest_x}, {dest_y})")
        
        # Send level warp packet
        self.warp_to_level(link.destination, dest_x, dest_y)
        
        # Set flag to prevent movement packet after warp
        self._transition_this_frame = True
        self._player_in_warp_areas.clear()
    
    # === Other Actions ===
    
    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.0) -> None:
        """Warp to a specific level"""
        from ..protocol.enums import PlayerToServer
        
        # Ensure level name has .nw extension if not a gmap
        if not level_name.endswith('.nw') and not level_name.endswith('.gmap'):
            level_name = f"{level_name}.nw"
        
        # Build warp packet
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_LEVELWARP + 32)
        
        # Convert coordinates to wire format
        wire_x = int(x * 2)
        wire_y = int(y * 2)
        packet_data.append(wire_x + 32)
        packet_data.append(wire_y + 32)
        
        # Add level name as null-terminated string
        level_bytes = level_name.encode('ascii')
        packet_data.extend(level_bytes)
        packet_data.append(0)
        
        self.client.send_packet(bytes(packet_data))
        
        # Update current level property
        self.set_current_level(level_name)
        
        # Update local player position to match warp destination
        local_player = self._session.get_player()
        if local_player:
            local_player.x = x
            local_player.y = y
            self.logger.debug(f"[ACTION_MGR] Updated local player position to ({x}, {y})")
        
        self.logger.info(f"[ACTION_MGR] Warped to level: {level_name} at ({x}, {y})")
    
    def set_chat(self, message: str) -> None:
        """Set chat bubble"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CURCHAT, message)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.chat = message
    
    def say(self, message: str) -> None:
        """Send chat message to all"""
        from ..protocol.enums import PlayerToServer
        
        # PLI_TOALL packet format: id + message
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_TOALL + 32)
        packet_data.extend(message.encode('ascii', errors='replace'))
        self.client.send_packet(bytes(packet_data))
    
    def send_pm(self, player_id: int, message: str) -> None:
        """Send private message"""
        from ..protocol.enums import PlayerToServer
        
        # PLI_PRIVMESSAGE packet format: id + player_id (2 bytes) + message
        packet_data = bytearray()
        packet_data.append(PlayerToServer.PLI_PRIVMESSAGE + 32)
        packet_data.append((player_id >> 8) & 0xFF)  # High byte
        packet_data.append(player_id & 0xFF)  # Low byte
        packet_data.extend(message.encode('ascii', errors='replace'))
        self.client.send_packet(bytes(packet_data))
    
    def set_nickname(self, nickname: str) -> None:
        """Set player nickname"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_NICKNAME, nickname)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.nickname = nickname
    
    def set_current_level(self, level_name: str) -> None:
        """Set current level property to notify server"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CURLEVEL, level_name)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set current level property: {level_name}")
    
    def set_gmap_position(self, gmap_x: int, gmap_y: int) -> None:
        """Set GMAP position coordinates"""
        local_player = self._session.get_player()
        if local_player:
            local_player.gmaplevelx = gmap_x
            local_player.gmaplevely = gmap_y
        
        # Send GMAP coordinates to server
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELX, gmap_x)
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GMAPLEVELY, gmap_y)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set GMAP position: ({gmap_x}, {gmap_y})")
    
    def set_gani(self, gani: str) -> None:
        """Set player GANI (animation)"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_GANI, gani)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.gani = gani
            
        self.logger.debug(f"[ACTION_MGR] Set GANI: {gani}")
    
    def set_carry_sprite(self, sprite_id: int) -> None:
        """Set carried item sprite"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_CARRYSPRITE, sprite_id)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set carry sprite: {sprite_id}")
    
    def set_head_image(self, image: str) -> None:
        """Set player head/hat image"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_HEADGIF, image)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set head image: {image}")
    
    def set_body_image(self, image: str) -> None:
        """Set player body/shirt image"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_BODYIMG, image)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set body image: {image}")
    
    def set_colors(self, colors: str) -> None:
        """Set player colors (color string format)"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_COLORS, colors)
        self.client.send_packet(packet.to_bytes())
        
        self.logger.debug(f"[ACTION_MGR] Set colors: {colors}")
    
    def set_head(self, image: str) -> None:
        """Alias for set_head_image for backward compatibility"""
        self.set_head_image(image)
    
    def set_body(self, image: str) -> None:
        """Alias for set_body_image for backward compatibility"""
        self.set_body_image(image)
    
    def request_file(self, filename: str) -> None:
        """Request a file from the server"""
        success = self.client.request_file(filename)
        self.logger.debug(f"[ACTION_MGR] Requested file: {filename} (success: {success})")
    
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, power: int = 1) -> None:
        """Drop a bomb at specified position"""
        local_player = self._session.get_player()
        if x is None and local_player:
            x = local_player.x
        if y is None and local_player:
            y = local_player.y
        if x is None:
            x = 30.0
        if y is None:
            y = 30.0
            
        # Create bomb packet manually since the import is broken
        # PLI_BOMBADD packet format: id + x + y + power + timer
        packet_id = 4  # PLI_BOMBADD
        packet_data = bytes([packet_id + 32])  # Add 32 to packet ID
        packet_data += bytes([min(255, int(x * 2))])  # X coordinate (half-tiles)
        packet_data += bytes([min(255, int(y * 2))])  # Y coordinate (half-tiles)
        packet_data += bytes([max(1, min(10, int(power)))])  # Power (1-10)
        packet_data += bytes([55])  # Timer (default 55 ticks)
        self.client.send_packet(packet_data)
        
        self.logger.debug(f"[ACTION_MGR] Dropped bomb at ({x}, {y}) with power {power}")
    
    def use_sword(self, return_to_idle: bool = False) -> None:
        """Swing the sword
        
        Args:
            return_to_idle: If True, automatically return to idle animation after a delay
        """
        # Send sword GANI animation with proper .gani extension
        self.update_animation("sword.gani", force=True)
        
        # Note: There is no PLI_SWORD packet in the protocol
        # Sword actions are handled through GANI animations
        # The server may send back sprite values (8-11) for legacy clients
        
        local_player = self._session.get_player()
        direction = 0  # Default to right
        if local_player and hasattr(local_player, 'direction'):
            direction = local_player.direction
        
        self.logger.debug(f"[ACTION_MGR] Used sword in direction {direction} via GANI")
    
    def swing_sword(self) -> None:
        """Alias for use_sword for compatibility"""
        self.use_sword()
    
    def shoot_arrow(self, direction: int = 0) -> None:
        """Shoot an arrow
        
        Args:
            direction: Direction to shoot (0=right, 1=left, 2=down, 3=up)
        """
        # Send bow GANI animation with proper .gani extension
        self.update_animation("bow.gani", force=True)
        
        # Create arrow packet manually
        # PLI_ARROWADD packet format: id + x + y + z (direction) + power + sprite
        packet_id = 9  # PLI_ARROWADD (not PLI_SHOOT which doesn't exist)
        
        # Get player position
        local_player = self._session.get_player()
        x = local_player.x if local_player else 30.0
        y = local_player.y if local_player else 30.0
        
        packet_data = bytes([packet_id + 32])  # Add 32 to packet ID
        packet_data += bytes([min(255, int(x * 2))])  # X coordinate (half-tiles)
        packet_data += bytes([min(255, int(y * 2))])  # Y coordinate (half-tiles)
        packet_data += bytes([direction & 0x03])  # Direction (0-3)
        packet_data += bytes([1])  # Power
        packet_data += bytes([0])  # Sprite (default arrow)
        self.client.send_packet(packet_data)
        
        self.logger.debug(f"[ACTION_MGR] Shot arrow from ({x}, {y}) in direction {direction}")
    
    def set_arrows(self, count: int) -> None:
        """Set arrow count"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_ARROWSCOUNT, count)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.arrows = count
            
        self.logger.debug(f"[ACTION_MGR] Set arrows: {count}")
    
    def set_bombs(self, count: int) -> None:
        """Set bomb count"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_BOMBSCOUNT, count)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.bombs = count
            
        self.logger.debug(f"[ACTION_MGR] Set bombs: {count}")
    
    def set_rupees(self, count: int) -> None:
        """Set rupee count"""
        packet = PlayerPropsPacketHelper.create()
        packet = PlayerPropsPacketHelper.add_property(packet, PlayerProp.PLPROP_RUPEESCOUNT, count)
        self.client.send_packet(packet.to_bytes())
        
        # Update local player
        local_player = self._session.get_player()
        if local_player:
            local_player.rupees = count
            
        self.logger.debug(f"[ACTION_MGR] Set rupees: {count}")
    
    # Note: Hearts/health properties not available in current protocol enums