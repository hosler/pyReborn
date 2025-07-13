"""
Player model for tracking player state
"""

from typing import Optional, Dict, Any
from ..protocol.enums import PlayerProp, Direction, PlayerStatus

class Player:
    """Represents a player in the game"""
    
    def __init__(self, player_id: int = -1):
        # Identity
        self.id = player_id
        self.account = ""
        self.nickname = ""
        
        # Position
        self.x = 30.0
        self.y = 30.0
        self.z = 0.0
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
        if prop == PlayerProp.PLPROP_NICKNAME:
            self.nickname = value
        elif prop == PlayerProp.PLPROP_X:
            self.x = value / 2.0  # Convert from half-tiles
        elif prop == PlayerProp.PLPROP_Y:
            self.y = value / 2.0
        elif prop == PlayerProp.PLPROP_Z:
            self.z = value
        elif prop == PlayerProp.PLPROP_X2:
            # High precision X coordinate (pixels)
            self.x = value / 16.0
        elif prop == PlayerProp.PLPROP_Y2:
            # High precision Y coordinate (pixels)
            self.y = value / 16.0
        elif prop == PlayerProp.PLPROP_Z2:
            # High precision Z coordinate
            self.z = value
        elif prop == PlayerProp.PLPROP_SPRITE:
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
            self.sword_power = value
        elif prop == PlayerProp.PLPROP_SHIELDPOWER:
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
        # Handle attributes (gattrib1-30, plattrib1-5)
        elif PlayerProp.PLPROP_GATTRIB1 <= prop <= PlayerProp.PLPROP_GATTRIB30:
            attr_num = prop - PlayerProp.PLPROP_GATTRIB1 + 1
            self.attributes[f"gattrib{attr_num}"] = value
        elif PlayerProp.PLPROP_PLATTRIB1 <= prop <= PlayerProp.PLPROP_PLATTRIB5:
            attr_num = prop - PlayerProp.PLPROP_PLATTRIB1 + 1
            self.player_attributes[f"plattrib{attr_num}"] = value
    
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