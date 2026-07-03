"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import re
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
    parse_bigmap,
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
    parse_level_chest,
    parse_hurt_player,
    parse_item_add,
    parse_item_del,
    parse_private_message,
    parse_rc_add_player,
    parse_rc_del_player,
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
    build_shoot_v1,
    build_player_gattrib,
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
    parse_filesendfailed,
    parse_signature,
    parse_default_weapon,
    parse_ghost_icon,
    parse_level_modtime,
    parse_set_active_level,
    parse_flag_set,
    parse_npcweapondel,
    parse_start_message,
    parse_server_text,
    parse_staff_guilds,
    parse_status_list,
    parse_rpg_window,
    parse_baddy_hurt,
    parse_board_modify,
    parse_board_modify2,
    build_board_modify,
    parse_board_heights,
    parse_large_file_marker,
    parse_large_file_size,
    parse_file_uptodate,
    build_update_file,
    parse_bomb_add,
    build_bomb_add,
    parse_bomb_del,
    build_bomb_del,
    parse_arrow_add,
    build_arrow_add,
    parse_horse_add,
    parse_horse_del,
    build_horse_del,
    parse_firespy,
    build_firespy,
    parse_throwcarried,
    build_throwcarried,
    parse_npcmoved,
    parse_move2,
    parse_flag_del,
    parse_say2,
    parse_server_warp,
    parse_triggeraction_in,
    parse_profile,
    build_profile_get,
    build_profile_set,
    parse_npcserveraddr,
    parse_setnetcookie,
    parse_npc_bytecode,
    parse_gani_script,
    parse_npcweaponscript,
    parse_loadgani,
    parse_loadscript,
    build_update_script,
    build_update_gani,
    build_update_class,
)

# NPC delete packet ID not in PacketID class yet
PLO_NPCDEL = 29


# Set of PLO packet ids that _handle_packet has an explicit branch for.
# Kept in sync with the if/elif chain in _handle_packet and used by the
# packet-coverage harness to distinguish "handled" from "silently dropped".
def _build_handled_plo_ids() -> set:
    names = [
        "PLO_LEVELNAME", "PLO_PLAYERPROPS", "PLO_TOALL", "PLO_SHOWIMG",
        "PLO_NPCWEAPONADD", "PLO_HURTPLAYER", "PLO_ITEMADD", "PLO_ITEMDEL",
        "PLO_PRIVATEMESSAGE", "PLO_BADDYPROPS", "PLO_BOARDPACKET", "PLO_RAWDATA",
        "PLO_FILE", "PLO_FILESENDFAILED", "PLO_NEWWORLDTIME", "PLO_PLAYERWARP",
        "PLO_PLAYERWARP2", "PLO_LEVELLINK", "PLO_NPCPROPS", "PLO_OTHERPLPROPS",
        "PLO_LEVELCHEST", "PLO_DISCMESSAGE", "PLO_LEVELSIGN", "PLO_EXPLOSION",
        "PLO_HITOBJECTS", "PLO_MINIMAP", "PLO_BOARDLAYER", "PLO_GHOSTMODE",
        # Misc server packets added for full coverage.
        "PLO_LEVELBOARD", "PLO_ISLEADER", "PLO_SIGNATURE", "PLO_BADDYHURT",
        "PLO_FLAGSET", "PLO_NPCWEAPONDEL", "PLO_LEVELMODTIME", "PLO_STARTMESSAGE",
        "PLO_DEFAULTWEAPON", "PLO_STAFFGUILDS", "PLO_SERVERTEXT",
        "PLO_SETACTIVELEVEL", "PLO_UNKNOWN168", "PLO_GHOSTICON", "PLO_RPGWINDOW",
        "PLO_STATUSLIST", "PLO_UNKNOWN190", "PLO_CLEARWEAPONS", "PLO_HASNPCSERVER",
        "PLO_BIGMAP", "PLO_ADDPLAYER", "PLO_DELPLAYER",
        "PLO_SHOOT", "PLO_SHOOT2",
        # Tier 1: board modify / large files / board heights.
        "PLO_BOARDMODIFY", "PLO_BOARDMODIFY2", "PLO_BOARDHEIGHTS",
        "PLO_LARGEFILESTART", "PLO_LARGEFILESIZE", "PLO_LARGEFILEEND",
        "PLO_FILEUPTODATE",
        # Tier 2: entity families + NPC movement.
        "PLO_BOMBADD", "PLO_BOMBDEL", "PLO_ARROWADD", "PLO_HORSEADD",
        "PLO_HORSEDEL", "PLO_FIRESPY", "PLO_THROWCARRIED", "PLO_NPCMOVED",
        "PLO_MOVE2", "PLO_FLAGDEL",
        # Tier 3: server-control packets.
        "PLO_FREEZEPLAYER2", "PLO_UNFREEZEPLAYER", "PLO_SAY2", "PLO_HIDENPCS",
        "PLO_SERVERWARP", "PLO_TRIGGERACTION", "PLO_DISABLECLASSICMODE",
        "PLO_PROFILE", "PLO_NPCSERVERADDR", "PLO_SETNETCOOKIE",
        # Tier 5: GS2 bytecode transport (parse + store only).
        "PLO_NPCBYTECODE", "PLO_GANISCRIPT", "PLO_NPCWEAPONSCRIPT",
        "PLO_LOADGANI", "PLO_LOADSCRIPT",
    ]
    ids = {PLO_NPCDEL}
    for n in names:
        v = getattr(PacketID, n, None)
        if v is not None:
            ids.add(int(v))
    return ids


HANDLED_PLO_IDS = _build_handled_plo_ids()


def _eval_warp_coord(expr, player_x: float, player_y: float) -> Optional[float]:
    """Resolve a level-link destination coordinate.

    It's a plain number for most doors, but edge links use Graal expressions
    that reference the player's current coordinate so a crossing is seamless:
    "playerx", "playery", "playery-4", "playerx+0.5", etc. Returns the resolved
    float, or None if it can't be parsed.
    """
    s = str(expr).strip().lower()
    try:
        return float(s)
    except ValueError:
        pass
    s = s.replace('playerx', repr(float(player_x))).replace('playery', repr(float(player_y)))
    # Only allow arithmetic over the substituted numbers — no names/calls.
    if re.fullmatch(r'[-+*/0-9.eE() ]+', s):
        try:
            return float(eval(s, {'__builtins__': {}}, {}))
        except Exception:
            return None
    return None


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
        # PLPROP_COLORS width: v6 clients get 8 (extended body colors), classic
        # v2/v5 clients get 5. Wrong width misaligns the whole player-props
        # packet (garbled level name, spawn stuck at 0,0). See parse_player_props.
        self._colors_len = 8 if str(version).startswith("6") else 5
        # Clients older than 2.1 receive PLO_FILE without the 5-byte modtime
        # header (GServer Player.cpp sendFile: "Older client versions didn't
        # send the modTime"). Only the 1.x entries qualify.
        self._file_no_modtime = str(version).startswith("1.")

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
        self._tiles_level_name = ""    # which level self.tiles currently holds
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
        self.gmap_name = ""            # name of the loaded .gmap (e.g. chicken.gmap)
        self._requested_gmap = ""      # .gmap we've already sent a WANTFILE for
        self.bigmap_info: Dict = {}    # PLO_BIGMAP (171): image/levels_file/x/y
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
        # Per-level NPC snapshots so re-entering a level we've already visited
        # repopulates its NPCs even when the server only streams them on first
        # entry. Maps level_name -> {npc_id: props}.
        self._npc_cache: Dict[str, Dict[int, dict]] = {}

        # Other players: maps player_id -> player dict with x, y, nickname, account, etc.
        # This is the IN-LEVEL set (from PLO_OTHERPLPROPS), used for rendering.
        self.players: Dict[int, dict] = {}
        # Server-wide online roster from PLO_ADDPLAYER/PLO_DELPLAYER: the server
        # dumps everyone on login and announces joins/leaves. Maps id -> dict
        # with account/nickname/level/etc.
        self.player_list: Dict[int, dict] = {}

        # Items on ground: maps (x, y) -> item_type string
        self.items: Dict[Tuple[float, float], str] = {}

        # Baddies (enemies): maps baddy_id -> baddy dict with x, y, type, power, etc.
        self.baddies: Dict[int, dict] = {}

        # Weapons: maps weapon_name -> weapon dict with name, image, script
        self.weapons: Dict[str, dict] = {}

        # Entity families (tier 2): bombs/arrows/horses keyed by (x, y) since
        # the protocol identifies them by half-tile position, not an id.
        self.bombs: Dict[Tuple[float, float], dict] = {}
        self.arrows: List[dict] = []  # transient - arrows don't persist/despawn explicitly
        self.horses: Dict[Tuple[float, float], dict] = {}

        # NPCs: maps npc_id -> {x, y, duration_ms, dx, dy, options} most recent
        # PLO_MOVE2/NPCMOVED update (in addition to self.npcs full props).
        self.npc_moves: Dict[int, dict] = {}

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

        # Online-roster callbacks: handler(player_id, info) on join (and the
        # login dump), handler(player_id, info) on leave.
        self.on_add_player: Optional[Callable[[int, dict], None]] = None
        self.on_del_player: Optional[Callable[[int, dict], None]] = None

        # Baddy callback: handler(baddy_id, baddy_props)
        self.on_baddy: Optional[Callable[[int, dict], None]] = None

        # Weapon added callback: handler(weapon_name, weapon_data)
        self.on_weapon_add: Optional[Callable[[str, dict], None]] = None
        # A relayed projectile arrived (another player's shoot). handler(info)
        # where info = {shooter, gani, params, x, y}; params is the GS1 shoot
        # param CSV that a weapon reads via #p(n) in actionprojectile2.
        self.on_projectile: Optional[Callable[[dict], None]] = None

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

        # Ghost mode callback: handler(enabled) - ghost/spectator mode toggled
        self.on_ghost_mode: Optional[Callable[[bool], None]] = None

        # Board modify callback: handler(info) - info is the dict from
        # parse_board_modify/parse_board_modify2 (x, y, width, height, tiles,
        # layer, and map_x/map_y for gmap deltas). Fired after self.tiles /
        # self.levels[...] has already been patched.
        self.on_board_modify: Optional[Callable[[dict], None]] = None

        # File-up-to-date callback: handler(filename) - server confirmed our
        # cached copy (per request_file_if_modified) is current.
        self.on_file_uptodate: Optional[Callable[[str], None]] = None

        # Entity family callbacks (tier 2).
        self.on_bomb_add: Optional[Callable[[dict], None]] = None
        self.on_bomb_del: Optional[Callable[[float, float], None]] = None
        self.on_arrow_add: Optional[Callable[[dict], None]] = None
        self.on_horse_add: Optional[Callable[[dict], None]] = None
        self.on_horse_del: Optional[Callable[[float, float], None]] = None
        self.on_firespy: Optional[Callable[[dict], None]] = None
        self.on_throwcarried: Optional[Callable[[int], None]] = None

        # NPC-moved callback: handler(info) where info has npc_id/x/y/new_level
        # (PLO_NPCMOVED - fired when an NPC warps to a different level).
        self.on_npc_moved: Optional[Callable[[dict], None]] = None
        # NPC move-queue update callback: handler(info) with npc_id/x/y/dx/dy/
        # duration_ms/options (PLO_MOVE2).
        self.on_npc_move: Optional[Callable[[dict], None]] = None

        # Server-control callbacks (tier 3).
        # Freeze state changed: handler(frozen: bool).
        self.on_freeze: Optional[Callable[[bool], None]] = None
        # Sign-style server message: handler(text) (PLO_SAY2).
        self.on_say2: Optional[Callable[[str], None]] = None
        # Server warp target: handler(info) with name/host/port (PLO_SERVERWARP).
        # pyReborn does NOT auto-connect; the app decides.
        self.on_server_warp: Optional[Callable[[dict], None]] = None
        # Inbound triggeraction: handler(info) with player_id/npc_id/x/y/action.
        self.on_triggeraction: Optional[Callable[[dict], None]] = None
        # Profile received: handler(profile dict) (PLO_PROFILE).
        self.on_profile: Optional[Callable[[dict], None]] = None
        # NPCs hidden by server: handler() (PLO_HIDENPCS).
        self.on_hide_npcs: Optional[Callable[[], None]] = None

        # Chest callback: handler(x, y, opened) - level chest state
        self.on_chest: Optional[Callable[[int, int, bool], None]] = None

        # Disconnect callback: handler(reason) - server sent PLO_DISCMESSAGE
        self.on_disconnect: Optional[Callable[[str], None]] = None

        # Ghost mode state
        self.ghost_mode = False

        # Level chests: maps (x, y) -> opened (bool)
        self.chests: Dict[Tuple[int, int], bool] = {}
        # Item a chest holds: maps (x, y) -> item name (known only for unopened
        # chests, which the server announces with item/sign on level entry).
        self.chest_items: Dict[Tuple[int, int], str] = {}

        # Level signs: maps (x, y) -> text
        self.signs: Dict[str, Dict[Tuple[float, float], str]] = {}  # level -> {(x,y): text}

        # Active explosions for rendering: list of {x, y, radius, power, time}
        self.active_explosions: List[dict] = []

        # Board layers: maps layer_id -> tile data
        self.board_layers: Dict[int, bytes] = {}

        # File download tracking
        self._pending_files: set = set()  # Files we're waiting for
        self._received_files: Dict[str, bytes] = {}  # Received files
        self._failed_files: set = set()  # Files that failed to download
        self._uptodate_files: set = set()  # Files confirmed unchanged by the server

        # Large file transfer (PLO_LARGEFILESTART/SIZE/...FILE.../END): files
        # over 32000 bytes arrive as repeated PLO_FILE chunks (each carrying
        # its own modtime+filename header) that must be appended, not treated
        # as separate complete downloads. Keyed by filename.
        self._large_file_pending: Optional[str] = None
        self._large_file_buffer: bytearray = bytearray()
        self._large_file_expected_size: int = 0

        # Gmap level-height overrides from PLO_BOARDHEIGHTS: (map_x, map_y) ->
        # {'block_x', 'block_y', 'block_width', 'block_height', 'heights'}.
        self.board_heights: Dict[Tuple[int, int], dict] = {}

        # Server-control state (tier 3).
        self.frozen = False              # PLO_FREEZEPLAYER2 / PLO_UNFREEZEPLAYER
        self.classic_mode_disabled = False  # PLO_DISABLECLASSICMODE
        self.npcs_hidden = False         # PLO_HIDENPCS
        self.server_warp_info: Optional[dict] = None  # last PLO_SERVERWARP target
        self.profiles: Dict[str, dict] = {}  # account -> profile (PLO_PROFILE)
        self.npcserver_addr: Optional[dict] = None  # PLO_NPCSERVERADDR
        self.net_cookie = ""             # PLO_SETNETCOOKIE
        # Optional GS1 host attachment point: if the embedding app (pygame
        # layer) sets this to its ClientGS1 instance, inbound
        # PLO_TRIGGERACTION fires the matching clientside `action<name>`
        # event on loaded scripts.
        self.gs1_host = None
        # Optional GS2 host attachment point (pyreborn.gs2_client.ClientGS2
        # sets this via attach()): inbound PLO_TRIGGERACTION also fires the
        # matching `onAction<name>` function on loaded GS2 VMs.
        self.gs2_host = None

        # GS2 bytecode store (tier 5 - parse and store only, no VM).
        # kind -> {key: blob} where kind is 'weapon'/'npc'/'gani'/'class';
        # weapon/gani/class keys are names, npc keys are npc ids.
        self.gs2_bytecode: Dict[str, Dict] = {
            'weapon': {}, 'npc': {}, 'gani': {}, 'class': {},
        }
        # Script headers announced via PLO_LOADSCRIPT: name -> header info
        # dict (type/name/save_to_disk/des_key/crc).
        self.gs2_script_headers: Dict[str, dict] = {}
        # Gani SETBACKTO info from PLO_LOADGANI: gani -> setbackto ani.
        self.gani_setbackto: Dict[str, str] = {}
        # Bytecode arrival callback: handler(kind, key, blob).
        self.on_gs2_bytecode: Optional[Callable[[str, object, bytes], None]] = None

        # Auto-respond settings
        self.auto_respond_hurt = True  # Automatically send hurt response with health update
        self.hurt_animation = "hurt"   # Animation to use when hurt

        # Misc server state (populated by the corresponding PLO handlers).
        self.is_leader = False              # PLO_ISLEADER: we drive level NPCs/baddies
        self.global_flags: Dict[str, str] = {}   # PLO_FLAGSET: server-wide flags
        self.staff_guilds: List[str] = []   # PLO_STAFFGUILDS
        self.status_list: List[str] = []    # PLO_STATUSLIST (selectable statuses)
        self.server_message = ""            # PLO_STARTMESSAGE (MOTD)
        self.server_text = ""               # PLO_SERVERTEXT (last text answer)
        self.has_npc_server = False         # PLO_HASNPCSERVER (44) flag
        self.rpg_window_lines: List[str] = []   # PLO_RPGWINDOW (last window)
        self.default_weapon = 0             # PLO_DEFAULTWEAPON
        self.server_signature = 0           # PLO_SIGNATURE
        self.disconnect_reason = ""         # last PLO_DISCMESSAGE text (e.g. login reject)
        self.ghost_icon = False             # PLO_GHOSTICON
        self.active_level = ""              # PLO_SETACTIVELEVEL routing target
        self.level_modtimes: Dict[str, int] = {}  # PLO_LEVELMODTIME per level

        # Callbacks for the misc packets.
        self.on_server_text: Optional[Callable[[str], None]] = None
        self.on_rpg_window: Optional[Callable[[List[str]], None]] = None
        self.on_baddy_hurt: Optional[Callable[[int, int], None]] = None
        self.on_flag: Optional[Callable[[str, str], None]] = None

        # Packet coverage instrumentation (for the QA coverage harness).
        # Maps packet_id -> {'received': n, 'handled': n, 'errors': n, 'last_error': str}
        self.packet_stats: Dict[int, Dict[str, object]] = {}
        # Capture the most recent error traceback per packet id for debugging.
        self._packet_trace_enabled = False  # when True, keep raw bytes of each id
        # PLO ids this instance has a dispatch branch for. Subclasses (e.g.
        # RCClient) extend this so coverage counts their handlers too.
        self._handled_plo_ids = set(HANDLED_PLO_IDS)

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

    @property
    def in_gmap_segment(self) -> bool:
        """True when the current level is an actual GMAP grid segment.

        Distinct from is_gmap: once a .gmap is loaded is_gmap stays True even
        after a door drops the player into a standalone interior level (house,
        cave) that is NOT part of the grid. Such levels use plain local (0-63)
        coordinates and must be edge-clamped like any non-GMAP level, whereas
        real segments stitch together with their neighbours and span past 64.
        """
        return (self.gmap_width > 0 and
                self._current_level_name in self.gmap_grid.values())

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
        self.disconnect_reason = ""

        # Wait for authentication response
        start = time.time()
        while time.time() - start < timeout:
            self.update(timeout=0.1)
            if self._authenticated:
                return True
            # Server rejected us (e.g. wrong version/password) — it sends a
            # PLO_DISCMESSAGE and drops the link. Stop waiting out the full
            # timeout; disconnect_reason holds why for the caller to surface.
            if not self.connected:
                return False

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

        # Server froze us (PLO_FREEZEPLAYER2): movement is a no-op until
        # PLO_UNFREEZEPLAYER, matching real client behavior.
        if self.frozen:
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

    def send_position(self) -> bool:
        """Re-broadcast the player's current position without moving.

        The server only tells other players our position when it changes, so a
        stationary player is invisible (position-wise) to anyone who joins after
        us. Calling this pushes our current X/Y so others can place us. Useful
        for tests and for an initial position announce after entering a level.
        """
        if not self.connected or not self._authenticated:
            return False
        local_x = self.player.x % 64
        local_y = self.player.y % 64
        data = build_movement(local_x, local_y, self.player.direction)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

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

        # Optimistic local echo: your own bubble/message shows immediately.
        # The server never relays your toall back to you (pid == m_id is skipped).
        self.player.chat = message
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

        # Optimistic local echo so our own bubble renders right away; the server
        # does not echo CURCHAT back to the setter.
        self.player.chat = message
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
              gani: str = "arrow", gravity: int = 0, params: str = "") -> bool:
        """
        Shoot a projectile (arrow, fireball, etc.).

        Args:
            direction: 0=up, 1=left, 2=down, 3=right (default: player direction)
            speed: Projectile speed (1-127, default 3)
            gani: Projectile animation name (default "arrow")
            gravity: Gravity effect (0 for flat shot, 8 for arc)
            params: Projectile param string (GS1 shoot params; the receiver reads
                them via #p(n) in an actionprojectile2 handler)

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

        # Classic servers (v2.x) only handle the old PLI_SHOOT (40); they ignore
        # PLI_SHOOT2 (48), so projectiles — and Bomber Arena's room system — never
        # relay. v6 clients use PLI_SHOOT2.
        if str(self.version).startswith("2."):
            data = build_shoot_v1(self.player.x, self.player.y, 0,
                                  angle, speed, gani, params)
            return self._protocol.send_packet(PacketID.PLI_SHOOT, data)
        data = build_shoot(
            self.player.x, self.player.y, 0,
            angle, speed, gani, params, gravity
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

    def set_gattrib(self, index: int, value: str) -> bool:
        """Set gani attribute `index` (1..30, i.e. GS1 #P<index>) and send it to
        the server, which relays it to other players (PLO_OTHERPLPROPS). Used by
        Bomber Arena's room slot lists so players see each other in the queue."""
        if not self.connected or not self._authenticated:
            return False
        # cache our own value so we read it back consistently
        self.player.gattribs = getattr(self.player, 'gattribs', {})
        self.player.gattribs[index] = value
        data = build_player_gattrib(index, value)
        if not data:
            return False
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

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
        if level_name != self._current_level_name:
            self._reset_level_state()
        # On a gmap, store WORLD coords (grid*64 + local) for the target segment
        # so position stays consistent with the world-coordinate model. A fresh
        # gmap entry (grid not loaded yet) relies on the server's PLAYERPROPS to
        # supply world coords; a re-warp between already-loaded segments does not
        # get those, so convert here. Non-segment targets keep their local coords.
        self.player.x = x
        self.player.y = y
        if self.gmap_width > 0:
            for (gx, gy), seg in self.gmap_grid.items():
                if seg == level_name:
                    self.player.x = gx * 64 + x
                    self.player.y = gy * 64 + y
                    break
        # Leaving a standalone (non-GMAP) level: drop the other players from it.
        # The server streams the new level's players fresh; without this, players
        # from old levels linger and inflate playerscount (e.g. the Bomber arena
        # host then thinks the room is full and never settles to host it). GMAP
        # segment hops keep the roster (you see players across the whole gmap).
        if (level_name != self._current_level_name
                and level_name not in self.gmap_grid):
            self.players.clear()

        self._current_level_name = level_name
        self._pending_level_name = level_name

        # If we've visited this level before, repopulate its board from cache
        # immediately so the renderer doesn't draw the OLD level's tiles under
        # the player while the server re-streams the board (the "warped before
        # the new tiles render" glitch). First-visit levels stay flagged stale
        # (tiles_level_name != current) so the client can show a loading state.
        if level_name in self.levels:
            self.tiles = self.levels[level_name]
            self._tiles_level_name = level_name

        # Restore any NPCs we cached for this level on a previous visit. If the
        # server re-streams them, the fresh PLO_NPCPROPS just overwrites these.
        cached_npcs = self._npc_cache.get(level_name)
        if cached_npcs:
            self.npcs.update(cached_npcs)

        # The LEVELWARP packet carries LOCAL coords within the target segment.
        data = build_level_warp(x, y, level_name)
        return self._protocol.send_packet(PacketID.PLI_LEVELWARP, data)

    def _reset_level_state(self):
        """Clear per-level state on a full level change so chests, chest items,
        signs, ground items, baddies and NPCs from the old level don't leak into
        the new one. (Links/signs are keyed by level name; the rest are flat.)

        Not called on seamless GMAP segment crossing (that goes through move(),
        not warp_to_level), so the stitched world keeps its entities."""
        self.chests.clear()
        self.chest_items.clear()
        self.signs.clear()
        self.items.clear()
        self.baddies.clear()
        # Snapshot NPCs per level before clearing so we can restore them if we
        # come back and the server doesn't re-stream them (see _npc_cache).
        for nid, npc in self.npcs.items():
            lvl = npc.get('_level')
            if lvl:
                self._npc_cache.setdefault(lvl, {})[nid] = npc
        self.npcs.clear()

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

    def put_bomb(self, x: Optional[float] = None, y: Optional[float] = None,
                power: int = 1, timer_ms: int = 3050) -> bool:
        """Place a bomb (PLI_BOMBADD). timer_ms is total fuse time; the server
        expects 50ms increments already counted down by ~200ms client-side, so
        this converts it the same way (see build_bomb_add)."""
        if not self.connected or not self._authenticated:
            return False
        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        data = build_bomb_add(x, y, power, timer_ms)
        return self._protocol.send_packet(PacketID.PLI_BOMBADD, data)

    def remove_bomb(self, x: float, y: float) -> bool:
        """Remove a bomb at (x, y) (PLI_BOMBDEL)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_bomb_del(x, y)
        return self._protocol.send_packet(PacketID.PLI_BOMBDEL, data)

    def shoot_arrow(self, x: Optional[float] = None, y: Optional[float] = None,
                    direction: Optional[int] = None, sprite: int = 0,
                    power: int = 1) -> bool:
        """Fire an arrow (PLI_ARROWADD)."""
        if not self.connected or not self._authenticated:
            return False
        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        if direction is None:
            direction = self.player.direction
        data = build_arrow_add(x, y, direction, sprite, power, from_player=True)
        return self._protocol.send_packet(PacketID.PLI_ARROWADD, data)

    def remove_horse(self, x: float, y: float) -> bool:
        """Remove/dismount a horse at (x, y) (PLI_HORSEDEL)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_horse_del(x, y)
        return self._protocol.send_packet(PacketID.PLI_HORSEDEL, data)

    def firespy(self, power: int = 1, length: int = 1) -> bool:
        """Trigger the fire-spy weapon effect (PLI_FIRESPY)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_firespy(power, length)
        return self._protocol.send_packet(PacketID.PLI_FIRESPY, data)

    def throw_carried(self) -> bool:
        """Throw whatever object/NPC the player is currently carrying (PLI_THROWCARRIED)."""
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(PacketID.PLI_THROWCARRIED, build_throwcarried())

    def modify_board(self, x: int, y: int, width: int, height: int, tiles) -> bool:
        """
        Edit a rectangle of the current level's board (PLI_BOARDMODIFY).

        Args:
            x, y: top-left tile coordinate of the edit (0-63)
            width, height: size of the edit rectangle
            tiles: flat list of width*height raw tile ids, row-major

        Returns:
            True if the packet was sent. The server does NOT echo the change
            back to the sender (sendPacketToOneLevelPart/sendPacketToNearby
            exclude the originating player id - see
            PlayerClientPackets.cpp msgPLI_BOARDMODIFY), only to other
            players on the level, so this applies the edit to our own cached
            board immediately (matching real client behavior of editing
            optimistically rather than waiting for a self-echo that never
            arrives).
        """
        if not self.connected or not self._authenticated:
            return False
        if len(tiles) < width * height:
            return False

        level_name = self._pending_level_name or self._current_level_name
        if level_name:
            self._apply_board_modify(level_name, {
                'layer': 0, 'x': x, 'y': y, 'width': width, 'height': height,
                'tiles': list(tiles[:width * height]),
            })

        data = build_board_modify(x, y, width, height, tiles)
        return self._protocol.send_packet(PacketID.PLI_BOARDMODIFY, data)

    def request_file_if_modified(self, filename: str, mod_time: int = 0) -> bool:
        """
        Ask the server whether filename has changed since mod_time
        (PLI_UPDATEFILE). Replies with PLO_FILE (new/changed - handled the
        same as request_file) or PLO_FILEUPTODATE (unchanged, see
        on_file_uptodate / is_file_uptodate).

        Args:
            filename: name of the file to check
            mod_time: last known modification time (unix epoch seconds);
                      0 always forces a fresh download.

        Returns:
            True if the packet was sent.
        """
        if not self.connected or not self._authenticated:
            return False

        self._pending_files.add(filename)
        data = build_update_file(filename, mod_time)
        return self._protocol.send_packet(PacketID.PLI_UPDATEFILE, data)

    def is_file_uptodate(self, filename: str) -> bool:
        """Check if the server confirmed filename is unchanged (PLO_FILEUPTODATE)."""
        return filename in self._uptodate_files

    def request_weapon_bytecode(self, weapon_name: str) -> bool:
        """Request a weapon's GS2 bytecode (PLI_UPDATESCRIPT). Reply arrives
        as PLO_NPCWEAPONSCRIPT -> client.gs2_bytecode['weapon'][name]."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_script(weapon_name)
        return self._protocol.send_packet(PacketID.PLI_UPDATESCRIPT, data)

    def request_gani_bytecode(self, gani_name: str, checksum: int = 0) -> bool:
        """Request a gani's GS2 bytecode (PLI_UPDATEGANI; name without .gani).
        Replies: PLO_GANISCRIPT (if checksum differs) + PLO_LOADGANI."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_gani(gani_name, checksum)
        return self._protocol.send_packet(PacketID.PLI_UPDATEGANI, data)

    def request_class_bytecode(self, class_name: str, checksum: int = 0) -> bool:
        """Request a script class's GS2 bytecode (PLI_UPDATECLASS). Reply
        arrives as PLO_LOADSCRIPT -> client.gs2_bytecode['class'][name]."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_class(class_name, checksum)
        return self._protocol.send_packet(PacketID.PLI_UPDATECLASS, data)

    def request_profile(self, account: str) -> bool:
        """
        Request another player's profile (PLI_PROFILEGET). The reply arrives
        as PLO_PROFILE (see on_profile / client.profiles) - requires the
        server to be connected to a listserver that knows the account.
        """
        if not self.connected or not self._authenticated:
            return False
        data = build_profile_get(account)
        return self._protocol.send_packet(PacketID.PLI_PROFILEGET, data)

    def set_profile(self, name: str = '', age: str = '', gender: str = '',
                    country: str = '', messenger: str = '', email: str = '',
                    website: str = '', hangout: str = '', quote: str = '') -> bool:
        """
        Update our own profile (PLI_PROFILESET). The server forwards it to the
        listserver; it silently drops the packet if the embedded account name
        doesn't match ours (which this method guarantees).
        """
        if not self.connected or not self._authenticated:
            return False
        data = build_profile_set(self.player.account or '', name, age, gender,
                                 country, messenger, email, website, hangout,
                                 quote)
        return self._protocol.send_packet(PacketID.PLI_PROFILESET, data)

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

    def _exit_gmap(self, level_name: str):
        """Leave gmap mode and become a standalone level.

        Called when the player warps from a gmap world into a level that isn't
        one of its segments (e.g. an interior). Clears the grid so is_gmap is
        False and positions are treated as plain local coordinates again.
        """
        self.gmap_grid.clear()
        self.gmap_width = 0
        self.gmap_height = 0
        self.gmap_name = ""
        self._requested_gmap = ""
        self._gmap_base_level = ""
        self._gmap_spawn_x = 0
        self._gmap_spawn_y = 0
        self.player.level = level_name
        self._current_level_name = level_name
        self._pending_level_name = level_name

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
            stats = self.packet_stats.get(packet_id)
            if stats is None:
                stats = {'received': 0, 'handled': 0, 'errors': 0, 'last_error': ''}
                self.packet_stats[packet_id] = stats
            stats['received'] += 1
            try:
                self._handle_packet(packet_id, data)
                if packet_id in self._handled_plo_ids:
                    stats['handled'] += 1
            except Exception as e:
                stats['errors'] += 1
                stats['last_error'] = f"{type(e).__name__}: {e}"

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
            # Entering a gmap: download the .gmap file so we can build the grid.
            # The server announces the gmap by name but doesn't push the file;
            # the client must request it (once) via PLI_WANTFILE.
            if level_name.endswith('.gmap') and level_name != self._requested_gmap:
                self._requested_gmap = level_name
                self.request_file(level_name)
            # Leaving a gmap: a .nw level that isn't one of the gmap's segments
            # (e.g. warping into a cave/house) means we've left gmap mode. Clear
            # the grid so is_gmap/coordinates reflect the standalone level.
            elif (level_name.endswith('.nw') and self.gmap_width > 0 and
                  level_name not in self.gmap_grid.values()):
                self._exit_gmap(level_name)

        # Player properties (our player data)
        elif packet_id == PacketID.PLO_PLAYERPROPS:
            props = parse_player_props(data, self._colors_len)

            # The server tracks position as LOCAL coords (0-63) within the
            # player's current segment, not world coords. Convert to the client's
            # world-coordinate model so the camera stays aligned with the tiles.
            #
            # Only a level that is an actual GMAP segment gets the grid offset;
            # standalone interior levels reached via a door (houses, caves) are
            # not in the grid even though a gmap is loaded, so they stay local.
            if 'x' in props or 'y' in props:
                grid = None
                if self.gmap_width > 0:
                    grid = next((cell for cell, name in self.gmap_grid.items()
                                 if name == self._current_level_name), None)
                if grid:
                    # Rebuild world coords: world = local + grid*64. Using (x % 64)
                    # makes this correct whether the server sent local or world.
                    if 'x' in props:
                        props['x'] = props['x'] % 64 + grid[0] * 64
                    if 'y' in props:
                        props['y'] = props['y'] % 64 + grid[1] * 64
                else:
                    if 'x' in props:
                        props['x'] = props['x'] % 64
                    if 'y' in props:
                        props['y'] = props['y'] % 64

            self.player.update_from_props(props)

            # First props packet means we're authenticated
            if not self._authenticated:
                self._authenticated = True

        # Chat message OR movement update
        elif packet_id == PacketID.PLO_TOALL:
            # PLO_TOALL is a server-wide broadcast message only. Player movement
            # arrives via PLO_OTHERPLPROPS (8), never here.
            player_id, message = parse_chat(data)
            if message and self.on_chat:
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

        # PLO_SHOOT (175) / PLO_SHOOT2 (191) - a projectile was relayed to us.
        # Same id across versions; classic uses SHOOT (v1 wire), 6.037 SHOOT2.
        elif packet_id in (PacketID.PLO_SHOOT, PacketID.PLO_SHOOT2):
            from .packets import parse_shoot
            info = parse_shoot(data, v2=(packet_id == PacketID.PLO_SHOOT2))
            if info and self.on_projectile:
                self.on_projectile(info)

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

        # PLO_ADDPLAYER (55) - online roster entry (login dump + joins)
        elif packet_id == PacketID.PLO_ADDPLAYER:
            info = parse_rc_add_player(data)
            if info and 'id' in info:
                pid = info['id']
                is_new = pid not in self.player_list
                self.player_list.setdefault(pid, {}).update(info)
                if is_new and self.on_add_player:
                    self.on_add_player(pid, self.player_list[pid])

        # PLO_DELPLAYER (56) - player left the server
        elif packet_id == PacketID.PLO_DELPLAYER:
            pid = parse_rc_del_player(data)
            info = self.player_list.pop(pid, None)
            if info is not None and self.on_del_player:
                self.on_del_player(pid, info)

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
            self._tiles_level_name = level_for_tiles
            if self.on_level:
                self.on_level(tiles)

        # Raw data announcement
        elif packet_id == PacketID.PLO_RAWDATA:
            self._raw_data_expected = parse_rawdata(data)

        # File transfer
        elif packet_id == PacketID.PLO_FILE:
            file_info = parse_file(data, no_modtime=self._file_no_modtime)
            if file_info and file_info['filename']:
                filename = file_info['filename']
                file_data = file_info['data']

                # Files over 32000 bytes arrive as repeated PLO_FILE chunks
                # bracketed by PLO_LARGEFILESTART/...END (each chunk resends
                # the full modtime+filename header - see
                # server/src/player/Player.cpp Player::sendFile). Append
                # rather than overwrite while a large transfer is in flight.
                if self._large_file_pending == filename:
                    self._large_file_buffer.extend(file_data)
                else:
                    self._received_files[filename] = file_data
                    self._pending_files.discard(filename)
                    # A downloaded .gmap file is the world grid - parse it.
                    if filename.endswith('.gmap'):
                        try:
                            self.load_gmap(file_data.decode('latin-1', errors='replace'))
                            self.gmap_name = filename
                            # Now that the grid is known, pull in the neighbouring
                            # segments so the world renders stitched instead of a
                            # lone current segment.
                            self.request_adjacent_levels()
                        except Exception:
                            pass
                    if self.on_file:
                        self.on_file(filename, file_data)

        # File send failed
        elif packet_id == PacketID.PLO_FILESENDFAILED:
            filename = parse_filesendfailed(data)
            if filename:
                self._failed_files.add(filename)
                self._pending_files.discard(filename)

        # Large file transfer starts (packet 68) - subsequent PLO_FILE chunks
        # for this filename must be appended, not treated as complete files.
        elif packet_id == PacketID.PLO_LARGEFILESTART:
            filename = parse_large_file_marker(data)
            self._large_file_pending = filename
            self._large_file_buffer = bytearray()
            self._large_file_expected_size = 0

        # Large file total size (packet 84) - informational, arrives right
        # after LARGEFILESTART.
        elif packet_id == PacketID.PLO_LARGEFILESIZE:
            self._large_file_expected_size = parse_large_file_size(data)

        # Large file transfer ends (packet 69) - flush the accumulated
        # buffer through the same path a normal PLO_FILE download takes.
        elif packet_id == PacketID.PLO_LARGEFILEEND:
            filename = parse_large_file_marker(data)
            if self._large_file_pending == filename:
                file_data = bytes(self._large_file_buffer)
                self._large_file_pending = None
                self._large_file_buffer = bytearray()
                self._received_files[filename] = file_data
                self._pending_files.discard(filename)
                if filename.endswith('.gmap'):
                    try:
                        self.load_gmap(file_data.decode('latin-1', errors='replace'))
                        self.gmap_name = filename
                        self.request_adjacent_levels()
                    except Exception:
                        pass
                if self.on_file:
                    self.on_file(filename, file_data)

        # Server confirms our cached copy is current (packet 45) - resolves a
        # request_file_if_modified() call with no data transfer.
        elif packet_id == PacketID.PLO_FILEUPTODATE:
            filename = parse_file_uptodate(data)
            if filename:
                self._uptodate_files.add(filename)
                self._pending_files.discard(filename)
                if self.on_file_uptodate:
                    self.on_file_uptodate(filename)

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
            props = parse_other_player(data, self._colors_len)
            if props and 'id' in props:
                player_id = props['id']
                # A non-empty CURCHAT prop is another player's chat bubble — the
                # primary in-level chat path. Surface it through on_chat.
                chat = props.get('chat')
                if chat and self.on_chat:
                    self.on_chat(player_id, chat)
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

        # Level chest (packet 4)
        elif packet_id == PacketID.PLO_LEVELCHEST:
            chest = parse_level_chest(data)
            if chest:
                key = (chest['x'], chest['y'])
                self.chests[key] = chest['opened']
                # Remember the item an unopened chest holds (only sent on warp).
                if 'item' in chest:
                    self.chest_items[key] = chest['item']
                if self.on_chest:
                    self.on_chest(chest['x'], chest['y'], chest['opened'])

        # Disconnect message (packet 16) - server kicked us / is shutting down
        elif packet_id == PacketID.PLO_DISCMESSAGE:
            reason = data.decode('latin-1', errors='replace').strip()
            self.disconnect_reason = reason
            if self.on_disconnect:
                self.on_disconnect(reason)
            self.disconnect()

        # Level sign (packet 5)
        elif packet_id == PacketID.PLO_LEVELSIGN:
            sign = parse_level_sign(data)
            if sign:
                # Key signs by the level they belong to (the level whose board is
                # currently being received) so a sign never shows in another level
                # — local sign coords collide across segments otherwise.
                lvl = self._pending_level_name or self._current_level_name
                self.signs.setdefault(lvl, {})[(sign['x'], sign['y'])] = sign['text']
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

        # Bigmap/minimap config (packet 171) - sent on gmap entry.
        elif packet_id == PacketID.PLO_BIGMAP:
            self.bigmap_info = parse_bigmap(data)

        # Board layer (packet 107)
        elif packet_id == PacketID.PLO_BOARDLAYER:
            layer = parse_board_layer(data)
            if layer:
                self.board_layers[layer['layer']] = layer['tiles']
                if self.on_board_layer:
                    self.on_board_layer(layer['layer'], layer['x'], layer['y'], layer['tiles'])

        # Ghost mode (packet 170)
        elif packet_id == PacketID.PLO_GHOSTMODE:
            # Ghost mode packet - typically just a toggle flag
            enabled = data[0] != 0 if data else True
            self.ghost_mode = enabled
            if self.on_ghost_mode:
                self.on_ghost_mode(enabled)

        # Single-level tile delta (packet 7) - non-gmap board edit.
        elif packet_id == PacketID.PLO_BOARDMODIFY:
            info = parse_board_modify(data)
            level_name = self._pending_level_name or self._current_level_name
            if level_name:
                self._apply_board_modify(level_name, info)
            if self.on_board_modify:
                self.on_board_modify(info)

        # Gmap tile delta (packet 186) - carries the target segment's map
        # position so it can be applied even to a level we're not standing on
        # (adjacent-level board edits within a gmap).
        elif packet_id == PacketID.PLO_BOARDMODIFY2:
            info = parse_board_modify2(data)
            level_name = self.gmap_grid.get((info['map_x'], info['map_y']))
            if not level_name:
                level_name = self._pending_level_name or self._current_level_name
            if level_name:
                self._apply_board_modify(level_name, info)
            if self.on_board_modify:
                self.on_board_modify(info)

        # Gmap level-height overrides (packet 185) - no rendering, just cache.
        elif packet_id == PacketID.PLO_BOARDHEIGHTS:
            heights = parse_board_heights(data)
            self.board_heights[(heights['map_x'], heights['map_y'])] = heights

        # ---- Misc server packets (full-coverage handlers) -----------------

        # Board-sent marker (packet 0) - board data normally arrives via
        # PLO_BOARDPACKET/PLO_RAWDATA, so this is usually just an
        # acknowledgement (server sends it with an empty payload - see
        # PlayerClient.cpp/PlayerClientOriginal.cpp). Defensively handle the
        # "batched board changes" payload form too (Level.cpp
        # sendBoardChangesToPlayer style==2: concatenated
        # getPropsForSingleLevel() records, same body as PLO_BOARDMODIFY,
        # back to back) - currently dead code server-side (TODO, never
        # triggered) but cheap to support if it ever is.
        elif packet_id == PacketID.PLO_LEVELBOARD:
            if data:
                from .packets import PacketReader as _PacketReader
                level_name = self._pending_level_name or self._current_level_name
                reader = _PacketReader(data)
                while reader.pos < len(data):
                    start = reader.pos
                    layer = 0
                    first = reader.read_gchar()
                    if first >= 64:
                        layer = first - 64
                        x = reader.read_gchar()
                    else:
                        x = first
                    y = reader.read_gchar()
                    w = reader.read_gchar()
                    h = reader.read_gchar()
                    if w <= 0 or h <= 0 or w > 64 or h > 64 or reader.pos <= start:
                        break  # not a valid record - bail rather than misparse
                    tiles = [reader.read_gshort() for _ in range(w * h)]
                    info = {'layer': layer, 'x': x, 'y': y, 'width': w,
                            'height': h, 'tiles': tiles}
                    if level_name:
                        self._apply_board_modify(level_name, info)
                    if self.on_board_modify:
                        self.on_board_modify(info)

        # We are this level's leader (packet 10) - drive baddies/NPCs.
        elif packet_id == PacketID.PLO_ISLEADER:
            self.is_leader = True

        # Server signature/version (packet 25).
        elif packet_id == PacketID.PLO_SIGNATURE:
            self.server_signature = parse_signature(data)

        # A baddy was hurt (packet 27) - relayed to the level leader.
        elif packet_id == PacketID.PLO_BADDYHURT:
            bh = parse_baddy_hurt(data)
            bid = bh['baddy_id']
            if bid in self.baddies:
                self.baddies[bid]['power'] = max(
                    0, self.baddies[bid].get('power', 0) - bh['power'])
            if self.on_baddy_hurt:
                self.on_baddy_hurt(bid, bh['power'])

        # Server flag set/clear (packet 28).
        elif packet_id == PacketID.PLO_FLAGSET:
            name, value = parse_flag_set(data)
            self.global_flags[name] = value
            if self.on_flag:
                self.on_flag(name, value)

        # Server-wide flag removed (packet 31).
        elif packet_id == PacketID.PLO_FLAGDEL:
            name = parse_flag_del(data)
            self.global_flags.pop(name, None)

        # Bomb placed by another player (packet 11).
        elif packet_id == PacketID.PLO_BOMBADD:
            info = parse_bomb_add(data)
            self.bombs[(info['x'], info['y'])] = info
            if self.on_bomb_add:
                self.on_bomb_add(info)

        # Bomb removed/exploded (packet 12).
        elif packet_id == PacketID.PLO_BOMBDEL:
            info = parse_bomb_del(data)
            self.bombs.pop((info['x'], info['y']), None)
            if self.on_bomb_del:
                self.on_bomb_del(info['x'], info['y'])

        # Arrow fired by another player (packet 19). Transient - no removal
        # packet exists, so just keep a bounded recent-arrows list.
        elif packet_id == PacketID.PLO_ARROWADD:
            info = parse_arrow_add(data)
            self.arrows.append(info)
            if len(self.arrows) > 64:
                self.arrows = self.arrows[-64:]
            if self.on_arrow_add:
                self.on_arrow_add(info)

        # Horse placed/mounted by another player (packet 17).
        elif packet_id == PacketID.PLO_HORSEADD:
            info = parse_horse_add(data)
            self.horses[(info['x'], info['y'])] = info
            if self.on_horse_add:
                self.on_horse_add(info)

        # Horse removed (packet 18).
        elif packet_id == PacketID.PLO_HORSEDEL:
            info = parse_horse_del(data)
            self.horses.pop((info['x'], info['y']), None)
            if self.on_horse_del:
                self.on_horse_del(info['x'], info['y'])

        # Fire spy weapon effect from another player (packet 20).
        elif packet_id == PacketID.PLO_FIRESPY:
            info = parse_firespy(data)
            if self.on_firespy:
                self.on_firespy(info)

        # Another player threw their carried object/npc (packet 21).
        elif packet_id == PacketID.PLO_THROWCARRIED:
            info = parse_throwcarried(data)
            if self.on_throwcarried:
                self.on_throwcarried(info['owner_id'])

        # NPC warped to a different level (packet 24).
        elif packet_id == PacketID.PLO_NPCMOVED:
            info = parse_npcmoved(data)
            if self.on_npc_moved:
                self.on_npc_moved(info)

        # NPC move-queue update, modern clients (packet 189).
        elif packet_id == PacketID.PLO_MOVE2:
            info = parse_move2(data)
            npc = self.npcs.get(info['npc_id'])
            if npc is not None:
                npc['x'] = info['x']
                npc['y'] = info['y']
            self.npc_moves[info['npc_id']] = info
            if self.on_npc_move:
                self.on_npc_move(info)

        # ---- Server-control packets (tier 3) -------------------------------

        # Freeze / unfreeze player (packets 154/155) - empty payloads.
        elif packet_id == PacketID.PLO_FREEZEPLAYER2:
            self.frozen = True
            if self.on_freeze:
                self.on_freeze(True)

        elif packet_id == PacketID.PLO_UNFREEZEPLAYER:
            self.frozen = False
            if self.on_freeze:
                self.on_freeze(False)

        # Sign-style text window pushed by the server (packet 153).
        elif packet_id == PacketID.PLO_SAY2:
            text = parse_say2(data)
            if self.on_say2:
                self.on_say2(text)

        # Hide all NPCs (packet 151) - empty payload.
        elif packet_id == PacketID.PLO_HIDENPCS:
            self.npcs_hidden = True
            if self.on_hide_npcs:
                self.on_hide_npcs()

        # Server warp target (packet 178) - do NOT auto-connect; just record
        # the destination and notify the app.
        elif packet_id == PacketID.PLO_SERVERWARP:
            self.server_warp_info = parse_server_warp(data)
            if self.on_server_warp:
                self.on_server_warp(self.server_warp_info)

        # Inbound triggeraction (packet 48) - from serverside scripts
        # (triggerClient) or relayed from other players.
        elif packet_id == PacketID.PLO_TRIGGERACTION:
            info = parse_triggeraction_in(data)
            if self.on_triggeraction:
                self.on_triggeraction(info)
            # Route into the GS1 host (if attached) so clientside scripts with
            # a matching `if (action<name>)` handler run, mirroring the real
            # client. Action name = first CSV token.
            if self.gs1_host is not None and info['action']:
                try:
                    action_name = info['action'].split(',', 1)[0].strip()
                    if action_name:
                        self.gs1_host.trigger_event('action' + action_name)
                except Exception:
                    pass
            # GS2 counterpart: fire onAction<name>(params...) on loaded VMs.
            if self.gs2_host is not None and info['action']:
                try:
                    self.gs2_host.handle_triggeraction(info['action'])
                except Exception:
                    pass

        # Disable classic mode (packet 176) - fully-scripted server marker.
        elif packet_id == PacketID.PLO_DISABLECLASSICMODE:
            self.classic_mode_disabled = True

        # Another player's profile (packet 75).
        elif packet_id == PacketID.PLO_PROFILE:
            profile = parse_profile(data)
            if profile.get('account'):
                self.profiles[profile['account']] = profile
            if self.on_profile:
                self.on_profile(profile)

        # NPC-server address (packet 79).
        elif packet_id == PacketID.PLO_NPCSERVERADDR:
            self.npcserver_addr = parse_npcserveraddr(data)

        # Net cookie (packet 111).
        elif packet_id == PacketID.PLO_SETNETCOOKIE:
            self.net_cookie = parse_setnetcookie(data)

        # ---- GS2 bytecode transport (tier 5: parse and store only) ---------

        # Compiled NPC script (packet 131, arrives via RAWDATA).
        elif packet_id == PacketID.PLO_NPCBYTECODE:
            info = parse_npc_bytecode(data)
            self.gs2_bytecode['npc'][info['npc_id']] = info['bytecode']
            if self.on_gs2_bytecode:
                self.on_gs2_bytecode('npc', info['npc_id'], info['bytecode'])

        # Compiled gani script (packet 134, arrives via RAWDATA).
        elif packet_id == PacketID.PLO_GANISCRIPT:
            info = parse_gani_script(data)
            self.gs2_bytecode['gani'][info['gani']] = info['bytecode']
            if self.on_gs2_bytecode:
                self.on_gs2_bytecode('gani', info['gani'], info['bytecode'])

        # Weapon (or unknown-class stub) bytecode (packet 140).
        elif packet_id == PacketID.PLO_NPCWEAPONSCRIPT:
            info = parse_npcweaponscript(data)
            kind = info['type'] if info['type'] in self.gs2_bytecode else 'weapon'
            if info['name']:
                self.gs2_bytecode[kind][info['name']] = info['bytecode']
                self.gs2_script_headers[info['name']] = info
            if self.on_gs2_bytecode:
                self.on_gs2_bytecode(kind, info['name'], info['bytecode'])

        # Load-gani instruction (packet 195).
        elif packet_id == PacketID.PLO_LOADGANI:
            info = parse_loadgani(data)
            if info['gani']:
                self.gani_setbackto[info['gani']] = info['setbackto']

        # Script header announcement / class bytecode (packet 197).
        elif packet_id == PacketID.PLO_LOADSCRIPT:
            info = parse_loadscript(data)
            if info['name']:
                self.gs2_script_headers[info['name']] = info
                if info['bytecode']:
                    kind = info['type'] if info['type'] in self.gs2_bytecode else 'class'
                    self.gs2_bytecode[kind][info['name']] = info['bytecode']
                    if self.on_gs2_bytecode:
                        self.on_gs2_bytecode(kind, info['name'], info['bytecode'])

        # Remove a weapon from inventory (packet 34).
        elif packet_id == PacketID.PLO_NPCWEAPONDEL:
            name = parse_npcweapondel(data)
            self.weapons.pop(name, None)

        # Active level's mod time (packet 39).
        elif packet_id == PacketID.PLO_LEVELMODTIME:
            level = self.active_level or self._pending_level_name
            self.level_modtimes[level] = parse_level_modtime(data)

        # Server MOTD (packet 41).
        elif packet_id == PacketID.PLO_STARTMESSAGE:
            self.server_message = parse_start_message(data)

        # Default weapon id (packet 43).
        elif packet_id == PacketID.PLO_DEFAULTWEAPON:
            self.default_weapon = parse_default_weapon(data)

        # Staff guild list (packet 47).
        elif packet_id == PacketID.PLO_STAFFGUILDS:
            self.staff_guilds = parse_staff_guilds(data)

        # Server text answer (packet 82).
        elif packet_id == PacketID.PLO_SERVERTEXT:
            self.server_text = parse_server_text(data)
            if self.on_server_text:
                self.on_server_text(self.server_text)

        # Active level for subsequent chest/baddy/npc/board packets (packet 156).
        elif packet_id == PacketID.PLO_SETACTIVELEVEL:
            self.active_level = parse_set_active_level(data)
            # Route level-scoped data (board/chest/sign) to this level too.
            self._pending_level_name = self.active_level

        # Login-server marker, blank (packet 168) - no-op.
        elif packet_id == PacketID.PLO_UNKNOWN168:
            pass

        # Ghost icon toggle (packet 174).
        elif packet_id == PacketID.PLO_GHOSTICON:
            self.ghost_icon = parse_ghost_icon(data)

        # RPG-style text window (packet 179).
        elif packet_id == PacketID.PLO_RPGWINDOW:
            self.rpg_window_lines = parse_rpg_window(data)
            if self.on_rpg_window:
                self.on_rpg_window(self.rpg_window_lines)

        # Selectable player-status labels (packet 180).
        elif packet_id == PacketID.PLO_STATUSLIST:
            self.status_list = parse_status_list(data)

        # Blank marker before weapon list (packet 190) - no-op.
        elif packet_id == PacketID.PLO_UNKNOWN190:
            pass

        # Clear all weapons before the server resends the list (packet 194).
        elif packet_id == PacketID.PLO_CLEARWEAPONS:
            self.weapons.clear()

        # PLO_HASNPCSERVER (44): empty flag - the server has an npc-server, so
        # the client should not update npc props itself. Just record it.
        elif packet_id == PacketID.PLO_HASNPCSERVER:
            self.has_npc_server = True

        # Custom handler
        if packet_id in self.on_packet:
            self.on_packet[packet_id](data)

    def get_tile(self, x: int, y: int) -> int:
        """Get tile ID at position (0-63, 0-63). Returns 0 if out of bounds."""
        if not self.tiles or x < 0 or x >= 64 or y < 0 or y >= 64:
            return 0
        return self.tiles[y * 64 + x]

    def _apply_board_modify(self, level_name: str, info: dict) -> None:
        """Patch a PLO_BOARDMODIFY/BOARDMODIFY2 tile delta into cached board
        data (self.levels[level_name] and, if it's the active level,
        self.tiles). Only layer 0 (the main board) is applied - extra layers
        go through PLO_BOARDLAYER/on_board_layer instead."""
        if info.get('layer', 0) != 0:
            return
        x, y = info.get('x', 0), info.get('y', 0)
        w, h = info.get('width', 0), info.get('height', 0)
        tiles = info.get('tiles') or []
        if w <= 0 or h <= 0 or len(tiles) < w * h:
            return

        def _patch(board: List[int]) -> None:
            i = 0
            for row in range(h):
                ty = y + row
                if ty < 0 or ty >= 64:
                    i += w
                    continue
                for col in range(w):
                    tx = x + col
                    if 0 <= tx < 64:
                        board[ty * 64 + tx] = tiles[i]
                    i += 1

        board = self.levels.get(level_name)
        if board is not None and len(board) >= 4096:
            _patch(board)
        if level_name == self._tiles_level_name and self.tiles and len(self.tiles) >= 4096:
            _patch(self.tiles)

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

        # Sample the player's body down the centre column — head, mid, feet, and
        # the very bottom of the feet — not a single point. Walking *down* onto a
        # link the feet reach it; walking *up* to a door (cave entrances sit on
        # blocking tiles you can't stand on, only the head overlaps) the upper
        # points reach it. The 3.0 sample matters for DOWNWARD edge/door links:
        # collision stops the feet (py+3) at the link row, but the old max sample
        # (2.5) fell half a tile short, so you'd jam against a downward warp and
        # have to noclip through it.
        px, py = self.player.x, self.player.y
        local_x = (px + 1.0) % 64
        body_ys = [(py + d) % 64 for d in (0.5, 1.5, 2.5, 3.0)]

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

            # Triggered if any body sample falls inside the link rect.
            if lx <= local_x < lx + lw and any(ly <= by < ly + lh for by in body_ys):
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

        # Destination coords (LOCAL within the destination level) may be a number
        # OR a Graal expression referencing playerx/playery — used by edge links
        # to keep the player's coordinate across a seamless crossing (e.g.
        # "playery", "playerx-4"). Plain float() throws on those and the old code
        # fell back to (0,0), so every such warp dumped the player in the corner.
        px, py = self.player.x % 64, self.player.y % 64
        new_x = _eval_warp_coord(dest_x, px, py)
        new_y = _eval_warp_coord(dest_y, px, py)
        # If an expression can't be evaluated, keep the current coordinate rather
        # than slamming to 0 (much closer to correct for an edge crossing).
        if new_x is None:
            new_x = px
        if new_y is None:
            new_y = py

        # Warp through warp_to_level so the SERVER is notified (PLI_LEVELWARP)
        # and the destination's coordinate frame is handled correctly: a GMAP
        # segment gets world coords, a standalone interior level (house/cave
        # reached via a door) keeps local coords. Without the server warp the
        # server keeps streaming our old GMAP position and yanks us around.
        return self.warp_to_level(dest_level, new_x, new_y)

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
