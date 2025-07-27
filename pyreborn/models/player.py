"""
Player model for tracking player state
"""

from typing import Optional, Dict, Any
from ..protocol.enums import PlayerProp, Direction, PlayerStatus
from ..utils.logging_config import ModuleLogger

logger = ModuleLogger.get_logger(__name__)

class Player:
    """Represents a player in the game"""
    
    def __init__(self, player_id: int = -1):
        # Identity
        self.id = player_id
        self.account = ""
        self.nickname = ""
        self.is_local = False  # Flag to identify local player
        
        # Position
        self._x = 30.0
        self._y = 30.0
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
        
        # GMAP properties
        self.gmaplevelx = None  # X segment in gmap
        self.gmaplevely = None  # Y segment in gmap
        
        # Store raw properties for debugging
        self._properties = {}
    
    @property
    def x(self) -> float:
        """Get local X coordinate (0-64 within segment)"""
        return self._x
        
    @x.setter
    def x(self, value: float):
        """Set local X coordinate and update world coordinate if in GMAP"""
        # No coordinate wrapping - each level is independent
        self._x = value
        # Update world coordinate if in GMAP mode
        if self.gmaplevelx is not None:
            self._x2 = self.gmaplevelx * 64 + self._x
            pass  # Debug print removed
            
    @property
    def y(self) -> float:
        """Get local Y coordinate (0-64 within segment)"""
        return self._y
        
    @y.setter
    def y(self, value: float):
        """Set local Y coordinate and update world coordinate if in GMAP"""
        # No coordinate wrapping - each level is independent
        self._y = value
        # Update world coordinate if in GMAP mode
        if self.gmaplevely is not None:
            self._y2 = self.gmaplevely * 64 + self._y
            pass  # Debug print removed
            
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
    
    def set_property(self, prop: PlayerProp, value: Any):
        """Set a single property"""
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
                self.direction = Direction(direction)
            else:
                # Legacy handling
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
        elif prop == PlayerProp.PLPROP_CURLEVEL:
            self.level = value
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
                self._x2 = value * 64 + self.x
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
                self._y2 = value * 64 + self.y
                logger.info(f"Player {self.id} GMAPLEVELY: {old_gmaplevely} -> {value} (world y2={self._y2} tiles)")
                # Check if this is our local player
                if self.is_local:
                    logger.warning(f"*** SERVER SENT GMAPLEVELY: {value} ***")
        # Handle attributes (gattrib1-30, plattrib1-5)
        elif PlayerProp.PLPROP_GATTRIB1 <= prop <= PlayerProp.PLPROP_GATTRIB30:
            attr_num = prop - PlayerProp.PLPROP_GATTRIB1 + 1
            self.attributes[f"gattrib{attr_num}"] = value
        # Note: PLATTRIB properties (42-46) were removed - they don't exist in the protocol
    
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
    
    def __repr__(self):
        return f"Player(id={self.id}, account='{self.account}', nickname='{self.nickname}', pos=({self.x:.1f},{self.y:.1f}), level='{self.level}')"