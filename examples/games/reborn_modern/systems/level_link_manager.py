"""
Level Link Manager
==================

Handles level transitions and link processing for the reborn_modern client.
Implements GMAP edge link filtering while preserving indoor/dungeon warps.
"""

import logging
from typing import Dict, Set, Optional, Tuple
from dataclasses import dataclass

from pyreborn import Client
from .packet_api_compat import OutgoingPacketAPI


logger = logging.getLogger(__name__)


@dataclass
class LinkTriggerState:
    """Tracks which link areas the player is currently in"""
    current_level: Optional[str] = None
    warp_areas: Set[int] = None
    
    def __post_init__(self):
        if self.warp_areas is None:
            self.warp_areas = set()


class LevelLinkManager:
    """Manages level link processing and GMAP filtering"""
    
    def __init__(self, client: Client, packet_api: OutgoingPacketAPI):
        """Initialize level link manager
        
        Args:
            client: PyReborn client for level data
            packet_api: API for sending warp packets
        """
        self.client = client
        self.packet_api = packet_api
        self.trigger_state = LinkTriggerState()
        
        # Transition prevention
        self.transition_this_frame = False
        
        # Warp tracking to prevent double processing
        self.last_warp_time = 0
        self.last_warp_level = None
        
        # Optional physics system reference for getting collision box parameters
        self.physics_system = None
        
        logger.info("Level link manager initialized")
    
    def update(self, player_x: float = None, player_y: float = None, 
               collision_point: Optional[Tuple[float, float]] = None,
               blocked_direction: Optional[int] = None,
               blocked_time: float = 0.0,
               blocking_tile: Optional[Tuple[int, int]] = None) -> bool:
        """Update level link checking
        
        Args:
            player_x: Player X position in tiles (optional - will get from player)
            player_y: Player Y position in tiles (optional - will get from player)
            collision_point: Point where collision occurred if blocked (x, y)
            blocked_direction: Direction player is blocked (0=up, 1=left, 2=down, 3=right)
            blocked_time: How long player has been blocked (not used anymore)
            blocking_tile: Coordinates of the tile that blocked movement (x, y)
            
        Returns:
            True if a level transition was triggered
        """
        logger.debug(f"[LINK_MGR-DEBUG] update() called with collision_point={collision_point}, blocked_direction={blocked_direction}, blocking_tile={blocking_tile}")
        
        # Reset transition flag
        self.transition_this_frame = False
        
        # Get actual player coordinates (world coordinates in GMAP mode)
        player = self.client.session_manager.get_player()
        if not player:
            return False
            
        # Use player's world coordinates in GMAP mode, local coordinates otherwise
        gmap_manager = self.client.gmap_manager
        if gmap_manager and gmap_manager.is_active():
            # In GMAP mode - use world coordinates for detection
            actual_x = player.x2 if player.x2 is not None else player.x
            actual_y = player.y2 if player.y2 is not None else player.y
        else:
            # In single level mode - use local coordinates
            actual_x = player.x
            actual_y = player.y
        
        coord_type = "world" if (gmap_manager and gmap_manager.is_active()) else "local"
        logger.debug(f"[LINK_MGR] Checking links at player {coord_type} coords ({actual_x:.1f}, {actual_y:.1f})")
        
        # If we have a collision point, immediately check for links there
        # No timer needed - if we're blocked and there's a link, we should trigger it
        if collision_point and blocked_direction is not None:
            collision_x, collision_y = collision_point
            logger.debug(f"[LINK_MGR] 🔍 Player blocked, checking collision point ({collision_x:.1f}, {collision_y:.1f})")
            self._check_collision_links(collision_x, collision_y, blocked_direction, blocking_tile)
        
        # Also check for normal level links at player position
        if not self.transition_this_frame:
            self._check_level_links(actual_x, actual_y)
        
        return self.transition_this_frame
    
    def _check_collision_links(self, collision_x: float, collision_y: float, direction: Optional[int], 
                               blocking_tile: Optional[Tuple[int, int]] = None) -> None:
        """Check if collision point overlaps with any links
        
        Args:
            collision_x: X coordinate where collision occurred
            collision_y: Y coordinate where collision occurred  
            direction: Direction player was moving (0=up, 1=left, 2=down, 3=right)
            blocking_tile: Coordinates of the tile that blocked movement (x, y)
        """
        # Get current level from level manager
        current_level = self.client.level_manager.get_current_level()
        if not current_level:
            return
            
        logger.debug(f"[LINK_MGR] Checking for links at collision point ({collision_x:.1f}, {collision_y:.1f}), direction={direction}")
        
        # When we hit a wall, we want to check for links not just at the collision point,
        # but also in the direction we were trying to move. This handles the case where
        # a link is placed on a blocking tile (like a door on a wall)
        
        # We'll check multiple points along a ray from the collision point
        # This ensures we find links even if they're placed on or behind blocking tiles
        check_points = []
        
        # Add the collision point itself
        check_points.append((collision_x, collision_y, 0.0, "collision point"))
        
        # If we know the exact blocking tile, also check its center
        # This is important for links placed directly on blocking tiles
        if blocking_tile:
            tile_center_x = blocking_tile[0] + 0.5
            tile_center_y = blocking_tile[1] + 0.5
            check_points.append((tile_center_x, tile_center_y, 0.0, "blocking tile center"))
            logger.debug(f"[LINK_MGR] Added blocking tile center ({tile_center_x:.1f}, {tile_center_y:.1f}) to check points")
        
        # Calculate ray direction based on movement direction
        ray_dx, ray_dy = 0.0, 0.0
        if direction == 0:  # Up
            ray_dy = -1.0
        elif direction == 1:  # Left  
            ray_dx = -1.0
        elif direction == 2:  # Down
            ray_dy = 1.0
        elif direction == 3:  # Right
            ray_dx = 1.0
        
        # Check multiple distances along the ray (0.5, 1.0, 1.5, 2.0 tiles)
        # This handles various link placements: on the wall, behind the wall, etc.
        for distance in [0.5, 1.0, 1.5, 2.0]:
            check_x = collision_x + ray_dx * distance
            check_y = collision_y + ray_dy * distance
            check_points.append((check_x, check_y, distance, f"ray +{distance:.1f}"))
        
        # Also check slightly to the sides for wider links
        # This handles cases where the player hits the edge of a wall but the link extends sideways
        if direction in [0, 2]:  # Vertical movement - check horizontal sides
            for side_offset in [-0.5, 0.5]:
                check_points.append((collision_x + side_offset, collision_y + ray_dy, 1.0, f"side offset {side_offset:+.1f}"))
        elif direction in [1, 3]:  # Horizontal movement - check vertical sides
            for side_offset in [-0.5, 0.5]:
                check_points.append((collision_x + ray_dx, collision_y + side_offset, 1.0, f"side offset {side_offset:+.1f}"))
        
        logger.debug(f"[LINK_MGR] Checking {len(check_points)} points for links")
        
        # Check all links in current level
        for i, link in enumerate(current_level.links):
            # Get link coordinates in the appropriate system
            link_x, link_y = self._get_link_world_coordinates(link)
            
            # Check each point against this link
            for check_x, check_y, distance, point_type in check_points:
                # Use adaptive tolerance based on distance from collision
                # Closer points need less tolerance, farther points need more
                base_tolerance = 0.5
                distance_factor = 1.0 + (distance * 0.25)  # Increase tolerance with distance
                tolerance = base_tolerance * distance_factor
                
                # Additional tolerance for larger links (doors are often 2-3 tiles wide)
                link_size_factor = max(link.width, link.height) / 2.0
                tolerance = max(tolerance, link_size_factor * 0.3)
                
                # Check if this point overlaps with the link
                point_overlaps = (check_x >= link_x - tolerance and 
                                 check_x < link_x + link.width + tolerance and
                                 check_y >= link_y - tolerance and 
                                 check_y < link_y + link.height + tolerance)
                
                if point_overlaps:
                    # Found a link!
                    dest_level = self._get_link_destination(link)
                    logger.debug(f"[LINK_MGR] 🎯 Found link at {point_type} (distance={distance:.1f}): {dest_level}")
                    logger.debug(f"[LINK_MGR] Link bounds: ({link_x:.1f},{link_y:.1f}) size ({link.width}x{link.height}), tolerance={tolerance:.2f}")
                    
                    # Check if we should trigger it
                    if self._should_trigger_link(link):
                        logger.info(f"[LINK_MGR] ✅ TRIGGERING BLOCKED LINK to {dest_level}")
                        
                        # Get player position for destination coordinates
                        player = self.client.session_manager.get_player()
                        if player:
                            # Use player's actual position for warp destination
                            if self.client.is_gmap_mode():
                                player_x = player.x2 if player.x2 is not None else player.x
                                player_y = player.y2 if player.y2 is not None else player.y
                            else:
                                player_x = player.x
                                player_y = player.y
                            
                            self._trigger_level_link(link, player_x, player_y)
                            self.transition_this_frame = True
                            return
                    else:
                        logger.info(f"[LINK_MGR] ❌ Skipping filtered link: {dest_level}")
                        # Still check other links in case there's an unfiltered one nearby
                        continue
    
    def _check_level_links(self, x: float, y: float) -> None:
        """Check if player position triggers a level link warp
        
        Args:
            x: Player X position in tiles
            y: Player Y position in tiles
        """
        # Get current level from level manager
        current_level = self.client.level_manager.get_current_level()
        if not current_level:
            return
            
        logger.debug(f"[LINK_MGR] Checking level links at ({x:.1f}, {y:.1f}) in {current_level.name}")
        
        # Initialize warp areas on level change
        if self.trigger_state.current_level != current_level.name:
            self.trigger_state.current_level = current_level.name
            self.trigger_state.warp_areas.clear()
            
            # Pre-populate areas player is already in on level entry
            for i, link in enumerate(current_level.links):
                if self._is_in_link_area(x, y, link):
                    self.trigger_state.warp_areas.add(i)
                    logger.debug(f"[LINK_MGR] Player already in warp area {i} on level entry")
            
            logger.debug(f"[LINK_MGR] Initialized warp areas for {current_level.name}, player in {len(self.trigger_state.warp_areas)} areas")
            
            # Debug: Show coordinate system info
            player = self.client.session_manager.get_player()
            if player:
                gmap_manager = self.client.gmap_manager
                is_gmap = gmap_manager and gmap_manager.is_active()
                logger.info(f"🗺️ Level: {current_level.name}, GMAP mode: {is_gmap}")
                logger.info(f"👤 Player local: ({player.x:.1f}, {player.y:.1f}), world: ({player.x2}, {player.y2}), segment: ({player.gmaplevelx}, {player.gmaplevely})")
                logger.info(f"🔗 Level has {len(current_level.links)} links:")
                
                for i, link in enumerate(current_level.links):
                    dest = self._get_link_destination(link)
                    link_world_x, link_world_y = self._get_link_world_coordinates(link)
                    logger.info(f"  Link {i}: {dest} @ local({link.x},{link.y}) world({link_world_x},{link_world_y}) size {link.width}x{link.height}")
            
            # Preload link destinations
            self._preload_link_destinations()
            
            return
        
        # Check all links in current level
        current_warp_areas = set()
        for i, link in enumerate(current_level.links):
            if self._is_in_link_area(x, y, link):
                current_warp_areas.add(i)
                
                # Only trigger warp if player just entered this area
                if i not in self.trigger_state.warp_areas:
                    dest_level = self._get_link_destination(link)
                    logger.info(f"[LINK_MGR] ✅ Player ENTERED link area {i} to {dest_level}")
                    
                    if self._should_trigger_link(link):
                        logger.info(f"[LINK_MGR] 🎯 TRIGGERING WARP to {dest_level} from area {i}")
                        self._trigger_level_link(link, x, y)
                        self.transition_this_frame = True
                        break
                    else:
                        logger.info(f"[LINK_MGR] ❌ Skipping filtered GMAP edge link to {dest_level}")
        
        # Update current warp areas
        self.trigger_state.warp_areas = current_warp_areas
    
    def _is_in_link_area(self, x: float, y: float, link) -> bool:
        """Check if player's collision box overlaps with link area
        
        Args:
            x: X position in tiles (world coordinates in GMAP mode, local otherwise)
            y: Y position in tiles (world coordinates in GMAP mode, local otherwise)
            link: Level link object (source coordinates in local 0-63, need conversion in GMAP)
            
        Returns:
            True if player's collision box overlaps with link area
        """
        # Convert link coordinates to match player coordinate system
        link_x, link_y = self._get_link_world_coordinates(link)
        
        # Get player's collision box dimensions and offsets
        # Try to get from physics system if available, otherwise use defaults
        if self.physics_system and -1 in self.physics_system.bodies:
            # Get actual collision box parameters from physics body
            body = self.physics_system.bodies[-1]
            player_width = body.width
            player_height = body.height
            offset_x = body.collision_offset_x
            offset_y = body.collision_offset_y
        else:
            # Use default collision box parameters
            # Based on PhysicsBody defaults: width=1.0, height=0.5
            # collision_offset_x=1.0, collision_offset_y=2.0
            player_width = 1.0   # Full tile width
            player_height = 0.5  # Half tile height (feet/shadow area)
            offset_x = 1.0       # Offset right by 1 tile
            offset_y = 2.0       # Offset down by 2 tiles
        
        # Apply offsets to get actual collision box position
        # These offsets position the collision box at the character's feet
        collision_x = x + offset_x
        collision_y = y + offset_y
        
        # Check AABB collision between player's collision box and link area
        # We use a small epsilon to detect edge touching, not just overlap
        # This is important for door links on walls where the player can only
        # get close enough to touch the edge, not overlap significantly
        epsilon = 0.01  # Small tolerance for floating point edge detection
        
        # Player collision box touches/overlaps link if:
        # - Player's right edge >= link's left edge (with epsilon tolerance) AND
        # - Player's left edge <= link's right edge (with epsilon tolerance) AND
        # - Player's bottom edge >= link's top edge (with epsilon tolerance) AND
        # - Player's top edge <= link's bottom edge (with epsilon tolerance)
        overlaps = (collision_x < link_x + link.width + epsilon and
                   collision_x + player_width > link_x - epsilon and
                   collision_y < link_y + link.height + epsilon and
                   collision_y + player_height > link_y - epsilon)
        
        if overlaps:
            logger.debug(f"[LINK_MGR] Collision box ({collision_x:.1f},{collision_y:.1f}) size ({player_width}x{player_height}) overlaps link at ({link_x},{link_y}) size ({link.width}x{link.height})")
        
        return overlaps
    
    def _get_link_world_coordinates(self, link) -> tuple:
        """Get level link source coordinates in the appropriate coordinate system
        
        Args:
            link: Level link object (source coordinates in local 0-63)
            
        Returns:
            (x, y) tuple in world coordinates if GMAP mode, local coordinates otherwise
        """
        # Get GMAP manager to check current mode
        gmap_manager = self.client.gmap_manager
        if not gmap_manager or not gmap_manager.is_active():
            # Not in GMAP mode - use local coordinates as-is
            return (link.x, link.y)
        
        # In GMAP mode - use our new segment mapper for reliable conversion
        level_manager = self.client.level_manager
        current_level = level_manager.get_current_level() if level_manager else None
        
        if not current_level:
            logger.warning("No current level - using local coordinates")
            return (link.x, link.y)
        
        # Simple segment lookup - just parse the level name
        # Most GMAP levels follow pattern: baseNameX.nw where X is the segment position
        segment = self._parse_segment_from_level_name(current_level.name)
        
        if segment:
            # Convert to world coordinates using the reliable segment
            seg_x, seg_y = segment
            world_x = seg_x * 64 + link.x
            world_y = seg_y * 64 + link.y
            
            logger.debug(f"Link ({link.x},{link.y}) -> world ({world_x},{world_y}) via segment ({seg_x},{seg_y})")
            
            # Ensure player segment is synchronized
            player = self.client.session_manager.get_player()
            if player and (player.gmaplevelx != seg_x or player.gmaplevely != seg_y):
                player.gmaplevelx = seg_x
                player.gmaplevely = seg_y
                logger.info(f"[LINK_MGR] Synchronized player segment to ({seg_x}, {seg_y})")
            
            return (world_x, world_y)
        else:
            # Level not in GMAP - shouldn't happen in GMAP mode
            logger.warning(f"Level {current_level.name} not found in GMAP - using local coordinates")
            return (link.x, link.y)
    
    
    def _should_trigger_link(self, link) -> bool:
        """Check if this link should be triggered (handle GMAP edge link filtering)
        
        Args:
            link: Level link object
            
        Returns:
            True if link should be triggered
        """
        # Get GMAP manager to check current mode
        gmap_manager = self.client.gmap_manager
        if not gmap_manager or not gmap_manager.is_active():
            # Not in GMAP mode - all links are valid
            return True
        
        # In GMAP mode - check if this is an edge link to another GMAP level
        current_level = self.client.level_manager.get_current_level()
        if not current_level:
            return True
        
        # Check if current level is a GMAP level
        current_level_name = current_level.name
        is_current_gmap_level = (
            current_level_name.endswith('.nw') and 
            gmap_manager.is_level_in_current_gmap(current_level_name)
        )
        
        if not is_current_gmap_level:
            # Current level is not a GMAP level - all links are valid
            return True
        
        # Check if destination is a GMAP level
        dest_level = self._get_link_destination(link)
        is_dest_gmap_level = (
            dest_level.endswith('.nw') and 
            gmap_manager.is_level_in_current_gmap(dest_level)
        )
        
        if not is_dest_gmap_level:
            # Destination is not a GMAP level (indoor, dungeon, etc.) - allow link
            logger.debug(f"[LINK_MGR] Allowing link to non-GMAP level: {dest_level}")
            return True
        
        # Both current and destination are GMAP levels - check if it's a full edge link
        if self._is_full_edge_link(link):
            logger.debug(f"[LINK_MGR] Filtering GMAP edge link: {current_level_name} -> {dest_level}")
            return False
        
        # Not a full edge link - allow it (might be a small transition area)
        logger.debug(f"[LINK_MGR] Allowing partial GMAP link: {current_level_name} -> {dest_level}")
        return True
    
    def _is_full_edge_link(self, link) -> bool:
        """Check if this is a full edge link (spans entire edge of level)
        
        Args:
            link: Level link object
            
        Returns:
            True if link spans a full edge
        """
        # Check if link spans full width/height of level (64x64)
        tolerance = 2  # Allow small gaps
        
        # Full top/bottom edge
        if (link.width >= 64 - tolerance and 
            (link.y <= tolerance or link.y >= 64 - link.height - tolerance)):
            return True
        
        # Full left/right edge  
        if (link.height >= 64 - tolerance and
            (link.x <= tolerance or link.x >= 64 - link.width - tolerance)):
            return True
        
        return False
    
    def _trigger_level_link(self, link, player_x: float, player_y: float) -> None:
        """Trigger a level link warp - handle locally for instant warping
        
        Args:
            link: Level link object
            player_x: Current player X position
            player_y: Current player Y position
        """
        # Handle different link data structure formats
        dest_level = self._get_link_destination(link)
        dest_x, dest_y = self._get_link_coordinates(link, player_x, player_y)
        
        logger.info(f"[LINK_MGR] 🚀 Triggering LOCAL warp: {dest_level} at ({dest_x:.1f}, {dest_y:.1f})")
        
        # Get current level and player
        current_level = self.client.level_manager.get_current_level()
        player = self.client.session_manager.get_player()
        
        if not player:
            logger.error("[LINK_MGR] No player object to warp!")
            return
        
        # Check if destination level is cached
        dest_level_obj = None
        if dest_level != current_level.name:
            dest_level_obj = self.client.level_manager.get_level(dest_level)
            if not dest_level_obj:
                logger.warning(f"[LINK_MGR] Destination level {dest_level} not cached, requesting...")
                # Request the level
                if hasattr(self.client, 'request_file'):
                    self.client.request_file(dest_level)
                # Fall back to server warp for uncached levels
                self._trigger_server_warp(dest_level, dest_x, dest_y)
                return
        
        # === LOCAL WARP - Update everything locally ===
        
        # 1. Update player position
        old_x, old_y = player.x, player.y
        player.x = dest_x
        player.y = dest_y
        player.level = dest_level
        logger.info(f"[LINK_MGR] Updated player position: ({old_x:.1f}, {old_y:.1f}) -> ({dest_x:.1f}, {dest_y:.1f})")
        
        # 2. Update GMAP segment coordinates if entering a GMAP level
        gmap_manager = self.client.gmap_manager
        
        # First check if destination level has segment data in parsed GMAP
        # This handles the case where we're entering a level that will trigger GMAP loading
        segment = self._parse_segment_from_level_name(dest_level)
        if segment:
            # This is a GMAP level - set coordinates even if GMAP isn't loaded yet
            player.gmaplevelx = segment[0]
            player.gmaplevely = segment[1]
            # Use the internal _x2/_y2 to ensure they persist
            if hasattr(player, '_x2'):
                player._x2 = segment[0] * 64 + dest_x
                player._y2 = segment[1] * 64 + dest_y
            else:
                player.x2 = segment[0] * 64 + dest_x
                player.y2 = segment[1] * 64 + dest_y
            actual_x2 = getattr(player, '_x2', player.x2)
            actual_y2 = getattr(player, '_y2', player.y2)
            logger.info(f"[LINK_MGR] Set GMAP coords for {dest_level}: segment ({segment[0]}, {segment[1]}), world ({actual_x2:.1f}, {actual_y2:.1f})")
        elif gmap_manager and dest_level.endswith('.nw'):
            # Check if destination is a GMAP level using the manager
            if gmap_manager.is_level_in_current_gmap(dest_level):
                # This shouldn't happen if parsing worked correctly
                logger.warning(f"[LINK_MGR] Level {dest_level} is in GMAP but no segment data found")
            else:
                # Entering a non-GMAP level from GMAP mode
                # Clear segment coordinates
                player.gmaplevelx = None
                player.gmaplevely = None
                player.x2 = None
                player.y2 = None
                logger.info(f"[LINK_MGR] Cleared GMAP segment coordinates (entering non-GMAP level)")
        else:
            # No GMAP manager and no segment data - clear coordinates
            player.gmaplevelx = None
            player.gmaplevely = None
            player.x2 = None
            player.y2 = None
            logger.debug(f"[LINK_MGR] No GMAP data for {dest_level}")
        
        # 3. Update physics body if exists
        if self.physics_system and -1 in self.physics_system.bodies:
            body = self.physics_system.bodies[-1]
            body.x = dest_x
            body.y = dest_y
            # Clear any collision state
            body.blocked_direction = None
            body.last_collision_x = None
            body.last_collision_y = None
            logger.info(f"[LINK_MGR] Updated physics body position to ({dest_x:.1f}, {dest_y:.1f})")
        
        # 4. Switch level if different
        if dest_level != current_level.name and dest_level_obj:
            self.client.level_manager.set_current_level(dest_level_obj)
            logger.info(f"[LINK_MGR] Switched to level: {dest_level}")
            # Check if we need to switch modes
            self._handle_mode_switching(dest_level)
        
        # 5. Clear trigger state for instant re-triggering
        self.trigger_state.warp_areas.clear()
        self.trigger_state.current_level = dest_level  # Update tracked level
        logger.info(f"[LINK_MGR] Cleared trigger state for instant re-triggering")
        
        # 6. Send player properties to inform server
        try:
            from pyreborn.protocol.enums import PlayerProp
            
            # Determine what coordinates to send based on GMAP mode
            send_x, send_y = dest_x, dest_y
            send_level = dest_level
            
            # If we're in GMAP mode, send world coordinates and GMAP name
            if player.gmaplevelx is not None and player.gmaplevely is not None:
                # Send world coordinates instead of local
                send_x = player.x2 if player.x2 is not None else dest_x
                send_y = player.y2 if player.y2 is not None else dest_y
                
                # Send GMAP name instead of individual level name
                # This matches what the server expects for GMAP warps
                if hasattr(gmap_manager, 'current_gmap') and gmap_manager.current_gmap:
                    send_level = gmap_manager.current_gmap
                    logger.info(f"[LINK_MGR] Sending GMAP coordinates: world({send_x:.1f}, {send_y:.1f}) in {send_level}")
            else:
                logger.info(f"[LINK_MGR] Sending local coordinates: ({send_x:.1f}, {send_y:.1f}) in {send_level}")
            
            properties = [
                (PlayerProp.PLPROP_X, send_x),
                (PlayerProp.PLPROP_Y, send_y),
                (PlayerProp.PLPROP_CURLEVEL, send_level)
            ]
            
            # Include GMAP segment coordinates if we have them
            if player.gmaplevelx is not None and player.gmaplevely is not None:
                properties.extend([
                    (PlayerProp.PLPROP_GMAPLEVELX, player.gmaplevelx),
                    (PlayerProp.PLPROP_GMAPLEVELY, player.gmaplevely)
                ])
            
            success = self.packet_api.create_and_send(
                'PLI_PLAYERPROPS',
                properties=properties
            )
            logger.info(f"[LINK_MGR] ✅ Sent player properties to server")
        except Exception as e:
            logger.error(f"[LINK_MGR] Failed to send player properties: {e}")
        
        # Set flag to prevent other systems from processing this frame
        self.transition_this_frame = True
        
        # Track this warp to prevent double processing
        import time
        self.last_warp_time = time.time()
        self.last_warp_level = dest_level
    
    def _trigger_server_warp(self, dest_level: str, dest_x: float, dest_y: float) -> None:
        """Fall back to server-side warp for uncached levels
        
        Args:
            dest_level: Destination level name
            dest_x: Destination X coordinate
            dest_y: Destination Y coordinate
        """
        logger.info(f"[LINK_MGR] Falling back to SERVER warp for uncached level")
        
        # Send level warp packet (old method)
        try:
            success = self.packet_api.create_and_send(
                'PLI_LEVELWARP',
                x=dest_x,
                y=dest_y,
                level_name=dest_level,
                transition=""
            )
            if success:
                logger.info(f"[LINK_MGR] ✅ PLI_LEVELWARP packet sent")
            else:
                logger.error(f"[LINK_MGR] ❌ PLI_LEVELWARP packet failed")
        except Exception as e:
            logger.error(f"[LINK_MGR] ❌ Failed to send PLI_LEVELWARP packet: {e}")
        
        # Set flag to prevent other systems from processing this frame
        self.transition_this_frame = True
        
        # Track this warp to prevent double processing
        import time
        self.last_warp_time = time.time()
        self.last_warp_level = dest_level
    
    def _get_link_destination(self, link) -> str:
        """Get destination level name from link object
        
        Args:
            link: Level link object
            
        Returns:
            Destination level name
        """
        # Try different attribute names
        for attr in ['destination', 'target_level', 'dest_level']:
            if hasattr(link, attr):
                return getattr(link, attr)
        return 'unknown'
    
    def _get_link_coordinates(self, link, player_x: float, player_y: float) -> Tuple[float, float]:
        """Get destination coordinates from link object
        
        Args:
            link: Level link object
            player_x: Current player X position
            player_y: Current player Y position
            
        Returns:
            (dest_x, dest_y) tuple
        """
        # Default to player position
        dest_x, dest_y = player_x, player_y
        
        # Try level.py model format (dest_x, dest_y)
        if hasattr(link, 'dest_x') and hasattr(link, 'dest_y'):
            dest_x = player_x if link.dest_x is None else float(link.dest_x)
            dest_y = player_y if link.dest_y is None else float(link.dest_y)
        
        # Try parser format (target_x, target_y)
        elif hasattr(link, 'target_x') and hasattr(link, 'target_y'):
            target_x = getattr(link, 'target_x', player_x)
            target_y = getattr(link, 'target_y', player_y)
            
            # Handle special string values
            if isinstance(target_x, str) and target_x in ('playerx', '-1'):
                dest_x = player_x
            else:
                dest_x = float(target_x)
                
            if isinstance(target_y, str) and target_y in ('playery', '-1'):
                dest_y = player_y
            else:
                dest_y = float(target_y)
        
        return dest_x, dest_y
    
    def _handle_mode_switching(self, dest_level: str) -> None:
        """Handle switching between GMAP and single level modes
        
        Args:
            dest_level: Destination level name
        """
        gmap_manager = self.client.gmap_manager
        if not gmap_manager:
            return
        
        # Check if destination is a GMAP level
        is_dest_gmap = (
            dest_level.endswith('.nw') and 
            gmap_manager.is_level_in_current_gmap(dest_level)
        )
        
        current_gmap_active = gmap_manager.is_active()
        player = self.client.session_manager.get_player()
        
        if is_dest_gmap and not current_gmap_active:
            # Switching to GMAP mode
            logger.info(f"[LINK_MGR] Switching to GMAP mode for {dest_level}")
            # The GMAP system will activate automatically when the level loads
            # But we should ensure the player has segment coordinates set
            if player:
                segment = self._parse_segment_from_level_name(dest_level)
                if segment and (player.gmaplevelx is None or player.gmaplevely is None):
                    player.gmaplevelx = segment[0]
                    player.gmaplevely = segment[1]
                    # Update world coordinates
                    player.x2 = segment[0] * 64 + player.x
                    player.y2 = segment[1] * 64 + player.y
                    logger.info(f"[LINK_MGR] Set initial GMAP segment to ({segment[0]}, {segment[1]})")
            
        elif not is_dest_gmap and current_gmap_active:
            # Switching to single level mode
            logger.info(f"[LINK_MGR] Switching to single level mode for {dest_level}")
            # Clear GMAP segment coordinates
            if player:
                player.gmaplevelx = None
                player.gmaplevely = None
                player.x2 = None
                player.y2 = None
                logger.info(f"[LINK_MGR] Cleared GMAP segment coordinates (exiting GMAP mode)")
    
    def reset_transition_flag(self):
        """Reset the transition flag (called at start of frame)"""
        self.transition_this_frame = False
    
    def was_transition_triggered(self) -> bool:
        """Check if a transition was triggered this frame"""
        return self.transition_this_frame
    
    def _parse_segment_from_level_name(self, level_name: str) -> Optional[Tuple[int, int]]:
        """Get segment coordinates from level name using parsed GMAP data
        
        Args:
            level_name: Level filename (with or without .nw extension)
            
        Returns:
            (seg_x, seg_y) or None if level not in current GMAP
        """
        if not level_name:
            return None
            
        # Try to get segment from level manager's parsed GMAP data
        level_manager = self.client.level_manager
        if level_manager and hasattr(level_manager, 'update_segment_from_level'):
            segment = level_manager.update_segment_from_level(level_name)
            if segment:
                logger.debug(f"✅ Found segment for '{level_name}': {segment}")
                return segment
            else:
                logger.debug(f"❌ No segment found for '{level_name}' in parsed GMAP data")
        
        # Fallback: If level manager doesn't have the data, return None
        # We should NOT guess - only use real parsed data
        logger.debug(f"No segment parser available for {level_name}")
        return None
    
    def _preload_link_destinations(self) -> None:
        """Preload all levels that this level has links to"""
        current_level = self.client.level_manager.get_current_level()
        if not current_level or not current_level.links:
            return
        
        # Get unique destination levels
        destinations = set()
        for link in current_level.links:
            dest = self._get_link_destination(link)
            if dest and dest != 'unknown' and dest != current_level.name:
                destinations.add(dest)
        
        if not destinations:
            return
        
        logger.info(f"[LINK_MGR] Preloading {len(destinations)} link destinations for {current_level.name}")
        
        # Request each destination level if not already cached
        for dest_level in destinations:
            # Check if level is already cached
            if not self.client.level_manager.has_level(dest_level):
                # Request the level file
                if hasattr(self.client, 'request_file'):
                    success = self.client.request_file(dest_level)
                    logger.info(f"[LINK_MGR] Requested preload of {dest_level}: {success}")
                else:
                    logger.debug(f"[LINK_MGR] Cannot preload {dest_level} - no request_file method")
            else:
                logger.debug(f"[LINK_MGR] {dest_level} already cached")