"""
Player model for tracking player state
"""

from typing import Optional, Dict, Any, Tuple
from ..protocol.enums import PlayerProp, Direction, PlayerStatus
from ..session.logging_config import ModuleLogger

logger = ModuleLogger.get_logger(__name__)

class Player:
    """Represents a player in the game"""
    
    def __init__(self, player_id: int = -1):
        # Identity
        self.id = player_id
        self.account = ""
        self.nickname = ""
        self.is_local = False  # Flag to identify local player
        self._processing_server_update = False  # Flag to track server updates
        
        # Position (None until server provides actual values)
        self._x = None  # Local X coordinate within level/segment
        self._y = None  # Local Y coordinate within level/segment
        self._x2 = None  # High precision X across entire gmap
        self._y2 = None  # High precision Y across entire gmap
        self.z = 0.0
        self.z2 = None  # High precision Z (height/layer)
        self.level = ""
        self.direction = Direction.DOWN
        
        # Stats
        self.hearts = 3.0
        self.max_hearts = 3.0
        self.magic = 0.0
        self.arrows = 0
        self.bombs = 0
        self.rupees = 0
        self.ap = 0  # Achievement Points (AP Count)
        self.apcount = 0  # Alias for ap
        
        # Power levels
        self.sword_power = 0
        self.shield_power = 0
        self.glove_power = 0
        self.bomb_power = 0
        
        # Appearance
        self.head_image = "head0.png"
        self.body_image = "body.png"
        self.sword_image = ""
        self.shield_image = ""
        self.gani = ""
        self.colors = [0, 0, 0, 0, 0]  # skin, coat, sleeves, shoes, belt
        
        # Status
        self.status = 0
        self.chat = ""
        self.guild = ""
        
        # Attributes
        self.attributes = {}  # gattrib1-30
        self.player_attributes = {}  # plattrib1-5
        
        # Other
        self.horse_image = ""
        self.carry_sprite = -1
        self.online_time = 0
        self.kills = 0
        self.deaths = 0
        self.rating = 0
        
        # New GServer-V2 properties
        self.community_name = ""  # Alias/community name
        self.playerlist_category = 0  # Player list categorization
        self.group = ""  # Player group for group maps
        
        # RC (Remote Control) properties
        self.rc_rights = 0  # RC rights level (0 = no rights, 1+ = various admin levels)
        self.admin_level = 0  # Administrative level (0 = normal user, 1+ = admin levels)
        
        # GMAP properties
        self.gmaplevelx = None  # X segment in gmap
        self.gmaplevely = None  # Y segment in gmap
        
        # Store raw properties for debugging
        self._properties = {}
        
        # Movement detection for animations
        self._last_x = None
        self._last_y = None
        self._movement_time = 0.0
        self.is_moving = False
        
        # Interpolated position for smooth rendering
        self.render_x = None
        self.render_y = None
        self._interpolation_speed = 0.15  # Smoothing factor (0-1, higher = snappier)
        
        # Animation states
        self.is_sitting = False
        self.is_swimming = False
        self.is_hurt = False
        self.is_dead = False
        self.is_carrying = False
        self.sword_out = False
        self.sprite = 2  # Default sprite direction (0=up, 1=left, 2=down, 3=right)
    
    @property
    def x(self) -> float:
        """Get local X coordinate (0-64 within segment)"""
        # Return 0 if not set yet (server hasn't sent position)
        return self._x if self._x is not None else 0.0
        
    @x.setter
    def x(self, value: float):
        """Set local X coordinate and update world coordinate if in GMAP"""
        # Check for movement (only if we had a previous position)
        if self._x is not None and abs(value - self._x) > 0.1:  # Movement threshold
            self._last_x = self._x
            self.is_moving = True
            self._movement_time = 0.0
            
            # Check for warp (large position change)
            if abs(value - self._x) > 10:
                # Snap render position on warp
                self.render_x = value
        
        # No coordinate wrapping - each level is independent
        self._x = value
        
        # Initialize render position if this is first position set
        if self.render_x is None:
            self.render_x = value
            
        # Update world coordinate atomically if in GMAP mode
        # BUT only if not being set from server packet (checked via stack inspection)
        if not self._is_server_update():
            self._update_world_coordinates()
            
    @property
    def y(self) -> float:
        """Get local Y coordinate (0-64 within segment)"""
        # Return 0 if not set yet (server hasn't sent position)
        return self._y if self._y is not None else 0.0
        
    @y.setter
    def y(self, value: float):
        """Set local Y coordinate and update world coordinate if in GMAP"""
        # Check for movement (only if we had a previous position)
        if self._y is not None and abs(value - self._y) > 0.1:  # Movement threshold
            self._last_y = self._y
            self.is_moving = True
            self._movement_time = 0.0
            
            # Check for warp (large position change)
            if abs(value - self._y) > 10:
                # Snap render position on warp
                self.render_y = value
        
        # No coordinate wrapping - each level is independent
        self._y = value
        
        # Initialize render position if this is first position set
        if self.render_y is None:
            self.render_y = value
            
        # Update world coordinate atomically if in GMAP mode
        # BUT only if not being set from server packet (checked via stack inspection)
        if not self._is_server_update():
            self._update_world_coordinates()
            
    @property
    def x2(self) -> Optional[float]:
        """Get world X coordinate (across entire GMAP)"""
        return self._x2
        
    @x2.setter
    def x2(self, value: Optional[float]):
        """Set world X coordinate - DO NOT calculate GMAP segment"""
        self._x2 = value
        # GMAP segments should ONLY be set by explicit GMAPLEVELX/Y packets from server
        # Do not calculate or update gmaplevelx from x2 coordinates
                
    @property
    def y2(self) -> Optional[float]:
        """Get world Y coordinate (across entire GMAP)"""
        return self._y2
        
    @y2.setter
    def y2(self, value: Optional[float]):
        """Set world Y coordinate - DO NOT calculate GMAP segment"""
        self._y2 = value
        # GMAP segments should ONLY be set by explicit GMAPLEVELX/Y packets from server
        # Do not calculate or update gmaplevely from y2 coordinates
    
    @property
    def player_id(self) -> int:
        """Backward compatibility property"""
        return self.id
        
    def update_from_props(self, props: Dict[PlayerProp, Any]):
        """Update player from property dictionary"""
        for prop, value in props.items():
            self.set_property(prop, value)
    
    def _is_server_update(self) -> bool:
        """Check if we're currently processing a server update"""
        return self._processing_server_update
    
    def _update_world_coordinates(self):
        """Atomically update world coordinates from segment and local coordinates
        
        This should be called when local coordinates change to keep world
        coordinates in sync during movement within a GMAP.
        """
        # Only update if we have valid segment and local coordinates
        # This maintains x2/y2 in sync with local movement
        if self.gmaplevelx is not None and self._x is not None:
            self._x2 = self.gmaplevelx * 64 + self._x
        if self.gmaplevely is not None and self._y is not None:
            self._y2 = self.gmaplevely * 64 + self._y
    
    def set_gmap_position(self, gmaplevelx: int, gmaplevely: int, local_x: float, local_y: float):
        """Atomically set segment coordinates and local coordinates together"""
        # Set all coordinates together to prevent race conditions
        self.gmaplevelx = gmaplevelx
        self.gmaplevely = gmaplevely
        self._x = local_x
        self._y = local_y
        # Update world coordinates atomically
        self._update_world_coordinates()
        
        logger.info(f"Player {self.id} GMAP position set atomically: segment=({gmaplevelx},{gmaplevely}) local=({local_x:.1f},{local_y:.1f}) world=({self._x2:.1f},{self._y2:.1f})")
    
    def set_property(self, prop: PlayerProp, value: Any):
        """Set a single property"""
        # Mark that we're processing a server update to prevent coordinate recalculation
        old_processing = self._processing_server_update
        self._processing_server_update = True
        
        try:
            # Store raw property for debugging
            if hasattr(self, '_properties'):
                self._properties[prop] = value
            
            if prop == PlayerProp.PLPROP_NICKNAME:
                self.nickname = value
            elif prop == PlayerProp.PLPROP_X:
                old_x = self.x
                self.x = value / 2.0  # Convert from half-tiles
                if abs(old_x - self.x) > 10:  # Large jump indicates warp
                    pass  # Debug: Warp detected
            elif prop == PlayerProp.PLPROP_Y:
                old_y = self.y
                self.y = value / 2.0
                if abs(old_y - self.y) > 10:  # Large jump indicates warp
                    pass  # Debug: Warp detected
            elif prop == PlayerProp.PLPROP_Z:
                # Z has special encoding with +25 offset (handled in parser)
                self.z = value
            elif prop == PlayerProp.PLPROP_X2:
                # X2 is pixel coordinate - convert to tiles (16 pixels per tile)
                # Value has already been decoded from bit-shift format in packet handler
                self._x2 = value / 16.0
                logger.debug(f"Player {self.id} X2 pixels={value}, tiles={self._x2:.1f}")
            elif prop == PlayerProp.PLPROP_Y2:
                # Y2 is pixel coordinate - convert to tiles (16 pixels per tile)
                # Value has already been decoded from bit-shift format in packet handler
                self._y2 = value / 16.0
                logger.debug(f"Player {self.id} Y2 pixels={value}, tiles={self._y2:.1f}")
            elif prop == PlayerProp.PLPROP_CURLEVEL:
                self.level = value
            elif prop == PlayerProp.PLPROP_Z2:
                # High precision Z coordinate
                self.z2 = value
            elif prop == PlayerProp.PLPROP_SPRITE:
                # Handle tuple from new parser (sprite, direction)
                if isinstance(value, tuple):
                    sprite, direction = value
                    self.sprite_info = value
                    self.sprite = sprite  # Store the full sprite value
                    self.direction = Direction(direction)
                else:
                    # Legacy handling
                    self.sprite = value  # Store the full sprite value
                    self.direction = Direction(value % 4)
            elif prop == PlayerProp.PLPROP_CURPOWER:
                self.hearts = value / 2.0
            elif prop == PlayerProp.PLPROP_MAXPOWER:
                self.max_hearts = value / 2.0
            elif prop == PlayerProp.PLPROP_RUPEESCOUNT:
                self.rupees = value
            elif prop == PlayerProp.PLPROP_ARROWSCOUNT:
                self.arrows = value
            elif prop == PlayerProp.PLPROP_BOMBSCOUNT:
                self.bombs = value
            elif prop == PlayerProp.PLPROP_SWORDPOWER:
                # Handle tuple (power, image)
                if isinstance(value, tuple):
                    self.sword_info = value
                    self.sword_power = value[0]
                    if len(value) > 1:
                        self.sword_image = value[1]
                else:
                    self.sword_power = value
            elif prop == PlayerProp.PLPROP_SHIELDPOWER:
                # Handle tuple (power, image)
                if isinstance(value, tuple):
                    self.shield_info = value
                    self.shield_power = value[0]
                    if len(value) > 1:
                        self.shield_image = value[1]
                else:
                    self.shield_power = value
            elif prop == PlayerProp.PLPROP_GLOVEPOWER:
                self.glove_power = value
            elif prop == PlayerProp.PLPROP_BOMBPOWER:
                self.bomb_power = value
            elif prop == PlayerProp.PLPROP_HEADGIF:
                self.head_image = value
            elif prop == PlayerProp.PLPROP_BODYIMG:
                self.body_image = value
            elif prop == PlayerProp.PLPROP_GANI:
                self.gani = value
            elif prop == PlayerProp.PLPROP_CURCHAT:
                self.chat = value
            elif prop == PlayerProp.PLPROP_STATUS:
                self.status = value
            elif prop == PlayerProp.PLPROP_ACCOUNTNAME:
                self.account = value
            elif prop == PlayerProp.PLPROP_HORSEGIF:
                self.horse_image = value
            elif prop == PlayerProp.PLPROP_CARRYSPRITE:
                self.carry_sprite = value
            elif prop == PlayerProp.PLPROP_KILLSCOUNT:
                self.kills = value
            elif prop == PlayerProp.PLPROP_DEATHSCOUNT:
                self.deaths = value
            elif prop == PlayerProp.PLPROP_ONLINESECS:
                self.online_time = value
            elif prop == PlayerProp.PLPROP_RATING:
                # Handle tuple (rating, deviation)
                if isinstance(value, tuple):
                    self.rating_info = value
                    self.rating = value[0]
                else:
                    self.rating = value
            elif prop == PlayerProp.PLPROP_ID:
                self.id = value
            elif prop == PlayerProp.PLPROP_COMMUNITYNAME:
                self.community_name = value
            elif prop == PlayerProp.PLPROP_PLAYERLISTCATEGORY:
                self.playerlist_category = value
            elif prop == PlayerProp.PLPROP_COLORS:
                if isinstance(value, list) and len(value) >= 5:
                    self.colors = value[:5]
            elif prop == PlayerProp.PLPROP_GMAPLEVELX:
                old_gmaplevelx = self.gmaplevelx
                # Validate that value is a number, not a boolean
                if isinstance(value, bool):
                    logger.warning(f"Ignoring invalid GMAPLEVELX value: {value} (boolean)")
                    return
                if not isinstance(value, (int, float)) or value < 0 or value > 100:
                    logger.warning(f"Ignoring invalid GMAPLEVELX value: {value}")
                    return
                self.gmaplevelx = value
                # Update world coordinate if local coordinate is set
                # Each GMAP level is 64 tiles, so world coordinate = gmaplevel * 64 + local_tile
                if old_gmaplevelx != value:
                    # Update world coordinates atomically
                    self._update_world_coordinates()
                    logger.info(f"Player {self.id} GMAPLEVELX: {old_gmaplevelx} -> {value} (world x2={self._x2} tiles)")
                    # Check if this is our local player
                    if self.is_local:
                        logger.warning(f"*** SERVER SENT GMAPLEVELX: {value} ***")
            elif prop == PlayerProp.PLPROP_GMAPLEVELY:
                old_gmaplevely = self.gmaplevely
                # Validate that value is a number, not a boolean
                if isinstance(value, bool):
                    logger.warning(f"Ignoring invalid GMAPLEVELY value: {value} (boolean)")
                    return
                if not isinstance(value, (int, float)) or value < 0 or value > 100:
                    logger.warning(f"Ignoring invalid GMAPLEVELY value: {value}")
                    return
                self.gmaplevely = value
                # Update world coordinate if local coordinate is set
                # Each GMAP level is 64 tiles, so world coordinate = gmaplevel * 64 + local_tile
                if old_gmaplevely != value:
                    # Update world coordinates atomically  
                    self._update_world_coordinates()
                    logger.info(f"Player {self.id} GMAPLEVELY: {old_gmaplevely} -> {value} (world y2={self._y2} tiles)")
                    # Check if this is our local player
                    if self.is_local:
                        logger.warning(f"*** SERVER SENT GMAPLEVELY: {value} ***")
            # Handle attributes (gattrib1-30, plattrib1-5)
            elif PlayerProp.PLPROP_GATTRIB1 <= prop <= PlayerProp.PLPROP_GATTRIB30:
                attr_num = prop - PlayerProp.PLPROP_GATTRIB1 + 1
                self.attributes[f"gattrib{attr_num}"] = value
            # Note: PLATTRIB properties (42-46) were removed - they don't exist in the protocol
        finally:
            # Restore the flag after processing
            self._processing_server_update = old_processing
    
    def is_hidden(self) -> bool:
        """Check if player is hidden"""
        return bool(self.status & PlayerStatus.PLSTATUS_HIDDEN)
    
    def is_dead(self) -> bool:
        """Check if player is dead"""
        return bool(self.status & PlayerStatus.PLSTATUS_DEAD)
    
    def is_paused(self) -> bool:
        """Check if player is paused"""
        return bool(self.status & PlayerStatus.PLSTATUS_PAUSED)
    
    def has_spin(self) -> bool:
        """Check if player has spin attack"""
        return bool(self.status & PlayerStatus.PLSTATUS_HASSPIN)
    
    # ===== UNIFIED COORDINATE METHODS =====
    # These methods provide a consistent interface for coordinate access
    
    def get_render_position(self, coordinate_manager=None) -> Tuple[float, float]:
        """Get position for rendering purposes
        
        This method returns the appropriate coordinates based on the current mode:
        - GMAP mode: Returns world coordinates (x2, y2)
        - Single level mode: Returns local coordinates (x, y)
        
        Args:
            coordinate_manager: Optional coordinate manager for mode detection
            
        Returns:
            Tuple of (x, y) coordinates for rendering
        """
        # If we have a coordinate manager, use it
        if coordinate_manager:
            return coordinate_manager.get_render_coordinates(self)
            
        # Fallback logic when no coordinate manager available
        # If we have world coordinates, prefer them (indicates GMAP mode)
        if self.x2 is not None and self.y2 is not None:
            return (self.x2, self.y2)
        else:
            return (self.x, self.y)
    
    def get_physics_position(self, coordinate_manager=None) -> Tuple[float, float]:
        """Get position for physics calculations
        
        Physics should use the same coordinate system as rendering for consistency.
        
        Args:
            coordinate_manager: Optional coordinate manager for mode detection
            
        Returns:
            Tuple of (x, y) coordinates for physics
        """
        # Physics uses same coordinate system as rendering
        return self.get_render_position(coordinate_manager)
    
    def get_camera_target_position(self, coordinate_manager=None) -> Tuple[float, float]:
        """Get position to use as camera target
        
        Args:
            coordinate_manager: Optional coordinate manager for mode detection
            
        Returns:
            Tuple of (x, y) coordinates for camera targeting
        """
        return self.get_render_position(coordinate_manager)
    
    def is_in_gmap_mode(self) -> bool:
        """Check if this player appears to be in GMAP mode based on available data"""
        return (self.x2 is not None and self.y2 is not None and 
                self.gmaplevelx is not None and self.gmaplevely is not None)
    
    def get_coordinate_debug_info(self) -> dict:
        """Get detailed coordinate information for debugging"""
        return {
            "local": (self.x, self.y),
            "world": (self.x2, self.y2) if self.x2 is not None else None,
            "gmap_segment": (self.gmaplevelx, self.gmaplevely) if self.gmaplevelx is not None else None,
            "appears_in_gmap": self.is_in_gmap_mode(),
            "level": self.level
        }
    
    def update_movement(self, dt: float):
        """Update movement state based on time
        
        Args:
            dt: Delta time in seconds
        """
        if self.is_moving:
            self._movement_time += dt
            # Stop moving after 0.5 seconds of no position changes
            if self._movement_time > 0.5:
                self.is_moving = False
                self._movement_time = 0.0
    
    def update_interpolation(self, dt: float):
        """Update interpolated render position for smooth movement
        
        Args:
            dt: Delta time in seconds
        """
        # Use exponential smoothing for frame-rate independent interpolation
        # This ensures consistent smoothing regardless of framerate
        factor = 1.0 - pow(1.0 - self._interpolation_speed, dt * 60.0)  # Normalized to 60 FPS
        
        # Interpolate towards actual position
        self.render_x += (self._x - self.render_x) * factor
        self.render_y += (self._y - self.render_y) * factor
        
        # Snap to position if very close (prevents eternal tiny movements)
        if abs(self._x - self.render_x) < 0.01:
            self.render_x = self._x
        if abs(self._y - self.render_y) < 0.01:
            self.render_y = self._y
    
    # RC (Remote Control) Rights Management
    
    def has_rc_rights(self) -> bool:
        """Check if player has any RC rights"""
        return self.rc_rights > 0 or self.admin_level > 0
    
    def get_admin_level(self) -> int:
        """Get player's administrative level"""
        return max(self.admin_level, self.rc_rights)
    
    def set_player_rights(self, rights_level: int, admin_level: int = None) -> None:
        """Set player's rights and admin levels
        
        Args:
            rights_level: RC rights level (0 = no rights, 1+ = various admin levels)
            admin_level: Administrative level (if None, uses rights_level)
        """
        self.rc_rights = rights_level
        self.admin_level = admin_level if admin_level is not None else rights_level
        logger.debug(f"Player {self.account} rights updated: RC={self.rc_rights}, Admin={self.admin_level}")
    
    def get_rc_permission_level(self) -> str:
        """Get RC permission level as string for debugging
        
        Returns:
            String description of permission level
        """
        level = self.get_admin_level()
        if level == 0:
            return "NONE"
        elif level == 1:
            return "BASIC"
        elif level == 2:
            return "PLAYER_ADMIN"
        elif level == 3:
            return "SERVER_ADMIN"
        elif level == 4:
            return "FILE_ADMIN"
        elif level >= 5:
            return "SUPER_ADMIN"
        else:
            return f"LEVEL_{level}"
    
    def has_rc_file_access(self) -> bool:
        """Check if player has RC file management access"""
        return self.get_admin_level() >= 4
    
    def has_rc_server_admin(self) -> bool:
        """Check if player has RC server administration access"""
        return self.get_admin_level() >= 3
    
    def has_rc_player_admin(self) -> bool:
        """Check if player has RC player administration access"""
        return self.get_admin_level() >= 2
    
    def __repr__(self):
        return f"Player(id={self.id}, account='{self.account}', nickname='{self.nickname}', pos=({self.x:.1f},{self.y:.1f}), level='{self.level}')"