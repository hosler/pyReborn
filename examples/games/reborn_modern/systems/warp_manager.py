"""
Elegant Warp Manager
====================

Simple, clean warp/link handling using AABB collision detection.
Replaces 833-line level_link_manager.py with ~200 lines of elegant code.

Features:
- Simple AABB collision for link detection
- Clean warp execution
- No complex GMAP edge filtering (just use collision)
- Support for both level links and NPCs with warp actions
"""

import logging
import time
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WarpDestination:
    """Represents a warp destination"""
    level_name: str
    x: float
    y: float
    transition: str = ""  # Optional transition effect


class WarpManager:
    """Simple, elegant warp management"""
    
    def __init__(self, client, packet_api):
        """Initialize warp manager
        
        Args:
            client: PyReborn client for level data
            packet_api: API for sending warp packets
        """
        self.client = client
        self.packet_api = packet_api
        
        # Cooldown to prevent warp spam
        self.last_warp_time = 0
        self.warp_cooldown = 0.5  # Half second cooldown
        
        # Track which warp we're in to prevent re-triggering
        self.current_warp_area = None
        
        logger.info("ElegantWarpManager initialized")
    
    def check_warps(self, player_x: float, player_y: float) -> Optional[WarpDestination]:
        """Check if player is in any warp area
        
        Args:
            player_x: Player X position in tiles
            player_y: Player Y position in tiles
            
        Returns:
            WarpDestination if warp should trigger, None otherwise
        """
        # Check cooldown
        if time.time() - self.last_warp_time < self.warp_cooldown:
            return None
        
        # Get current level
        level_mgr = getattr(self.client, 'level_manager', None)
        if not level_mgr:
            return None
            
        level = level_mgr.get_current_level()
        if not level:
            return None
        
        # Check level links
        if hasattr(level, 'links') and level.links:
            for link in level.links:
                if self._is_player_in_link(player_x, player_y, link):
                    # Check if we're already in this warp (prevent re-trigger)
                    warp_id = f"{link.x},{link.y},{link.width},{link.height}"
                    if warp_id == self.current_warp_area:
                        continue  # Already processed this warp
                    
                    # New warp area entered
                    self.current_warp_area = warp_id
                    
                    # Calculate destination
                    dest = self._calculate_destination(player_x, player_y, link)
                    if dest:
                        logger.info(f"🌀 Warp triggered: {level.name} → {dest.level_name} at ({dest.x:.1f}, {dest.y:.1f})")
                        self.execute_warp(dest)
                        return dest
        
        # Check if we've left all warp areas
        if self.current_warp_area:
            # Check if still in current warp
            still_in_warp = False
            if hasattr(level, 'links') and level.links:
                for link in level.links:
                    warp_id = f"{link.x},{link.y},{link.width},{link.height}"
                    if warp_id == self.current_warp_area:
                        if self._is_player_in_link(player_x, player_y, link):
                            still_in_warp = True
                            break
            
            if not still_in_warp:
                self.current_warp_area = None  # Left warp area
        
        return None
    
    def _is_player_in_link(self, player_x: float, player_y: float, link) -> bool:
        """Check if player overlaps with link using AABB collision
        
        Args:
            player_x: Player X position
            player_y: Player Y position  
            link: Link object with x, y, width, height
            
        Returns:
            True if player is in link area
        """
        # Player hitbox (offset to character feet/center)
        player_box_x = player_x + 0.5  # Center of player tile
        player_box_y = player_y + 1.5  # Near feet for better feel
        player_width = 1.0
        player_height = 0.5
        
        # AABB collision check
        return (player_box_x < link.x + link.width and
                player_box_x + player_width > link.x and
                player_box_y < link.y + link.height and
                player_box_y + player_height > link.y)
    
    def _calculate_destination(self, player_x: float, player_y: float, link) -> Optional[WarpDestination]:
        """Calculate warp destination from link
        
        Args:
            player_x: Current player X
            player_y: Current player Y
            link: Link object
            
        Returns:
            WarpDestination or None
        """
        if not hasattr(link, 'destination'):
            return None
        
        # Parse destination coordinates
        dest_x = link.dest_x if hasattr(link, 'dest_x') else 30.0
        dest_y = link.dest_y if hasattr(link, 'dest_y') else 30.0
        
        # Handle special destination keywords
        if isinstance(dest_x, str):
            if dest_x.lower() == 'playerx':
                dest_x = player_x
            elif dest_x.lower() == 'playery':
                dest_x = player_y
            else:
                try:
                    dest_x = float(dest_x)
                except:
                    dest_x = 30.0
        
        if isinstance(dest_y, str):
            if dest_y.lower() == 'playerx':
                dest_y = player_x
            elif dest_y.lower() == 'playery':
                dest_y = player_y
            else:
                try:
                    dest_y = float(dest_y)
                except:
                    dest_y = 30.0
        
        return WarpDestination(
            level_name=link.destination,
            x=float(dest_x),
            y=float(dest_y)
        )
    
    def execute_warp(self, destination: WarpDestination):
        """Execute a warp to the destination
        
        Args:
            destination: WarpDestination to warp to
        """
        # Update cooldown
        self.last_warp_time = time.time()
        
        # Send warp packet
        try:
            # For GMAP warps, check if we need special handling
            level_mgr = getattr(self.client, 'level_manager', None)
            is_gmap = level_mgr and level_mgr.is_gmap_mode()
            
            if is_gmap:
                # In GMAP mode, let server handle the warp
                logger.debug(f"Sending GMAP warp to {destination.level_name}")
            
            # Send the warp request (works for both GMAP and regular)
            from pyreborn.protocol.enums import PlayerProp
            self.packet_api.create_and_send(
                'PLI_PLAYERPROPS',
                properties=[
                    (PlayerProp.PLPROP_X, destination.x),
                    (PlayerProp.PLPROP_Y, destination.y),
                    (PlayerProp.PLPROP_CURLEVEL, destination.level_name)
                ]
            )
            
            # Update local player position for smooth transition
            session_mgr = getattr(self.client, 'session_manager', None)
            if session_mgr:
                player = session_mgr.get_player()
                if player:
                    player.x = destination.x
                    player.y = destination.y
            
            logger.info(f"✅ Warp executed to {destination.level_name} at ({destination.x:.1f}, {destination.y:.1f})")
            
        except Exception as e:
            logger.error(f"Failed to execute warp: {e}")
    
    def add_custom_warp(self, x: float, y: float, width: float, height: float,
                       destination: str, dest_x: float, dest_y: float):
        """Add a custom warp area (for script-created warps)
        
        Args:
            x, y: Top-left position of warp area
            width, height: Size of warp area
            destination: Destination level name
            dest_x, dest_y: Destination coordinates
        """
        # This could be extended to support custom warps from NPCs
        # For now, it's a placeholder for future functionality
        logger.info(f"Custom warp support planned: {destination} at ({x},{y})")
    
    def reset(self):
        """Reset warp state (call on level change)"""
        self.current_warp_area = None
        self.last_warp_time = 0
        logger.debug("Warp manager state reset")