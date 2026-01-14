"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import sys
import time
from typing import Optional, Callable, Dict, List, Tuple

from .protocol import Protocol, WebSocketProtocol, IS_BROWSER
from .player import Player
from .packets import (
    PacketID,
    parse_level_name,
    parse_level_link,
    parse_level_sign,
    parse_explosion,
    parse_hit_objects,
    parse_minimap,
    parse_board_layer,
    parse_npc_props,
    parse_player_props,
    parse_playerwarp,
    parse_playerwarp2,
    parse_chat,
    parse_player_movement,
    parse_board_packet,
    parse_rawdata,
    parse_newworldtime,
    parse_other_player,
    parse_player_left,
    parse_hurt_player,
    parse_item_add,
    parse_item_del,
    parse_private_message,
    parse_baddy_props,
    parse_weapon_add,
    build_movement,
    build_chat,
    build_player_chat,
    build_sword_attack,
    build_bomb_drop,
    build_item_take,
    build_animation,
    build_hearts,
    build_hurt_response,
    build_attack_player,
    build_shoot,
    build_triggeraction,
    build_npc_props,
    build_flag_set,
    build_flag_del,
    build_level_warp,
    build_private_message,
    build_baddy_hurt,
    build_open_chest,
    build_horse_add,
    build_wantfile,
    parse_file,
    parse_filesendfailed
)

# NPC delete packet ID not in PacketID class yet
PLO_NPCDEL = 29


class Client:
    """
    Dead simple Reborn client.

    Usage:
        client = Client("localhost", 14900)
        client.connect()
        client.login("username", "password")
        client.move(1, 0)  # Move right
        client.say("Hello!")
        client.disconnect()
    """

    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "2.22",
                 proxy_url: Optional[str] = None):
        """
        Create a new client.

        Args:
            host: Server hostname or IP
            port: Server port (default 14900)
            version: Protocol version ("2.22" or "6.037")
            proxy_url: WebSocket proxy URL for browser (e.g., "ws://localhost:14901")
                       Required when running in browser, ignored otherwise.
        """
        self.host = host
        self.port = port
        self.version = version
        self.proxy_url = proxy_url

        # Use WebSocketProtocol in browser, regular Protocol otherwise
        if IS_BROWSER:
            if not proxy_url:
                raise ValueError("proxy_url is required when running in browser")
            self._protocol = WebSocketProtocol(proxy_url, host, port, version)
        else:
            self._protocol = Protocol(host, port, version)

        self.player = Player()

        # Authentication state
        self._authenticated = False
        self._login_time = 0.0

        # Level data: 4096 tile IDs (64x64 grid) for current level
        self.tiles: List[int] = []
        self._raw_data_expected = 0
        self._raw_buffer = b""

        # GMAP support: multiple levels keyed by level name
        self.levels: Dict[str, List[int]] = {}
        self._current_level_name = ""  # The player's actual level (set once at login)
        self._pending_level_name = ""  # Track which level data is being received

        # GMAP grid: maps (x, y) -> level_name
        self.gmap_grid: Dict[Tuple[int, int], str] = {}
        self.gmap_width = 0
        self.gmap_height = 0
        self._gmap_base_level = ""  # The level player started in when GMAP was loaded
        self._gmap_spawn_x = 0  # GMAP grid x from PLO_PLAYERWARP2
        self._gmap_spawn_y = 0  # GMAP grid y from PLO_PLAYERWARP2
        # Offset between world coordinate grid and GMAP grid
        # world_grid = gmap_grid + offset
        self._gmap_offset_x = 0
        self._gmap_offset_y = 0

        # Links: maps level_name -> list of link dicts
        self.links: Dict[str, List[dict]] = {}

        # NPCs: maps npc_id -> npc dict with x, y, image, etc.
        self.npcs: Dict[int, dict] = {}

        # Other players: maps player_id -> player dict with x, y, nickname, account, etc.
        self.players: Dict[int, dict] = {}

        # Items on ground: maps (x, y) -> item_type string
        self.items: Dict[Tuple[float, float], str] = {}

        # Baddies (enemies): maps baddy_id -> baddy dict with x, y, type, power, etc.
        self.baddies: Dict[int, dict] = {}

        # Weapons: maps weapon_name -> weapon dict with name, image, script
        self.weapons: Dict[str, dict] = {}

        # Server time (from heartbeat)
        self.server_time = 0

        # Packet callbacks: packet_id -> handler(data)
        self.on_packet: Dict[int, Callable[[bytes], None]] = {}

        # Chat callback: handler(player_id, message)
        self.on_chat: Optional[Callable[[int, str], None]] = None

        # Level update callback: handler(tiles)
        self.on_level: Optional[Callable[[List[int]], None]] = None

        # Hurt callback: handler(player_id, damage, damage_type, source_x, source_y)
        self.on_hurt: Optional[Callable[[int, float, int, int, int], None]] = None

        # Item callback: handler(x, y, item_type, added) - added=True for spawn, False for remove
        self.on_item: Optional[Callable[[float, float, str, bool], None]] = None

        # Private message callback: handler(from_player_id, message)
        self.on_pm: Optional[Callable[[int, str], None]] = None

        # Baddy callback: handler(baddy_id, baddy_props)
        self.on_baddy: Optional[Callable[[int, dict], None]] = None

        # Weapon added callback: handler(weapon_name, weapon_data)
        self.on_weapon_add: Optional[Callable[[str, dict], None]] = None

        # File callback: handler(filename, data) - called when file is received
        self.on_file: Optional[Callable[[str, bytes], None]] = None

        # Sign callback: handler(x, y, text) - when sign text is received
        self.on_sign: Optional[Callable[[float, float, str], None]] = None

        # Explosion callback: handler(x, y, radius, power) - explosion effect
        self.on_explosion: Optional[Callable[[float, float, int, int], None]] = None

        # Hit objects callback: handler(x, y, power, player_id) - object hit feedback
        self.on_hit_objects: Optional[Callable[[float, float, int, int], None]] = None

        # Minimap callback: handler(data) - minimap data received
        self.on_minimap: Optional[Callable[[bytes], None]] = None

        # Board layer callback: handler(layer, x, y, tiles) - extra level layer
        self.on_board_layer: Optional[Callable[[int, int, int, bytes], None]] = None

        # Level signs: maps (x, y) -> text
        self.signs: Dict[Tuple[float, float], str] = {}

        # Active explosions for rendering: list of {x, y, radius, power, time}
        self.active_explosions: List[dict] = []

        # Board layers: maps layer_id -> tile data
        self.board_layers: Dict[int, bytes] = {}

        # File download tracking
        self._pending_files: set = set()  # Files we're waiting for
        self._received_files: Dict[str, bytes] = {}  # Received files
        self._failed_files: set = set()  # Files that failed to download

        # Auto-respond settings
        self.auto_respond_hurt = True  # Automatically send hurt response with health update
        self.hurt_animation = "hurt"   # Animation to use when hurt

    # =========================================================================
    # Connection
    # =========================================================================

    def connect(self) -> bool:
        """Connect to the server. Returns True if successful."""
        return self._protocol.connect()

    def disconnect(self):
        """Disconnect from the server."""
        self._protocol.disconnect()
        self._authenticated = False

    @property
    def connected(self) -> bool:
        """Check if connected to server."""
        return self._protocol.connected

    @property
    def authenticated(self) -> bool:
        """Check if logged in."""
        return self._authenticated

    @property
    def is_gmap(self) -> bool:
        """Check if currently in a GMAP level.

        Returns True if any of these conditions are met:
        1. We have GMAP dimensions from loading a .gmap file
        2. The spawn packet indicated GMAP grid offsets
        3. Player level name ends with .gmap
        """
        if self.gmap_width > 0 and self.gmap_height > 0:
            return True
        # Also detect from spawn packet or level name
        if self._gmap_spawn_x > 0 or self._gmap_spawn_y > 0:
            return True
        if self.player.level and self.player.level.endswith('.gmap'):
            return True
        return False

    # =========================================================================
    # Authentication
    # =========================================================================

    def login(self, username: str, password: str, timeout: float = 5.0) -> bool:
        """
        Login to the server.

        Args:
            username: Account name
            password: Account password
            timeout: How long to wait for login response (seconds)

        Returns:
            True if login successful
        """
        if not self.connected:
            return False

        # Send login packet
        if not self._protocol.send_login(username, password):
            return False

        self.player.account = username
        self._login_time = time.time()

        # Wait for authentication response
        start = time.time()
        while time.time() - start < timeout:
            self.update(timeout=0.1)
            if self._authenticated:
                return True

        return False

    # =========================================================================
    # Actions
    # =========================================================================

    def move(self, dx: int, dy: int, step: float = 0.25) -> bool:
        """
        Move the player.

        Args:
            dx: X direction (-1=left, 0=none, 1=right)
            dy: Y direction (-1=up, 0=none, 1=down)
            step: Movement step size in tiles (default 0.5 for half-tile precision)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Calculate new position using step size
        new_x = self.player.x + dx * step
        new_y = self.player.y + dy * step

        # Determine direction
        if dx > 0:
            direction = 3  # right
        elif dx < 0:
            direction = 1  # left
        elif dy > 0:
            direction = 2  # down
        elif dy < 0:
            direction = 0  # up
        else:
            direction = self.player.direction

        # Check if we're crossing into a different GMAP level BEFORE sending packet
        crossing_boundary = False
        new_level_name = None
        if self.is_gmap:
            # Calculate which grid cell the new position is in
            import math
            new_grid_x = math.floor(new_x / 64)
            new_grid_y = math.floor(new_y / 64)
            old_grid_x = math.floor(self.player.x / 64)
            old_grid_y = math.floor(self.player.y / 64)

            # If we're changing grid cells, we need to notify the server
            if (new_grid_x, new_grid_y) != (old_grid_x, old_grid_y):
                # Look up the new level name from the GMAP grid
                new_level = self.gmap_grid.get((new_grid_x, new_grid_y))
                if new_level:
                    new_level_name = new_level
                    crossing_boundary = True

        # Build and send movement packet
        # Always send LOCAL coordinates (0-63) - server tracks level separately
        local_x = new_x % 64
        local_y = new_y % 64
        data = build_movement(local_x, local_y, direction)
        if self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            # Update local state
            self.player.x = new_x
            self.player.y = new_y
            self.player.direction = direction

            # If crossing GMAP boundary, send a level warp to notify server
            if crossing_boundary and new_level_name:
                # Send PLI_LEVELWARP to tell server we changed levels
                warp_data = build_level_warp(local_x, local_y, new_level_name)
                self._protocol.send_packet(PacketID.PLI_LEVELWARP, warp_data)
                self._current_level_name = new_level_name
                # Request adjacent levels for new position
                self.request_adjacent_levels()

            return True

        return False

    def say(self, message: str) -> bool:
        """
        Send a chat message.

        Args:
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_chat(message)
        return self._protocol.send_packet(PacketID.PLI_TOALL, data)

    def send_level_chat(self, message: str) -> bool:
        """
        Send local level chat (shows above player's head).
        Uses PLPROP_CURCHAT (prop 12) via PLI_PLAYERPROPS.

        Args:
            message: Message to display

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_player_chat(message)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def sword_attack(self, direction: Optional[int] = None) -> bool:
        """
        Swing sword in the given direction.

        Args:
            direction: 0=up, 1=left, 2=down, 3=right (default: current direction)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if direction is None:
            direction = self.player.direction

        # Always send local coords (0-63)
        local_x = self.player.x % 64
        local_y = self.player.y % 64
        data = build_sword_attack(local_x, local_y, direction)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def drop_bomb(self, power: int = 1) -> bool:
        """
        Drop a bomb at current position.

        Args:
            power: Bomb power (1-3)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_bomb_drop(self.player.x, self.player.y, power)
        return self._protocol.send_packet(PacketID.PLI_EXPLOSION, data)

    def pickup_item(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """
        Pick up an item at position.

        Args:
            x: Item X position (default: player position)
            y: Item Y position (default: player position)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_item_take(x, y)
        return self._protocol.send_packet(PacketID.PLI_ITEMTAKE, data)

    def set_animation(self, gani_name: str) -> bool:
        """
        Set player animation (gani).

        Args:
            gani_name: Animation name (e.g., "idle", "walk", "sword", "hurt")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        self.player.animation = gani_name
        # Always send local coords (0-63)
        local_x = self.player.x % 64
        local_y = self.player.y % 64
        data = build_animation(gani_name, local_x, local_y, self.player.direction)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def send_hearts(self, hearts: Optional[float] = None) -> bool:
        """
        Send current hearts value to server.

        Args:
            hearts: Hearts value (default: use player's current hearts)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if hearts is not None:
            self.player.hearts = max(0, min(hearts, self.player.max_hearts))

        data = build_hearts(self.player.hearts)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def respond_to_hurt(self, damage: float, gani_name: str = "hurt") -> bool:
        """
        Respond to being hurt by sending updated health and hurt animation.
        This should be called when the client receives a PLO_HURTPLAYER packet.

        Args:
            damage: Damage received in hearts
            gani_name: Hurt animation name (default "hurt")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Calculate new health (client is source of truth)
        new_hearts = max(0, self.player.hearts - damage)
        self.player.hearts = new_hearts
        self.player.animation = gani_name
        self.player.hurt_timeout = time.time() + 0.5  # 500ms hurt animation

        # Send combined hurt response with health + animation
        data = build_hurt_response(
            new_hearts,
            self.player.x,
            self.player.y,
            self.player.direction,
            gani_name
        )
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def attack_player(self, victim_id: int, damage: float = 0.5,
                      knockback_x: int = 0, knockback_y: int = 0) -> bool:
        """
        Attack another player.

        Args:
            victim_id: Player ID of the target
            damage: Damage in hearts (default 0.5 = 1 half-heart)
            knockback_x: Knockback direction X (-128 to 127)
            knockback_y: Knockback direction Y (-128 to 127)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_attack_player(victim_id, knockback_x, knockback_y, damage)
        return self._protocol.send_packet(PacketID.PLI_HURTPLAYER, data)

    def shoot(self, direction: Optional[int] = None, speed: int = 3,
              gani: str = "arrow", gravity: int = 0) -> bool:
        """
        Shoot a projectile (arrow, fireball, etc.).

        Args:
            direction: 0=up, 1=left, 2=down, 3=right (default: player direction)
            speed: Projectile speed (1-127, default 3)
            gani: Projectile animation name (default "arrow")
            gravity: Gravity effect (0 for flat shot, 8 for arc)

        Returns:
            True if packet sent successfully
        """
        import math

        if not self.connected or not self._authenticated:
            return False

        if direction is None:
            direction = self.player.direction

        # Convert direction to angle (radians)
        # 0=up (-pi/2), 1=left (pi), 2=down (pi/2), 3=right (0)
        angles = {
            0: -math.pi / 2,  # up
            1: math.pi,       # left
            2: math.pi / 2,   # down
            3: 0              # right
        }
        angle = angles.get(direction, 0)

        data = build_shoot(
            self.player.x, self.player.y, 0,
            angle, speed, gani, "", gravity
        )
        return self._protocol.send_packet(PacketID.PLI_SHOOT2, data)

    def triggeraction(self, action: str, x: Optional[float] = None,
                      y: Optional[float] = None, npc_id: int = 0) -> bool:
        """
        Trigger a server-side action.

        Args:
            action: Action string (e.g., "warp,level.nw,30,30" or "serverside,func")
            x: X position (default: player position)
            y: Y position (default: player position)
            npc_id: NPC ID to trigger on (0 for level/weapon triggers)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_triggeraction(x, y, action, npc_id)
        return self._protocol.send_packet(PacketID.PLI_TRIGGERACTION, data)

    def send_npc_props(self, npc_id: int, prop_name: str, value: str) -> bool:
        """
        Send NPC properties update (char props like #P1, #P2).

        Args:
            npc_id: NPC ID to update
            prop_name: Property name (e.g., "P1", "P2", "P3")
            value: Property value

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_npc_props(npc_id, prop_name, value)
        return self._protocol.send_packet(PacketID.PLI_NPCPROPS, data)

    def set_flag(self, flag_name: str, flag_value: str = "") -> bool:
        """
        Set a player flag.

        Args:
            flag_name: Name of the flag
            flag_value: Value to set (empty for boolean true)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_flag_set(flag_name, flag_value)
        return self._protocol.send_packet(PacketID.PLI_FLAGSET, data)

    def del_flag(self, flag_name: str) -> bool:
        """
        Delete a player flag.

        Args:
            flag_name: Name of the flag to delete

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_flag_del(flag_name)
        return self._protocol.send_packet(PacketID.PLI_FLAGDEL, data)

    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.0) -> bool:
        """
        Warp to a different level.

        Args:
            level_name: Name of the level to warp to (e.g., "level.nw")
            x: Destination X position in tiles (default 30.0 = center)
            y: Destination Y position in tiles (default 30.0 = center)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Update local state
        self.player.x = x
        self.player.y = y
        self._current_level_name = level_name
        self._pending_level_name = level_name

        data = build_level_warp(x, y, level_name)
        return self._protocol.send_packet(PacketID.PLI_LEVELWARP, data)

    def send_pm(self, player_id: int, message: str) -> bool:
        """
        Send a private message to another player by ID.

        Args:
            player_id: Numeric player ID of the recipient
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_private_message([player_id], message)
        return self._protocol.send_packet(PacketID.PLI_PRIVATEMESSAGE, data)

    def send_pm_multi(self, player_ids: list, message: str) -> bool:
        """
        Send a private message to multiple players by ID.

        Args:
            player_ids: List of numeric player IDs
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_private_message(player_ids, message)
        return self._protocol.send_packet(PacketID.PLI_PRIVATEMESSAGE, data)

    def get_player_id_by_account(self, account: str) -> int:
        """
        Look up a player ID by account name.

        Args:
            account: Account name to search for

        Returns:
            Player ID if found, 0 otherwise
        """
        account_lower = account.lower()
        for pid, player in self.players.items():
            if player.get('account', '').lower() == account_lower:
                return pid
        return 0

    def hurt_baddy(self, baddy_id: int, damage: float = 1.0) -> bool:
        """
        Attack a baddy/enemy.

        Args:
            baddy_id: ID of the baddy to attack
            damage: Damage in hearts (default 1.0)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_baddy_hurt(baddy_id, damage)
        return self._protocol.send_packet(PacketID.PLI_BADDYHURT, data)

    def open_chest(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """
        Open a chest at the specified position.

        Args:
            x: Chest X position (default: player position)
            y: Chest Y position (default: player position)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y

        data = build_open_chest(x, y)
        return self._protocol.send_packet(PacketID.PLI_OPENCHEST, data)

    def mount_horse(self, x: Optional[float] = None, y: Optional[float] = None,
                    image: str = "horse.png", direction: Optional[int] = None) -> bool:
        """
        Add/mount a horse at the specified position.

        Args:
            x: Horse X position (default: player position)
            y: Horse Y position (default: player position)
            image: Horse image name (default "horse.png")
            direction: Horse direction (default: player direction)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        if direction is None:
            direction = self.player.direction

        data = build_horse_add(x, y, image, direction)
        return self._protocol.send_packet(PacketID.PLI_HORSEADD, data)

    def request_level(self, level_name: str) -> bool:
        """
        Request an adjacent GMAP level.

        Args:
            level_name: Name of the level to request (e.g., "chicken2.nw")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Build packet: GUInt5 (modtime=0) + level name
        data = bytearray()
        # modtime = 0, encoded as 5 GCHARs
        for _ in range(5):
            data.append(32)  # 0 + 32
        data.extend(level_name.encode('latin-1'))

        return self._protocol.send_packet(PacketID.PLI_ADJACENTLEVEL, data)

    def request_file(self, filename: str) -> bool:
        """
        Request a file from the server.

        Args:
            filename: Name of the file to request (e.g., "image.png")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        self._pending_files.add(filename)
        data = build_wantfile(filename)
        return self._protocol.send_packet(PacketID.PLI_WANTFILE, data)

    def get_file(self, filename: str) -> Optional[bytes]:
        """
        Get a previously downloaded file.

        Args:
            filename: Name of the file

        Returns:
            File data as bytes, or None if not downloaded
        """
        return self._received_files.get(filename)

    def has_file(self, filename: str) -> bool:
        """Check if a file has been downloaded."""
        return filename in self._received_files

    def is_file_pending(self, filename: str) -> bool:
        """Check if a file download is pending."""
        return filename in self._pending_files

    def did_file_fail(self, filename: str) -> bool:
        """Check if a file download failed."""
        return filename in self._failed_files

    def load_gmap(self, gmap_data: str):
        """
        Parse GMAP data to build the level grid.

        Args:
            gmap_data: Contents of .gmap file
        """
        self.gmap_grid.clear()
        # Save the current level as the base for position calculations
        self._gmap_base_level = self._current_level_name
        lines = gmap_data.strip().split('\n')

        in_levelnames = False
        level_names = []

        for line in lines:
            line = line.strip()
            if line.startswith('WIDTH'):
                self.gmap_width = int(line.split()[1])
            elif line.startswith('HEIGHT'):
                self.gmap_height = int(line.split()[1])
            elif line == 'LEVELNAMES':
                in_levelnames = True
            elif line == 'LEVELNAMESEND':
                in_levelnames = False
            elif in_levelnames:
                # Parse level names from CSV format
                parts = line.replace('"', '').rstrip(',').split(',')
                for name in parts:
                    name = name.strip()
                    if name:
                        level_names.append(name)

        # Build grid mapping
        for i, name in enumerate(level_names):
            x = i % self.gmap_width
            y = i // self.gmap_width
            self.gmap_grid[(x, y)] = name


        # With GMAP-relative coordinates, there's no offset needed
        # player.x and player.y are directly in GMAP tile coordinates
        # grid position = player.x // 64, player.y // 64
        self._gmap_offset_x = 0
        self._gmap_offset_y = 0

        # Set current level based on spawn grid position from PLO_PLAYERWARP2
        # (which is received before GMAP file, so we can't use gmap_grid at that time)
        # If we have a spawn grid position, use it; otherwise fall back to calculating from coords
        if self._gmap_spawn_x != 0 or self._gmap_spawn_y != 0:
            spawn_pos = (self._gmap_spawn_x, self._gmap_spawn_y)
        else:
            grid_x = int(self.player.x // 64)
            grid_y = int(self.player.y // 64)
            spawn_pos = (grid_x, grid_y)

        if spawn_pos in self.gmap_grid:
            self._current_level_name = self.gmap_grid[spawn_pos]
            self._gmap_base_level = self._current_level_name

            # Convert player coords to world coords if they're still local
            # (PLAYERWARP2 arrives before GMAP, so coords are local at that point)
            if self.player.x < 64 and self.player.y < 64:
                self.player.x = self.player.x + spawn_pos[0] * 64
                self.player.y = self.player.y + spawn_pos[1] * 64

        # Update existing NPC coords to world coords now that we have the GMAP grid
        self._update_npc_world_coords()

    def _update_npc_world_coords(self):
        """Update NPC world coordinates based on their level's grid position."""
        for npc_id, npc in self.npcs.items():
            npc_level = npc.get('_level')
            if not npc_level:
                continue  # No level info
            # Find the level's grid position
            for (gx, gy), level_name in self.gmap_grid.items():
                if level_name == npc_level:
                    if 'x' in npc:
                        npc['world_x'] = npc['x'] + gx * 64
                    if 'y' in npc:
                        npc['world_y'] = npc['y'] + gy * 64
                    break

    def get_adjacent_levels(self, level_name: str) -> List[str]:
        """
        Get names of levels adjacent to the given level.

        Args:
            level_name: Current level name

        Returns:
            List of adjacent level names
        """
        # Find current level's grid position
        current_pos = None
        for pos, name in self.gmap_grid.items():
            if name == level_name:
                current_pos = pos
                break

        if not current_pos:
            return []

        # Get all 8 adjacent positions
        x, y = current_pos
        adjacent = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                adj_pos = (x + dx, y + dy)
                if adj_pos in self.gmap_grid:
                    adjacent.append(self.gmap_grid[adj_pos])

        return adjacent

    def request_adjacent_levels(self) -> int:
        """
        Request all adjacent levels based on current position.

        Returns:
            Number of levels requested
        """
        if not self._current_level_name:
            return 0

        adjacent = self.get_adjacent_levels(self._current_level_name)
        count = 0
        for level_name in adjacent:
            if level_name not in self.levels:
                self.request_level(level_name)
                count += 1

        return count

    # =========================================================================
    # Update Loop
    # =========================================================================

    def update(self, timeout: float = 0.01) -> List[Tuple[int, bytes]]:
        """
        Process incoming packets. Call this regularly (e.g., in game loop).

        Args:
            timeout: How long to wait for packets (seconds)

        Returns:
            List of (packet_id, data) tuples received
        """
        packets = self._protocol.recv_packets(timeout)

        for packet_id, data in packets:
            self._handle_packet(packet_id, data)

        return packets

    def _handle_packet(self, packet_id: int, data: bytes):
        """Handle a received packet."""

        # Level name - track which level we're receiving data for
        if packet_id == PacketID.PLO_LEVELNAME:
            level_name = parse_level_name(data)
            # .nw files are actual levels, .gmap is the world map name
            if level_name.endswith('.nw'):
                # Only update if we don't have a base level yet, or this is the first level
                if not self._current_level_name:
                    self._current_level_name = level_name
                # Track for tile storage
                self._pending_level_name = level_name
            # Set player.level to GMAP name if available, else level name
            if level_name.endswith('.gmap') or not self.player.level:
                self.player.level = level_name

        # Player properties (our player data)
        elif packet_id == PacketID.PLO_PLAYERPROPS:
            props = parse_player_props(data)

            # Check if we're in GMAP mode
            has_gmap_grid = self.gmap_width > 0 and self.gmap_height > 0
            level_is_gmap = self.player.level and self.player.level.endswith('.gmap')
            in_gmap = has_gmap_grid or level_is_gmap

            # Server sends world coordinates in PixelX/PixelY (props 78/79)
            # For non-GMAP levels, convert to local coordinates (0-63)
            if not in_gmap and 'x' in props:
                props['x'] = props['x'] % 64
            if not in_gmap and 'y' in props:
                props['y'] = props['y'] % 64

            self.player.update_from_props(props)

            # First props packet means we're authenticated
            if not self._authenticated:
                self._authenticated = True

        # Chat message OR movement update
        elif packet_id == PacketID.PLO_TOALL:
            # Try to parse as movement update first
            movement = parse_player_movement(data)
            if movement and 'id' in movement:
                player_id = movement['id']
                # Create player entry if not exists
                if player_id not in self.players:
                    self.players[player_id] = {'id': player_id}
                # Update position and other movement data
                for key in ('x', 'y', 'direction', 'animation', 'level'):
                    if key in movement:
                        self.players[player_id][key] = movement[key]
            else:
                # Regular chat message
                player_id, message = parse_chat(data)
                if self.on_chat:
                    self.on_chat(player_id, message)

        # PLO_SHOWIMG (32) - also carries level chat messages
        elif packet_id == PacketID.PLO_SHOWIMG:
            # Same format as PLO_TOALL for chat: gshort(player_id) + message
            player_id, message = parse_chat(data)
            if message and self.on_chat:
                self.on_chat(player_id, message)

        # PLO_NPCWEAPONADD (33) - weapon being added to player
        elif packet_id == PacketID.PLO_NPCWEAPONADD:
            weapon = parse_weapon_add(data)
            if weapon and weapon.get('name'):
                self.weapons[weapon['name']] = weapon
                # Callback for weapon added
                if self.on_weapon_add:
                    self.on_weapon_add(weapon['name'], weapon)

        # PLO_HURTPLAYER (40) - player hurt/damage notification
        elif packet_id == PacketID.PLO_HURTPLAYER:
            hurt_info = parse_hurt_player(data)
            if hurt_info:
                attacker_id = hurt_info.get('player_id', 0)
                damage = hurt_info.get('damage', 0)

                # We got hurt - client is source of truth for health
                # Auto-respond with new health and hurt animation
                if self.auto_respond_hurt and damage > 0:
                    self.respond_to_hurt(damage, self.hurt_animation)

                # Callback (after responding, so player.hearts is updated)
                if self.on_hurt:
                    self.on_hurt(
                        attacker_id,
                        damage,
                        hurt_info.get('damage_type', 0),
                        hurt_info.get('source_x', 0),
                        hurt_info.get('source_y', 0)
                    )

        # PLO_ITEMADD (22) - item added to level
        elif packet_id == PacketID.PLO_ITEMADD:
            item_info = parse_item_add(data)
            if item_info:
                x = item_info.get('x', 0)
                y = item_info.get('y', 0)
                item_type = item_info.get('type', '')
                self.items[(x, y)] = item_type
                if self.on_item:
                    self.on_item(x, y, item_type, True)

        # PLO_ITEMDEL (23) - item removed from level
        elif packet_id == PacketID.PLO_ITEMDEL:
            item_info = parse_item_del(data)
            if item_info:
                x = item_info.get('x', 0)
                y = item_info.get('y', 0)
                item_type = self.items.pop((x, y), '')
                if self.on_item:
                    self.on_item(x, y, item_type, False)

        # PLO_PRIVATEMESSAGE (37) - private message received
        elif packet_id == PacketID.PLO_PRIVATEMESSAGE:
            pm_info = parse_private_message(data)
            if pm_info and self.on_pm:
                self.on_pm(pm_info.get('from_id', 0), pm_info.get('message', ''))

        # PLO_BADDYPROPS (2) - baddy/enemy properties
        elif packet_id == PacketID.PLO_BADDYPROPS:
            props = parse_baddy_props(data)
            if props and 'id' in props:
                baddy_id = props['id']
                if baddy_id in self.baddies:
                    self.baddies[baddy_id].update(props)
                else:
                    self.baddies[baddy_id] = props
                if self.on_baddy:
                    self.on_baddy(baddy_id, props)

        # PLO_LEVELBOARD (0) - not tile data, possibly level metadata
        # Tile data comes via PLO_BOARDPACKET (101) instead

        # Level board tiles (uncompressed, 8192 bytes)
        elif packet_id == PacketID.PLO_BOARDPACKET:
            tiles = parse_board_packet(data)
            # Store in levels dict using the pending level name
            level_for_tiles = self._pending_level_name or self._current_level_name
            if level_for_tiles:
                self.levels[level_for_tiles] = tiles
            # Always update self.tiles with the latest (for fallback rendering)
            self.tiles = tiles
            if self.on_level:
                self.on_level(tiles)

        # Raw data announcement
        elif packet_id == PacketID.PLO_RAWDATA:
            self._raw_data_expected = parse_rawdata(data)

        # File transfer
        elif packet_id == PacketID.PLO_FILE:
            file_info = parse_file(data)
            if file_info and file_info['filename']:
                filename = file_info['filename']
                file_data = file_info['data']
                self._received_files[filename] = file_data
                self._pending_files.discard(filename)
                if self.on_file:
                    self.on_file(filename, file_data)

        # File send failed
        elif packet_id == PacketID.PLO_FILESENDFAILED:
            filename = parse_filesendfailed(data)
            if filename:
                self._failed_files.add(filename)
                self._pending_files.discard(filename)

        # Heartbeat / time sync
        elif packet_id == PacketID.PLO_NEWWORLDTIME:
            info = parse_newworldtime(data)
            self.server_time = info.get('time', 0)

        # Player warp/spawn position (packet 14) - non-GMAP levels
        elif packet_id == PacketID.PLO_PLAYERWARP:
            warp = parse_playerwarp(data)
            if warp:
                # x, y are local coords (0-63 range for non-GMAP levels)
                self.player.x = warp.get('x', 0)
                self.player.y = warp.get('y', 0)
                level = warp.get('level', '')
                if level:
                    self.player.level = level

        # Player warp with GMAP position (packet 49)
        elif packet_id == PacketID.PLO_PLAYERWARP2:
            warp = parse_playerwarp2(data)
            if warp:
                # x, y are local coords within the level/grid cell
                local_x = warp.get('x', 0)
                local_y = warp.get('y', 0)
                gmap_x = warp.get('gmap_x', 0)
                gmap_y = warp.get('gmap_y', 0)

                # Check if we're in GMAP mode:
                # 1. Have a gmap grid loaded, OR
                # 2. Level name ends with .gmap, OR
                # 3. The warp packet itself has non-zero gmap grid coords
                has_gmap_grid = self.gmap_width > 0 and self.gmap_height > 0
                level_is_gmap = self.player.level and self.player.level.endswith('.gmap')
                warp_has_grid = gmap_x != 0 or gmap_y != 0

                # Only use world coords if we have a loaded gmap grid or level is explicitly a .gmap
                # If just warp_has_grid but no gmap loaded, use local coords
                in_gmap = has_gmap_grid or level_is_gmap

                if in_gmap:
                    # Convert to world coords by adding grid_offset * 64
                    self.player.x = local_x + gmap_x * 64
                    self.player.y = local_y + gmap_y * 64
                else:
                    # Not in GMAP - use local coordinates only
                    self.player.x = local_x
                    self.player.y = local_y

                # Store grid position for GMAP detection
                self._gmap_spawn_x = gmap_x
                self._gmap_spawn_y = gmap_y

                # Update level name from gmap grid if available
                if self.gmap_grid and (gmap_x, gmap_y) in self.gmap_grid:
                    self._current_level_name = self.gmap_grid[(gmap_x, gmap_y)]

        # Level links
        elif packet_id == PacketID.PLO_LEVELLINK:
            link = parse_level_link(data)
            level_for_link = self._pending_level_name or self._current_level_name
            if link and level_for_link:
                if level_for_link not in self.links:
                    self.links[level_for_link] = []
                self.links[level_for_link].append(link)

        # NPC properties
        elif packet_id == PacketID.PLO_NPCPROPS:
            props = parse_npc_props(data)
            if props and 'id' in props:
                npc_id = props['id']
                # Associate NPC with the pending/current level
                npc_level = self._pending_level_name or self._current_level_name
                props['_level'] = npc_level

                # Convert NPC local coords to world coords if in GMAP
                if self.gmap_grid and npc_level:
                    # Find the level's grid position
                    for (gx, gy), level_name in self.gmap_grid.items():
                        if level_name == npc_level:
                            if 'x' in props:
                                props['world_x'] = props['x'] + gx * 64
                            if 'y' in props:
                                props['world_y'] = props['y'] + gy * 64
                            break
                else:
                    # Not in GMAP - local coords are world coords
                    if 'x' in props:
                        props['world_x'] = props['x']
                    if 'y' in props:
                        props['world_y'] = props['y']
                if npc_id in self.npcs:
                    self.npcs[npc_id].update(props)
                else:
                    self.npcs[npc_id] = props

        # NPC deleted
        elif packet_id == PLO_NPCDEL:
            if len(data) >= 3:
                from .packets import PacketReader
                reader = PacketReader(data)
                npc_id = reader.read_gint3()
                if npc_id in self.npcs:
                    del self.npcs[npc_id]

        # Other player properties
        elif packet_id == PacketID.PLO_OTHERPLPROPS:
            props = parse_other_player(data)
            if props and 'id' in props:
                player_id = props['id']
                if player_id in self.players:
                    # Merge props, preferring tile positions (15/16) over pixel (75/76)
                    # Only update x/y if the new value is reasonable
                    existing = self.players[player_id]
                    for key, value in props.items():
                        if key in ('x', 'y'):
                            # Prefer values in tile range (0-64) if existing is already set
                            if value is not None and (key not in existing or 0 <= value <= 64):
                                existing[key] = value
                        else:
                            existing[key] = value
                else:
                    self.players[player_id] = props

        # Player left
        elif packet_id == PacketID.PLO_PLAYERLEFT:
            player_id = parse_player_left(data)
            if player_id in self.players:
                del self.players[player_id]

        # Level sign (packet 5)
        elif packet_id == PacketID.PLO_LEVELSIGN:
            sign = parse_level_sign(data)
            if sign:
                self.signs[(sign['x'], sign['y'])] = sign['text']
                if self.on_sign:
                    self.on_sign(sign['x'], sign['y'], sign['text'])

        # Explosion effect (packet 36)
        elif packet_id == PacketID.PLO_EXPLOSION:
            exp = parse_explosion(data)
            if exp:
                self.active_explosions.append({
                    'x': exp['x'],
                    'y': exp['y'],
                    'radius': exp['radius'],
                    'power': exp['power'],
                    'time': time.time()
                })
                if self.on_explosion:
                    self.on_explosion(exp['x'], exp['y'], exp['radius'], exp['power'])

        # Hit objects feedback (packet 46)
        elif packet_id == PacketID.PLO_HITOBJECTS:
            hit = parse_hit_objects(data)
            if hit and self.on_hit_objects:
                self.on_hit_objects(hit['x'], hit['y'], hit['power'], hit['player_id'])

        # Minimap data (packet 172)
        elif packet_id == PacketID.PLO_MINIMAP:
            mm = parse_minimap(data)
            if mm and self.on_minimap:
                self.on_minimap(mm['data'])

        # Board layer (packet 107)
        elif packet_id == PacketID.PLO_BOARDLAYER:
            layer = parse_board_layer(data)
            if layer:
                self.board_layers[layer['layer']] = layer['tiles']
                if self.on_board_layer:
                    self.on_board_layer(layer['layer'], layer['x'], layer['y'], layer['tiles'])

        # Custom handler
        if packet_id in self.on_packet:
            self.on_packet[packet_id](data)

    def get_tile(self, x: int, y: int) -> int:
        """Get tile ID at position (0-63, 0-63). Returns 0 if out of bounds."""
        if not self.tiles or x < 0 or x >= 64 or y < 0 or y >= 64:
            return 0
        return self.tiles[y * 64 + x]

    def get_current_level_from_position(self) -> str:
        """
        Calculate which GMAP level the player is in based on position.
        Returns the level name, or _current_level_name if not in GMAP.
        """
        if not self.gmap_grid:
            return self._current_level_name

        # Player coords are GMAP-relative, so grid position is simply x // 64
        grid_x = int(self.player.x // 64)
        grid_y = int(self.player.y // 64)

        # Look up level name at this grid position
        return self.gmap_grid.get((grid_x, grid_y), self._current_level_name)

    def check_link_collision(self) -> Optional[dict]:
        """
        Check if player is standing on a door/warp link.
        Returns the link dict if on a door link, None otherwise.

        Edge links (at level borders for GMAP adjacency) are ignored.
        Only "interior" links like doors/caves trigger warps.
        """
        # Use the current level (set at login, stable)
        if not self._current_level_name:
            return None

        links = self.links.get(self._current_level_name, [])
        if not links:
            return None

        # Player's local position within the level
        local_x = self.player.x % 64
        local_y = self.player.y % 64

        for link in links:
            lx = link.get('x', 0)
            ly = link.get('y', 0)
            lw = link.get('width', 1)
            lh = link.get('height', 1)

            # Check if this is an edge link (GMAP adjacency, ignore)
            is_edge = (lx <= 1 or lx + lw >= 63 or ly <= 1 or ly + lh >= 63)

            # Also check if destination is an adjacent GMAP level
            dest_level = link.get('dest_level', '')
            is_adjacent = dest_level in self.get_adjacent_levels(self._current_level_name)

            # Skip edge links to adjacent levels (GMAP seamless walking)
            if is_edge and is_adjacent:
                continue

            # Check collision
            if lx <= local_x < lx + lw and ly <= local_y < ly + lh:
                return link

        return None

    def use_link(self, link: dict) -> bool:
        """
        Warp through a link (door/cave entrance).

        Args:
            link: Link dict from check_link_collision()

        Returns:
            True if warp initiated
        """
        if not link:
            return False

        dest_level = link.get('dest_level', '')
        dest_x = link.get('dest_x', '0')
        dest_y = link.get('dest_y', '0')

        # Parse destination coordinates
        try:
            new_x = float(dest_x)
            new_y = float(dest_y)
        except ValueError:
            new_x = 0.0
            new_y = 0.0

        # Request the destination level
        self.request_level(dest_level)

        # Update player position
        self.player.x = new_x
        self.player.y = new_y
        self._current_level_name = dest_level

        return True

    # =========================================================================
    # Convenience Properties
    # =========================================================================

    @property
    def x(self) -> float:
        """Player X position in tiles."""
        return self.player.x

    @property
    def y(self) -> float:
        """Player Y position in tiles."""
        return self.player.y

    @property
    def level(self) -> str:
        """Current level name."""
        return self.player.level

    # =========================================================================
    # Context Manager
    # =========================================================================

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


# =============================================================================
# Convenience Function
# =============================================================================

def connect(username: str, password: str,
            host: str = "localhost", port: int = 14900,
            version: str = "2.22") -> Optional[Client]:
    """
    Quick connect and login.

    Args:
        username: Account name
        password: Account password
        host: Server hostname
        port: Server port
        version: Protocol version

    Returns:
        Connected and authenticated Client, or None if failed

    Usage:
        client = connect("user", "pass")
        if client:
            client.move(1, 0)
            client.disconnect()
    """
    client = Client(host, port, version)

    if not client.connect():
        return None

    if not client.login(username, password):
        client.disconnect()
        return None

    return client
