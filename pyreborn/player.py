"""
pyreborn - Player model
Simple dataclass for player state.
"""

from dataclasses import dataclass, field


@dataclass
class Player:
    """Minimal player state"""
    # Identity
    id: int = 0
    account: str = ""
    nickname: str = ""

    # Position
    x: float = 0.0
    y: float = 0.0
    level: str = ""
    direction: int = 2  # 0=up, 1=left, 2=down, 3=right

    # Stats
    hearts: float = 3.0
    max_hearts: float = 3.0
    rupees: int = 0
    mp: int = 0   # magic points (PLPROP_MAGICPOINTS)
    ap: int = 50  # alignment points (PLPROP_ALIGNMENT; 50 = neutral default)

    # Body colors (PLPROP_COLORS): list of palette indices
    # (5 entries on classic clients, 8 on v6 extended body colors).
    colors: list = field(default_factory=list)

    # Inventory counts
    arrows: int = 0
    bombs: int = 0
    glove_power: int = 0
    bomb_power: int = 1
    sword_power: int = 0
    shield_power: int = 0

    # Equipment images
    sword_image: str = ""
    shield_image: str = ""
    head_image: str = ""
    body_image: str = ""
    horse_image: str = ""
    horse_bushes: int = 0

    # Carrying state
    carry_sprite: int = 0
    carry_npc: int = 0
    carried_object_type: str = ""  # "bush", "rock", "pot", "sign", or ""
    carried_tile_ids: tuple = ()  # 4 tile IDs for 2x2 object: (tl, tr, bl, br)
    carried_tile_pos: tuple = ()  # Position where object was picked up: (x, y)

    # Sitting state
    is_sitting: bool = False
    sit_direction: int = 2  # Direction player is facing while sitting

    # Animation/visual state
    animation: str = "idle"  # Current gani animation name
    sprite: int = 0  # Sprite frame within animation
    status: int = 0  # Status flags (paused, hidden, etc.)
    chat: str = ""  # Current chat bubble text (CURCHAT)
    # Gani attributes: index (1..30) -> string, from PLPROP_GATTRIB1.. (#P1..
    # in script). A gani's ATTRn sprite layer draws gattribs[n] as an image
    # (hats, capes); servers also use the same slots as a plain data channel,
    # in which case the value simply names no file and nothing is drawn.
    gattribs: dict = field(default_factory=dict)

    # Hurt state tracking
    hurt_timeout: float = 0.0  # When hurt animation should end

    @property
    def is_hidden(self) -> bool:
        """Whether the server marked this player as hidden."""
        return bool(self.status & 0x02)

    def update_from_props(self, props: dict):
        """Update player state from parsed properties"""
        if 'id' in props:
            self.id = props['id']
        if 'account' in props:
            self.account = props['account']
        if 'nickname' in props:
            self.nickname = props['nickname']
        if 'x' in props:
            self.x = props['x']
        if 'y' in props:
            self.y = props['y']
        if 'level' in props:
            self.level = props['level']
        if 'direction' in props:
            self.direction = props['direction']
        if 'hearts' in props:
            self.hearts = props['hearts']
        if 'max_hearts' in props:
            self.max_hearts = props['max_hearts']
        if 'rupees' in props:
            self.rupees = props['rupees']
        if 'mp' in props:
            self.mp = props['mp']
        if 'ap' in props:
            self.ap = props['ap']
        if 'colors' in props:
            self.colors = props['colors']
        if 'animation' in props:
            self.animation = props['animation']
        if 'sprite' in props:
            self.sprite = props['sprite']
        if 'status' in props:
            self.status = props['status']
        if 'arrows' in props:
            self.arrows = props['arrows']
        if 'bombs' in props:
            self.bombs = props['bombs']
        if 'glove_power' in props:
            self.glove_power = props['glove_power']
        if 'bomb_power' in props:
            self.bomb_power = props['bomb_power']
        if 'sword_power' in props:
            self.sword_power = props['sword_power']
        if 'shield_power' in props:
            self.shield_power = props['shield_power']
        if 'sword_image' in props:
            self.sword_image = props['sword_image']
        if 'shield_image' in props:
            self.shield_image = props['shield_image']
        if 'head_image' in props:
            self.head_image = props['head_image']
        if 'body_image' in props:
            self.body_image = props['body_image']
        if 'horse_image' in props:
            self.horse_image = props['horse_image']
        if 'horse_bushes' in props:
            self.horse_bushes = props['horse_bushes']
        if 'carry_sprite' in props:
            self.carry_sprite = props['carry_sprite']
        if 'carry_npc' in props:
            self.carry_npc = props['carry_npc']
        for key, value in props.items():
            if key.startswith('gattrib') and key[7:].isdigit():
                self.gattribs[int(key[7:])] = value

        # Clamp hearts to valid range after updating both values
        if self.max_hearts > 0:
            self.hearts = max(0, min(self.hearts, self.max_hearts))

    def is_carrying(self) -> bool:
        """Check if player is currently carrying an object."""
        return self.carried_object_type != ""

    def pickup_object(self, object_type: str, tile_ids: tuple, pos: tuple):
        """Pick up a 2x2 liftable object.

        Args:
            object_type: Type of carried object
            tile_ids: Tuple of 4 tile IDs (top-left, top-right, bottom-left, bottom-right)
            pos: Position where object was picked up (x, y)
        """
        self.carried_object_type = object_type
        self.carried_tile_ids = tile_ids
        self.carried_tile_pos = pos
        # Stop sitting when picking up
        self.is_sitting = False

    def throw_object(self) -> tuple:
        """Throw the carried object.

        Returns:
            Tuple of (object_type, tile_ids, original_pos)
        """
        thrown_type = self.carried_object_type
        thrown_tiles = self.carried_tile_ids
        thrown_pos = self.carried_tile_pos
        self.carried_object_type = ""
        self.carried_tile_ids = ()
        self.carried_tile_pos = ()
        return (thrown_type, thrown_tiles, thrown_pos)

    def sit_down(self, direction: int = 2):
        """Sit down in the given direction.

        Args:
            direction: Direction to face while sitting (0=up, 1=left, 2=down, 3=right)
        """
        # Can't sit while carrying something
        if self.is_carrying():
            return False
        self.is_sitting = True
        self.sit_direction = direction
        return True

    def stand_up(self):
        """Stand up from sitting."""
        self.is_sitting = False
