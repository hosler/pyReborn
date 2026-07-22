"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import logging
import math
import re
import sys
import time
import traceback
from collections import OrderedDict
from typing import Optional, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

# LEVELWARP encodes coords as gchar half-tiles: byte = int(coord*2)+32, which
# must stay in [0, 255]. That bounds the warp target to [-16, 111.5] tiles.
WARP_COORD_MIN = -16.0
WARP_COORD_MAX = 111.5
MAX_CACHED_LEVELS = 512
MAX_CACHED_FILES = 512
MAX_LARGE_FILE_SIZE = 256 * 1024 * 1024
LARGE_FILE_SIZE_SLACK = 64 * 1024


class BoundedLRU(OrderedDict):
    """Dictionary-compatible LRU cache with a fixed entry limit."""

    def __init__(self, max_entries: int):
        super().__init__()
        self.max_entries = max_entries

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        present = super().__contains__(key)
        if present:
            self.move_to_end(key)
        return present

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.max_entries:
            self.popitem(last=False)

from reborn_protocol import BDPROP, BDMODE

from .protocol import Protocol, WebSocketProtocol, IS_BROWSER
from .player import Player
from .game.constants import (
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
    PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y,
    PLAYER_STAND_X, PLAYER_STAND_Y,
)
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
    parse_npc_showimgs,
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
    build_item_take,
    build_animation,
    build_hearts,
    build_arrow_count,
    build_bomb_count,
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
    build_baddy_props,
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
    parse_fullstop,
    parse_fullstop2,
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
    parse_push_away,
    parse_npcmoved,
    parse_move2,
    parse_move,
    parse_npcdel2,
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
        "PLO_SHOWIMGNPC",
        "PLO_LEVELCHEST", "PLO_DISCMESSAGE", "PLO_LEVELSIGN", "PLO_EXPLOSION",
        "PLO_HITOBJECTS", "PLO_MINIMAP", "PLO_BOARDLAYER", "PLO_GHOSTMODE",
        "PLO_WARPFAILED",
        # Misc server packets added for full coverage.
        "PLO_LEVELBOARD", "PLO_ISLEADER", "PLO_SIGNATURE", "PLO_BADDYHURT",
        "PLO_FLAGSET", "PLO_NPCWEAPONDEL", "PLO_LEVELMODTIME", "PLO_STARTMESSAGE",
        "PLO_DEFAULTWEAPON", "PLO_STAFFGUILDS", "PLO_SERVERTEXT",
        "PLO_SETACTIVELEVEL", "PLO_UNKNOWN168", "PLO_GHOSTICON", "PLO_RPGWINDOW",
        "PLO_STATUSLIST", "PLO_UNKNOWN190", "PLO_CLEARWEAPONS", "PLO_HASNPCSERVER",
        "PLO_LISTPROCESSES",
        "PLO_BIGMAP", "PLO_ADDPLAYER", "PLO_DELPLAYER",
        "PLO_SHOOT", "PLO_SHOOT2",
        # Tier 1: board modify / large files / board heights.
        "PLO_BOARDMODIFY", "PLO_BOARDMODIFY2", "PLO_BOARDHEIGHTS",
        "PLO_LARGEFILESTART", "PLO_LARGEFILESIZE", "PLO_LARGEFILEEND",
        "PLO_FILEUPTODATE",
        # Tier 2: entity families + NPC movement.
        "PLO_BOMBADD", "PLO_BOMBDEL", "PLO_ARROWADD", "PLO_HORSEADD",
        "PLO_HORSEDEL", "PLO_FIRESPY", "PLO_THROWCARRIED", "PLO_NPCMOVED",
        "PLO_MOVE2", "PLO_MOVE", "PLO_NPCDEL2", "PLO_FLAGDEL", "PLO_PUSHAWAY",
        # Tier 3: server-control packets.
        "PLO_FREEZEPLAYER2", "PLO_UNFREEZEPLAYER", "PLO_SAY2", "PLO_HIDENPCS",
        "PLO_SERVERWARP", "PLO_TRIGGERACTION", "PLO_DISABLECLASSICMODE",
        "PLO_FULLSTOP2",
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

    It's a plain number for most doors, but edge links use Reborn expressions
    that reference the player's current coordinate so a crossing is seamless:
    "playerx", "playery", "playery-4", "playerx+0.5", etc. Returns the resolved
    float, or None if it can't be parsed.
    """
    s = str(expr).strip().lower()
    # Server-controlled input (level link destination) — cap length and reject
    # '**' (power operator) before it ever reaches eval. Without this, a link
    # like "9**9**9**9" builds a tower-of-exponents that hangs the client (DoS).
    if len(s) > 64 or '**' in s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    s = s.replace('playerx', repr(float(player_x))).replace('playery', repr(float(player_y)))
    if len(s) > 64 or '**' in s:
        return None
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
        self.levels: Dict[str, List[int]] = BoundedLRU(MAX_CACHED_LEVELS)
        self._current_level_name = ""  # The player's actual level (set once at login)
        self._pending_level_name = ""  # Track which level data is being received
        # Destination of a client-initiated warp awaiting the server's
        # authoritative PLO_LEVELNAME confirmation (see warp_to_level).
        self._awaiting_warp_confirm = ""
        # A client-initiated, standalone level change whose destination board
        # has not become the active board yet.  This is deliberately separate
        # from _pending_level_name: gmap neighbour streaming changes that field
        # without moving the local player.
        self._local_level_transition = ""
        # Bumped when a held transition finishes (or is rolled back).  The
        # pygame renderer consumes this to snap even when the coordinate jump
        # is small enough that ordinary movement would interpolate it.
        self._local_level_transition_epoch = 0
        self._plain_level_change_epoch = 0
        # monotonic() stamp of when the current hold started - the renderer
        # fails open (releases) if confirmation never arrives.
        self._local_level_transition_started = 0.0
        # One-shot renderer hint for a standalone boundary-link transition.
        # It survives the board-ready release just long enough for the pygame
        # renderer to replace the cut with a static two-frame slide.
        self._local_level_transition_direction: Optional[int] = None
        # Every level name that has EVER been a segment of a loaded .gmap
        # this session. Unlike gmap_grid this survives _exit_gmap, so a warp
        # back out of an interior can tell "this destination will become a
        # gmap segment again" and keep the transition held until the world
        # frame is re-established (see _maybe_release_local_transition).
        self._known_gmap_segments: set = set()
        # Pre-warp (level, x, y) snapshot to restore if the server rejects
        # the warp with PLO_WARPFAILED (warp_to_level flips state
        # optimistically, so a rejected warp would otherwise strand us at a
        # phantom level the server never confirmed).
        self._warp_fallback: Optional[Tuple[str, float, float]] = None

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
        # Monotonic counter backing npc['_pos_epoch'] (see _mark_npc_pos_snap):
        # bumped whenever an NPC's world_x/world_y is set OUTSIDE an actual
        # movement update (initial stream, gmap re-attribution, cache restore),
        # so the pygame renderer (render_entities.py's _render_entities) can
        # tell "the NPC's world position field jumped because it moved" apart
        # from "it jumped because we just found out where it really is" and
        # snap the visual position instead of lerping across the jump.
        self._npc_pos_epoch = 0

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

        # Victim-side arrow flight simulation (client-authoritative combat
        # parity - see _tick_arrow_sims for the full design). Each entry:
        # {owner_id, x, y, dx, dy, spawn_time, last_tick}.
        self._arrow_sims: List[dict] = []
        # Arrow hits our own sim detected but hasn't applied yet - see
        # _ARROW_HIT_GRACE. Each entry: {owner_id, dx, dy, resolve_at}.
        self._pending_arrow_hits: List[dict] = []
        # owner_id -> suppress-until epoch time. Guards against double
        # damage on servers (pygserver) that ALSO run their own independent
        # server-side arrow simulation and send a real PLO_HURTPLAYER for
        # the same hit - see _tick_arrow_sims's docstring.
        self._arrow_hurt_suppress: Dict[int, float] = {}
        # Arrows we fired ourselves, so an echo of our own PLI_ARROWADD
        # coming back as PLO_ARROWADD (pygserver's handle_arrow_add
        # broadcasts to the WHOLE level including the shooter; GServer-v2
        # excludes the sender) isn't mistaken for an incoming attack and
        # simulated against ourselves. pyReborn doesn't track its own
        # numeric player id (PLO_PLAYERPROPS never carries one for "self"),
        # so entries are matched heuristically on direction/position/timing
        # instead of owner id - see _start_arrow_sim. Each entry:
        # (fire_time, direction, x, y).
        self._own_recent_arrows: List[Tuple[float, int, float, float]] = []

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
        # Initial server message callback: handler(text).
        self.on_start_message: Optional[Callable[[str], None]] = None

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

        # Push-away/knockback callback: handler(dx, dy) - tiles, signed (see
        # packets.parse_push_away for the PLO_PUSHAWAY GCHAR decode).
        self.on_pushaway: Optional[Callable[[float, float], None]] = None

        # NPC-moved callback: handler(info) where info has npc_id/x/y/new_level
        # (PLO_NPCMOVED - fired when an NPC warps to a different level).
        self.on_npc_moved: Optional[Callable[[dict], None]] = None
        # NPC move-queue update callback: handler(info) with npc_id/x/y/dx/dy/
        # duration_ms/options (PLO_MOVE2).
        self.on_npc_move: Optional[Callable[[dict], None]] = None
        # NPC-deleted callback: handler(npc_id) - lets the render/scripting
        # layer drop the NPC's collision shape and loaded GS1 prog so a
        # despawned NPC can't keep firing playertouchsme from its old tile.
        self.on_npc_del: Optional[Callable[[int], None]] = None
        # Sword-hit-NPC callback: handler(npc_id) - a sword swing connected
        # with a level NPC (see _sword_hit_npcs). The scripting layer wires
        # this to fire the GS1 `washit` event on that NPC.
        self.on_sword_hit_npc: Optional[Callable[[int], None]] = None

        # Server-control callbacks (tier 3).
        # Freeze state changed: handler(frozen: bool).
        self.on_freeze: Optional[Callable[[bool], None]] = None
        # Normal-input/HUD stop state changed: handler(frozen: bool).
        self.on_fullstop: Optional[Callable[[bool], None]] = None
        # Sign-style server message: handler(text) (PLO_SAY2).
        self.on_say2: Optional[Callable[[str], None]] = None
        # A player left our level (JOINLEAVELVL=0): handler(player_id).
        self.on_player_left: Optional[Callable[[int], None]] = None
        # Server warp target: handler(info) with name/host/port (PLO_SERVERWARP).
        # pyReborn does NOT auto-connect; the app decides.
        self.on_server_warp: Optional[Callable[[dict], None]] = None
        # Inbound triggeraction: handler(info) with player_id/npc_id/x/y/action.
        self.on_triggeraction: Optional[Callable[[dict], None]] = None
        # Profile received: handler(profile dict) (PLO_PROFILE).
        self.on_profile: Optional[Callable[[dict], None]] = None
        # NPCs hidden by server: handler() (PLO_HIDENPCS).
        self.on_hide_npcs: Optional[Callable[[], None]] = None
        # Login-complete notification: handler() (PLO_UNKNOWN168, blank -
        # see Player.cpp:709 "This seems to inform the client that they
        # have logged in.").
        self.on_login_complete: Optional[Callable[[], None]] = None

        # Chest callback: handler(x, y, opened) - level chest state
        self.on_chest: Optional[Callable[[int, int, bool], None]] = None

        # Disconnect callback: handler(reason) - server sent PLO_DISCMESSAGE
        self.on_disconnect: Optional[Callable[[str], None]] = None

        # Ghost mode state
        self.ghost_mode = False

        # Level chests: maps level name -> {(x, y): opened (bool)}
        self.chests: Dict[str, Dict[Tuple[int, int], bool]] = {}
        # Items held by chests, keyed in the same per-level shape. Item names
        # are known only for unopened chests announced on level entry.
        self.chest_items: Dict[str, Dict[Tuple[int, int], str]] = {}

        # Level signs: maps (x, y) -> text
        self.signs: Dict[str, Dict[Tuple[float, float], str]] = {}  # level -> {(x,y): text}

        # Active explosions for rendering: list of {x, y, radius, power, time}
        self.active_explosions: List[dict] = []

        # Board layers: maps layer_id -> tile data
        self.board_layers: Dict[int, bytes] = {}

        # File download tracking
        self._pending_files: set = set()  # Files we're waiting for
        self._received_files: Dict[str, bytes] = BoundedLRU(MAX_CACHED_FILES)
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
        self.input_frozen = False           # packets 176 / 177
        self.npcs_hidden = False         # PLO_HIDENPCS
        self.login_complete = False      # PLO_UNKNOWN168 (blank "you're logged in" marker)
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
        # (name, crc) weapon-bytecode pulls already sent, so a re-announced
        # unchanged header doesn't re-request.
        self._gs2_requested: set = set()
        # True while update() is dispatching received packets (see update()).
        self._in_update = False
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
        # Packet ids we've already logged a handler-exception warning for, so
        # a persistently-failing packet type doesn't spam the log every frame
        # (the count is still visible in packet_stats[id]['errors']).
        self._warned_packet_errors: set = set()
        # PLO ids this instance has a dispatch branch for. Subclasses (e.g.
        # RCClient) extend this so coverage counts their handlers too.
        self._handled_plo_ids = set(HANDLED_PLO_IDS)
        # Player-property decoder anomalies are probe-visible. A warning means
        # the alternate known COLORS width recovered a clean parse; an error
        # means neither known width consumed the property stream cleanly.
        self.prop_parse_diagnostics = {
            'warnings': 0, 'errors': 0, 'width_fallbacks': 0,
        }

    # =========================================================================
    # Connection
    # =========================================================================

    def connect(self) -> bool:
        """Connect to the server. Returns True if successful."""
        # Per-session decode state (codec, buffers) is reset inside
        # Protocol.connect(); this instance also gets reset here for the case
        # a Client is reused across connect() calls without an intervening
        # disconnect() (normal usage builds a fresh Client per connection —
        # see example_pygame.py's F8 server-switch loop — so this is
        # defensive, not load-bearing).
        self._authenticated = False
        if self.input_frozen:
            self.input_frozen = False
            if self.on_fullstop:
                self.on_fullstop(False)
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

    def move(self, dx: int, dy: int, step: float = 0.25,
             face_direction: Optional[int] = None) -> bool:
        """
        Move the player.

        Args:
            dx: X direction (-1=left, 0=none, 1=right)
            dy: Y direction (-1=up, 0=none, 1=down)
            step: Movement step size in tiles (default 0.5 for half-tile precision)
            face_direction: Override the facing direction sent/stored instead
                of the one inferred from (dx, dy). Used by the pygame
                client's corner-assist (game/actions.py's _move): a
                perpendicular nudge around a doorway/corner moves the
                player sideways for a frame, but they should keep facing
                whichever cardinal direction was actually pressed, not
                whichever way the assist nudged them.

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
        if face_direction is not None:
            direction = face_direction
        elif dx > 0:
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
        sent = self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

        # Classic sword damage is attacker-client-authoritative: the swing
        # itself is just a gani prop; the attacker detects the hit and sends
        # PLI_HURTPLAYER per victim (the server only relays/applies). Without
        # this, sword swings are cosmetic and players can't melee each other.
        # Level NPCs and baddies get the same treatment: NPCs react to a
        # `washit` event (bushes/pots/enemies with scripts) and baddies take
        # real damage via PLI_BADDYHURT.
        if sent:
            self._sword_hit_players(direction)
            self._sword_hit_npcs(direction)
            self._sword_hit_baddies(direction)
            # Also report the swing to the server so IT can run hit detection
            # against server-side scripted NPCs (fires their `washit`). Real
            # clients send PLI_HITOBJECTS on every swing; the probe point is
            # the center of the swing arc in local level coords.
            from .packets import build_hit_objects
            dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction, (0, 1))
            probe_x = (self.player.x % 64) + 1 + dir_vec[0] * 1.5
            probe_y = (self.player.y % 64) + 1.5 + dir_vec[1] * 1.5
            power = max(1.0, float(getattr(self.player, "sword_power", 1) or 1))
            self._protocol.send_packet(
                PacketID.PLI_HITOBJECTS, build_hit_objects(power, probe_x, probe_y))
        return sent

    # The blade rectangle starts at the attacker's body center. A target is
    # hittable when its canonical 2x2 collision box overlaps that rectangle.
    # These dimensions retain the former center-test envelope: adding the
    # target box's one-tile half-size gives 2.5 forward and 1.5 lateral tiles.
    _SWORD_REACH = 1.5
    _SWORD_HALF_WIDTH = 0.5

    def _target_in_sword_arc(self, target_x: float, target_y: float,
                             fx: int, fy: int) -> bool:
        """Whether a target collision box overlaps the facing sword arc."""
        my_cx = self.player.x + PLAYER_BODY_CENTER_X
        my_cy = self.player.y + PLAYER_BODY_CENTER_Y
        corners = (
            (target_x + PLAYER_COLLISION_LEFT, target_y + PLAYER_COLLISION_TOP),
            (target_x + PLAYER_COLLISION_LEFT, target_y + PLAYER_COLLISION_BOTTOM),
            (target_x + PLAYER_COLLISION_RIGHT, target_y + PLAYER_COLLISION_TOP),
            (target_x + PLAYER_COLLISION_RIGHT, target_y + PLAYER_COLLISION_BOTTOM),
        )
        forwards = [(x - my_cx) * fx + (y - my_cy) * fy for x, y in corners]
        laterals = [(x - my_cx) * fy - (y - my_cy) * fx for x, y in corners]
        return (max(forwards) > 0 and min(forwards) <= self._SWORD_REACH
                and max(laterals) >= -self._SWORD_HALF_WIDTH
                and min(laterals) <= self._SWORD_HALF_WIDTH)

    def _sword_hit_players(self, direction: int):
        """Send PLI_HURTPLAYER for every other player inside the sword arc."""
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        fx, fy = dir_vec
        # self.players['x'/'y'] are now always LEVEL-LOCAL (0-63) - the
        # PLO_OTHERPLPROPS handler normalizes both classic X/Y and
        # high-precision X2/Y2 into that one frame at merge time - while
        # self.player.x/y are WORLD coords on a GMAP, so folding in an
        # offset is still required to compare them. 'world_x'/'world_y' are
        # set on that same merge whenever the wire told us the true world
        # position (a value >= 64, only possible via X2/Y2); prefer those
        # when known instead of assuming the attacker's own segment. When
        # they're not known (pygserver never sends per-player GMAPLEVELX/Y
        # (43/44) for OTHERPLPROPS, so a player on a DIFFERENT segment from
        # ours has no way to report its true segment), fall back to folding
        # in the ATTACKER's own segment offset - correct for same-segment
        # targets, but a target one segment over (e.g. attacker on
        # chicken1 at world (64, 95.5), target on chicken2 at local
        # (63.5, 94), a 1.6-tile world gap) still won't connect. Documented
        # limitation, not fixable client-side without server support.
        seg_ox = (self.player.x // 64) * 64
        seg_oy = (self.player.y // 64) * 64
        # Half a heart per sword power level, matching the classic client.
        damage = 0.5 * max(1, int(getattr(self.player, 'sword_power', 1) or 1))
        for pid, p in list(self.players.items()):
            wx, wy = p.get('world_x'), p.get('world_y')
            if wx is not None and wy is not None:
                px, py = wx, wy
            else:
                px, py = p.get('x'), p.get('y')
                if px is None or py is None:
                    continue
                px, py = px + seg_ox, py + seg_oy
            if self._target_in_sword_arc(px, py, fx, fy):
                self.attack_player(pid, damage=damage,
                                   knockback_x=fx * 2, knockback_y=fy * 2)

    def _sword_hit_npcs(self, direction: int):
        """Fire on_sword_hit_npc for every visible, blocking level NPC inside
        the sword arc (same math as _sword_hit_players). Hidden NPCs (`hide`/
        `destroy` -> visible=False) and non-blocking ones (`dontblock`) are
        skipped: per npcserver-gs1.md, `visible` tracks whether an NPC has
        been made invisible, and a dontblock NPC has no collision to hit.
        NPC positions use world_x/world_y (set on PLO_NPCPROPS) since
        self.player.x/y are world coords on a GMAP."""
        if not self.on_sword_hit_npc:
            return
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        fx, fy = dir_vec
        for npc_id, npc in list(self.npcs.items()):
            if npc.get('visible', True) is False or npc.get('dontblock'):
                continue
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is None or ny is None:
                continue
            if self._target_in_sword_arc(nx, ny, fx, fy):
                self.on_sword_hit_npc(npc_id)

    def _sword_hit_baddies(self, direction: int):
        """Send PLI_BADDYHURT for every baddy inside the sword arc (same math
        as _sword_hit_players). Baddy x/y are level-local, not world coords
        (unlike NPCs, PLO_BADDYPROPS has no world_x/world_y), so fold in the
        current GMAP segment's offset first, like render_entities.py does for
        drawing them."""
        dir_vec = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}.get(direction)
        if not dir_vec:
            return
        fx, fy = dir_vec
        seg_off_x = seg_off_y = 0
        if self.gmap_grid:
            seg = next((g for g, n in self.gmap_grid.items()
                        if n == self._current_level_name), None)
            if seg:
                seg_off_x, seg_off_y = seg[0] * 64, seg[1] * 64
        # Half a heart per sword power level, matching the classic client.
        damage = 0.5 * max(1, int(getattr(self.player, 'sword_power', 1) or 1))
        for bid, b in list(self.baddies.items()):
            bx, by = b.get('x'), b.get('y')
            if bx is None or by is None:
                continue
            wx, wy = bx + seg_off_x, by + seg_off_y
            if self._target_in_sword_arc(wx, wy, fx, fy):
                if self.is_leader:
                    # As this level's leader we're the one who resolves baddy
                    # damage (see _leader_apply_baddy_damage) - apply it and
                    # broadcast the result directly instead of sending
                    # PLI_BADDYHURT, which the server would just relay back
                    # to us (we ARE the leader) and double-apply through the
                    # PLO_BADDYHURT handler below.
                    self._leader_apply_baddy_damage(bid, int(damage * 2))
                else:
                    self.hurt_baddy(bid, damage=damage, hurt_dx=fx, hurt_dy=fy)

    # ---- Leader-authoritative baddy damage (client-authoritative combat
    # parity, task 2) -----------------------------------------------------
    #
    # GServer-v2 makes the level's LEADER (the first player to enter it,
    # PLO_ISLEADER) the sole resolver of baddy damage: any other player's
    # PLI_BADDYHURT is relayed to the leader ONLY (msgPLI_BADDYHURT,
    # PlayerClientPackets.cpp:523-539 - `leader->sendPacket(...)`), and the
    # leader is expected to apply the damage locally and report the result
    # back via PLI_BADDYPROPS, which the server both stores server-side and
    # relays to every OTHER player in the level (msgPLI_BADDYPROPS,
    # PlayerClientPackets.cpp:494-521 - the leader itself is excluded from
    # that relay). Without this, non-leader clients' PLI_BADDYHURT packets
    # reach the leader and stop there - the leader's own baddies dict never
    # updates and nobody else ever learns the baddy took damage or died.

    def _leader_apply_baddy_damage(self, baddy_id: int, damage_half_hearts: float) -> bool:
        """Apply damage to a baddy we (the leader) own and broadcast the
        result. `damage_half_hearts` is in the same raw wire units as
        PLO_BADDYHURT's power field (half-hearts) - baddy['power'] itself is
        plain hit points (GServer-v2's BaddyProp::POWERIMAGE), not hearts;
        this client already treats one half-heart of sword damage as one
        point of baddy power (see the PLO_BADDYHURT handler, unchanged by
        this task), so the units are kept consistent with that existing
        convention rather than introduced fresh here.
        """
        baddy = self.baddies.get(baddy_id)
        if baddy is None:
            return False
        new_power = max(0, baddy.get('power', 0) - damage_half_hearts)
        baddy['power'] = new_power
        baddy['mode'] = int(BDMODE.DEAD) if new_power <= 0 else int(BDMODE.HURT)
        return self._leader_broadcast_baddy_props(baddy_id, baddy)

    def _leader_broadcast_baddy_props(self, baddy_id: int, baddy: dict) -> bool:
        """Send PLI_BADDYPROPS reporting this baddy's current POWERIMAGE +
        MODE. Leader-only - see the docstring above this section."""
        if not self.connected or not self._authenticated:
            return False
        data = build_baddy_props(baddy_id, {
            BDPROP.POWERIMAGE: (int(baddy.get('power', 0)), baddy.get('image', '') or ''),
            BDPROP.MODE: int(baddy.get('mode', BDMODE.WALK)),
        })
        return self._protocol.send_packet(PacketID.PLI_BADDYPROPS, data)

    def drop_bomb(self, power: int = 1) -> bool:
        """
        Drop a bomb at current position (PLI_BOMBADD; the server runs the
        fuse, explosion, and damage).

        Args:
            power: Bomb power (1-3)

        Returns:
            True if packet sent successfully
        """
        return self.put_bomb(power=power)

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
        # GS1 `replaceani` substitution (wired by the pygame client): the wire
        # prop must carry the replaced name so other clients play the level's
        # ani (and their NPC scripts see it via #m), like a real client.
        resolver = getattr(self, "ani_resolver", None)
        wire_name = gani_name
        if resolver is not None:
            try:
                wire_name = resolver(gani_name) or gani_name
            except Exception:
                pass
        # Always send local coords (0-63)
        local_x = self.player.x % 64
        local_y = self.player.y % 64
        data = build_animation(wire_name, local_x, local_y, self.player.direction)
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

        # Send combined hurt response with health + animation. Always send
        # LOCAL coords (0-63) via X2/Y2 - self.player.x/y are WORLD coords
        # on a GMAP (move()/sword_attack() already wrap with % 64 for this
        # same reason), but this used to send them verbatim. The server
        # tracks position per-level/local (pygserver player.py
        # _handle_player_props: `self.x = props[PLPROP.X2]`, no unwrap), so
        # a world value here poisoned the SERVER's notion of this player's
        # position - not just the wire relay other clients saw (BUG 1's
        # players_visible frame poisoning), but pygserver's own hurt-range
        # sanity check (combat.py handle_hurt_player: `abs(attacker.x -
        # target.x) > 6.0`), which started rejecting every subsequent hit
        # against this player as "out of range" once its tracked x/y jumped
        # by a whole segment (live repro: kills took 3-6 extra swings).
        data = build_hurt_response(
            new_hearts,
            self.player.x % 64,
            self.player.y % 64,
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

    def send_server_text(self, request: bool, text: str) -> bool:
        """Send a gtokenized server-list text request or command."""
        from .packets import _gtokenize
        packet_id = PacketID.PLI_REQUESTTEXT if request else PacketID.PLI_SENDTEXT
        return self._protocol.send_packet(packet_id, _gtokenize(text).encode("latin-1"))

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

    def delete_weapon(self, name: str) -> bool:
        """Remove a weapon from this account, locally and server-side
        (PLI_NPCWEAPONDEL — GServer erases it from account.weapons unless
        protected). This is what a weapon script's `destroy` does on the real
        client; without it, self-destroying weapons (the Bomber arena's
        -arenaSYS/-validation) pile up on the account and their playerenters
        re-fire on every later level/login."""
        if not name:
            return False
        self.weapons.pop(name, None)
        if not self.connected or not self._authenticated:
            return False
        try:
            data = name.encode("latin-1", "replace")
        except Exception:
            return False
        return self._protocol.send_packet(PacketID.PLI_NPCWEAPONDEL, data)

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

    def warp_to_level(self, level_name: str, x: float = 30.0,
                      y: float = 30.0,
                      transition_direction: Optional[int] = None) -> bool:
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

        # Guard BEFORE mutating any state: everything below (level reset, roster
        # clear, tile-cache swap) is irreversible, and build_level_warp encodes
        # x/y as gchar half-tiles (byte = int(coord*2)+32). A missing level name
        # or an off-map coordinate makes that build throw, leaving the client
        # desynced at a phantom level/position it can't recover from. Reject up
        # front instead — same graceful path a bogus level name already takes.
        if not level_name:
            logger.warning("warp_to_level: empty level name ignored")
            return False
        if not (WARP_COORD_MIN <= x <= WARP_COORD_MAX
                and WARP_COORD_MIN <= y <= WARP_COORD_MAX):
            logger.warning(
                "warp_to_level: (%s, %s) outside encodable range "
                "[%s, %s]; ignored", x, y, WARP_COORD_MIN, WARP_COORD_MAX)
            return False

        # Snapshot the authoritative pre-warp state BEFORE the optimistic
        # flip below, so a PLO_WARPFAILED rejection can restore it.
        pre_warp_state = (self._current_level_name, self.player.x, self.player.y)
        self._local_level_transition_direction = None

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
                and level_name not in self.gmap_grid.values()):
            self.players.clear()

        self._current_level_name = level_name
        self._pending_level_name = level_name
        # Keep player.level (the source of client.level and GS1 #L) in step
        # with the optimistic flip: it is otherwise only assigned on
        # PLO_PLAYERWARP, which a client-initiated warp may not receive before
        # level scripts re-run — weapon playerenters then read the OLD level
        # via #L (the Bomber arena weapon re-armed its "Joining..." curtain in
        # the lobby that way). Gmap convention keeps player.level = .gmap name,
        # so segment hops don't touch it.
        if level_name not in self.gmap_grid.values():
            self.player.level = level_name

        # If we've visited this level before, repopulate its board from cache
        # immediately so the renderer doesn't draw the OLD level's tiles under
        # the player while the server re-streams the board (the "warped before
        # the new tiles render" glitch). First-visit levels stay flagged stale
        # (tiles_level_name != current) so the client can show a loading state.
        if level_name in self.levels:
            self.tiles = self.levels[level_name]
            self._tiles_level_name = level_name

        # Restore any NPCs we cached for this level (and, for a gmap segment,
        # its sibling segments) on a previous visit. If the server re-streams
        # them, the fresh PLO_NPCPROPS just overwrites these.
        self._restore_cached_npcs(level_name)

        # Mark the warp as awaiting the server's authoritative confirmation.
        # We flipped _current_level_name above optimistically (for instant
        # tile/board display), but that also makes incoming NPC/chest props
        # get stamped with the new level — so old-level props still in transit
        # from before the server processed this warp would be mis-attributed
        # to the new level. On the confirming PLO_LEVELNAME we re-reset to
        # purge them (TCP order guarantees they arrive before it).
        if level_name not in self.gmap_grid.values():
            self._awaiting_warp_confirm = level_name
            self._warp_fallback = pre_warp_state
            if level_name != pre_warp_state[0]:
                self._local_level_transition = level_name
                self._local_level_transition_started = time.monotonic()
                if self.player.hearts > 0 and transition_direction in range(4):
                    self._local_level_transition_direction = transition_direction

        # The LEVELWARP packet carries LOCAL coords within the target segment.
        data = build_level_warp(x, y, level_name)
        sent = self._protocol.send_packet(PacketID.PLI_LEVELWARP, data)
        if not sent:
            self._restore_failed_warp("send_failed")
            return False
        return True

    def _release_local_transition(self) -> None:
        """Unconditionally end a held local level transition (rollback,
        renderer fail-open timeout). Bumps the epoch so the renderer snaps."""
        if self._local_level_transition:
            self._local_level_transition = ""
            self._local_level_transition_epoch += 1
        self._local_level_transition_direction = None

    def _maybe_release_local_transition(self) -> None:
        """End the held transition once the destination is genuinely
        presentable. Called from every packet handler that advances a warp
        (LEVELNAME confirm, BOARDPACKET, PLAYERWARP2, load_gmap).

        Two conditions, both learned from live traces (funtimes, house/gmap
        links):
        - The destination's board must be the ACTIVE render board.
        - If the destination is a segment of a gmap seen this session, the
          gmap frame must be re-established (grid reloaded and the segment
          current). Releasing on the bare board - the old behavior - landed
          the camera in the standalone LOCAL interim frame of a gmap
          re-entry (edge-clamped, wrong bounds), then the .gmap reload
          flipped coordinates to the world frame and the camera visibly
          jumped a second time."""
        lvl = self._local_level_transition
        if not lvl:
            return
        if self._current_level_name != lvl:
            return
        if self._tiles_level_name != lvl:
            return
        if lvl in self._known_gmap_segments and not self.in_gmap_segment:
            return
        self._local_level_transition = ""
        self._local_level_transition_epoch += 1

    def _restore_failed_warp(self, reason: str) -> None:
        """Roll back the optimistic state flip from warp_to_level after the
        server rejected the warp. The server's authoritative state never
        changed (we're still in the pre-warp level), so restore the snapshot
        taken in warp_to_level: level name, position, render board, and any
        cached NPCs for that level."""
        fallback = self._warp_fallback
        target = self._awaiting_warp_confirm
        self._awaiting_warp_confirm = ""
        self._warp_fallback = None
        self._release_local_transition()
        if not fallback:
            return
        prev_level, prev_x, prev_y = fallback
        logger.info("Warp to %r rejected by server (%s); restoring %r",
                    target, reason, prev_level)
        self._current_level_name = prev_level
        self._pending_level_name = prev_level
        # Mirror warp_to_level's optimistic player.level flip on rollback
        # (same gmap-name convention: only plain levels are stored there).
        if prev_level and prev_level not in self.gmap_grid.values():
            self.player.level = prev_level
        self.player.x = prev_x
        self.player.y = prev_y
        # Re-point the render board and restore cached NPCs; the server-side
        # state never changed, so the cached data is still authoritative.
        if prev_level in self.levels:
            self.tiles = self.levels[prev_level]
            self._tiles_level_name = prev_level
        cached_npcs = self._npc_cache.get(prev_level)
        if cached_npcs:
            self.npcs.update({nid: npc.copy()
                              for nid, npc in cached_npcs.items()})

    def _reset_level_state(self, cache_npcs: bool = True):
        """Clear per-level state on a full level change so ground items,
        baddies and NPCs from the old level don't leak into the new one.

        Not called on seamless GMAP segment crossing (that goes through move(),
        not warp_to_level), so the stitched world keeps its entities.

        cache_npcs=False skips the per-level NPC snapshot: on a client-warp
        confirmation the NPCs present may be transit-window leaks stamped with
        the WRONG (optimistically-flipped) level, so caching them would poison
        _npc_cache for that level.

        Signs/chests/chest_items are NOT cleared: they're keyed by level name
        (no cross-level leakage possible) and gs2emu keeps a per-session
        level cache (PlayerClient.cpp sendStaticLevelData) - signs are only
        streamed on the FIRST entry of a level each session, so wiping them
        here made every sign in the world go dead after the first re-entered
        level (live-verified: re-warping into chicken_house1.nw streamed no
        PLO_LEVELSIGN at all). They mirror the server's own session cache."""
        self.items.clear()
        self.baddies.clear()
        # PLO_ISLEADER (GServer-v2 PlayerClient.cpp checkAndInformIfLevelLeader)
        # is only ever sent to (re-)CONFIRM leadership on a level - there's no
        # "you are NOT the leader" packet, so is_leader must default back to
        # False on every real level change and wait to be reconfirmed, or a
        # client that was ever a level's leader (even briefly alone on its
        # spawn level before another player joined) stays stuck reporting
        # is_leader=True forever afterward on levels it doesn't actually lead
        # - which would make _leader_apply_baddy_damage fire on every such
        # client at once. Live-verified against real gs2emu: without this
        # reset, a second bot that had ever been alone on a level kept
        # is_leader=True after warping onto a level someone else already led.
        self.is_leader = False
        # Snapshot NPCs per level before clearing so we can restore them if we
        # come back and the server doesn't re-stream them (see _npc_cache).
        if cache_npcs:
            for nid, npc in self.npcs.items():
                lvl = npc.get('_level')
                if lvl:
                    self._npc_cache.setdefault(lvl, {})[nid] = npc.copy()
        self.npcs.clear()

    def _mark_npc_pos_snap(self, npc: dict) -> None:
        """Stamp `npc` with a fresh _pos_epoch so the renderer snaps its
        visual position instead of lerping to it. Call this whenever
        world_x/world_y is set/changed for a reason OTHER than the NPC
        actually moving during play (new NPC streamed in, gmap
        re-attribution, cache restore on level re-entry) - see the
        _npc_pos_epoch comment in __init__."""
        self._npc_pos_epoch += 1
        npc['_pos_epoch'] = self._npc_pos_epoch

    def _restore_cached_npcs(self, level_name: str) -> None:
        """Repopulate self.npcs from _npc_cache for level_name - and, when
        it's a segment of the loaded gmap, for EVERY segment of that gmap
        (the stitched world renders neighbours too, and gs2emu's per-session
        level cache means none of them get re-streamed on re-entry). Fresh
        PLO_NPCPROPS from the server simply overwrite these afterwards."""
        if not level_name:
            return
        names = [level_name]
        if self.gmap_grid and level_name in self.gmap_grid.values():
            names = list(self.gmap_grid.values())
        for name in names:
            cached = self._npc_cache.get(name)
            if cached:
                # Restored NPCs reappear at their last-known position - the
                # renderer must snap to it, not lerp from wherever a
                # same-numbered NPC happened to be visually parked before
                # (see _mark_npc_pos_snap).
                restored = {nid: npc.copy() for nid, npc in cached.items()}
                for npc in restored.values():
                    self._mark_npc_pos_snap(npc)
                self.npcs.update(restored)

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

    def hurt_baddy(self, baddy_id: int, damage: float = 1.0,
                   hurt_dx: float = 0.0, hurt_dy: float = 0.0) -> bool:
        """
        Attack a baddy/enemy.

        Args:
            baddy_id: ID of the baddy to attack
            damage: Damage in hearts (default 1.0)
            hurt_dx, hurt_dy: Attack direction, -1.0..1.0 per axis (default
                0,0 = no direction / environment hit) - see build_baddy_hurt.

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_baddy_hurt(baddy_id, damage, hurt_dx, hurt_dy)
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
        this converts it the same way (see build_bomb_add).

        Ammo is client-authoritative on GServer-v2 (PLI_BOMBADD only spawns
        the projectile; the server never touches the count), so this refuses
        to fire at 0 bombs, decrements locally, and reports the new
        BOMBSCOUNT. pygserver additionally decrements server-side and echoes
        the authoritative count via PLO_PLAYERPROPS - that echo is an absolute
        value equal to our prediction, so the two don't double-decrement."""
        if not self.connected or not self._authenticated:
            return False
        if self.player.bombs <= 0:
            logger.debug("put_bomb: no bombs left, not firing")
            return False
        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        data = build_bomb_add(x, y, power, timer_ms)
        ok = self._protocol.send_packet(PacketID.PLI_BOMBADD, data)
        if ok:
            self.player.bombs -= 1
            self._protocol.send_packet(PacketID.PLI_PLAYERPROPS,
                                       build_bomb_count(self.player.bombs))
        return ok

    def remove_bomb(self, x: float, y: float) -> bool:
        """Remove a bomb at (x, y) (PLI_BOMBDEL)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_bomb_del(x, y)
        return self._protocol.send_packet(PacketID.PLI_BOMBDEL, data)

    def shoot_arrow(self, x: Optional[float] = None, y: Optional[float] = None,
                    direction: Optional[int] = None, sprite: int = 0,
                    power: int = 1) -> bool:
        """Fire an arrow (PLI_ARROWADD).

        Refuses to fire at 0 arrows, decrements the local count, and reports
        the new ARROWSCOUNT - ammo is client-authoritative on GServer-v2 (see
        put_bomb for the full parity story vs pygserver's server-side echo)."""
        if not self.connected or not self._authenticated:
            return False
        if self.player.arrows <= 0:
            logger.debug("shoot_arrow: no arrows left, not firing")
            return False
        # ARROWADD wire coords are LEVEL-LOCAL (0-63) like move()/sword —
        # GServer-v2's msgPLI_ARROWADD treats them as local-to-segment, and
        # sending world coords on a gmap made the server drop the arrow as
        # out-of-bounds on tick 1 (arrows silently never hit anything).
        if x is None:
            x = self.player.x % 64
        if y is None:
            y = self.player.y % 64
        if direction is None:
            direction = self.player.direction
        data = build_arrow_add(x, y, direction, sprite, power, from_player=True)
        ok = self._protocol.send_packet(PacketID.PLI_ARROWADD, data)
        if ok:
            self.player.arrows -= 1
            self._protocol.send_packet(PacketID.PLI_PLAYERPROPS,
                                       build_arrow_count(self.player.arrows))
            # Record so a self-echo of this same arrow (servers that
            # broadcast PLI_ARROWADD to the whole level, self included -
            # see _own_recent_arrows) doesn't get simulated as an incoming
            # attack against ourselves.
            now = time.time()
            self._own_recent_arrows.append((now, direction, float(x), float(y)))
            self._own_recent_arrows = [
                e for e in self._own_recent_arrows
                if now - e[0] < self._OWN_ARROW_ECHO_WINDOW]
        return ok

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

    @property
    def failed_files(self) -> set:
        """Filenames the server has refused to send."""
        return self._failed_files

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
        # Remember segment membership across _exit_gmap (see __init__).
        self._known_gmap_segments.update(level_names)


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

        # Re-entering a gmap from an interior level: the warp-time restore in
        # warp_to_level/_handle_packet only saw the target segment (the grid
        # was cleared by _exit_gmap), so now that the grid is rebuilt, pull
        # the sibling segments' cached NPCs back in too - gs2emu's session
        # cache won't re-stream any of them.
        self._restore_cached_npcs(self._current_level_name)

        # Update existing NPC coords to world coords now that we have the GMAP grid
        self._update_npc_world_coords()

        # A transition held across a gmap re-entry (interior -> segment) was
        # waiting for exactly this: the grid is rebuilt and coordinates are
        # world again, so the destination view is finally presentable.
        self._maybe_release_local_transition()

    def _update_npc_world_coords(self):
        """Update NPC world coordinates based on their level's grid position.

        Runs after load_gmap builds the grid, fixing up NPCs that arrived
        BEFORE the .gmap file download finished. NPCs carrying GMAPLEVELX/
        GMAPLEVELY props (gs2emu gmap streams - see the PLO_NPCPROPS handler)
        are re-attributed from those; at stream time the grid was empty so
        they were stamped with the .gmap name and local-as-world coords."""
        for npc_id, npc in self.npcs.items():
            gx = npc.get('gmaplevelx')
            gy = npc.get('gmaplevely')
            if gx is not None and gy is not None and (gx, gy) in self.gmap_grid:
                npc['_level'] = self.gmap_grid[(gx, gy)]
                if 'x' in npc:
                    raw_x = npc['x']
                    npc['world_x'] = (raw_x if (raw_x >= 64 or raw_x < 0)
                                       else raw_x + gx * 64)
                if 'y' in npc:
                    raw_y = npc['y']
                    npc['world_y'] = (raw_y if (raw_y >= 64 or raw_y < 0)
                                       else raw_y + gy * 64)
                # Re-attribution, not movement: the NPC didn't actually walk,
                # we just learned its real world position now that the grid
                # is built. Snap the renderer's visual position (see
                # _mark_npc_pos_snap) instead of letting it lerp across the
                # jump from the interim local-as-world guess.
                self._mark_npc_pos_snap(npc)
                continue
            npc_level = npc.get('_level')
            if not npc_level:
                continue  # No level info
            # Find the level's grid position
            for (gx, gy), level_name in self.gmap_grid.items():
                if level_name == npc_level:
                    # Same guard as the PLO_NPCPROPS handler (BUG 4): only
                    # fold in the segment offset for a still-local value, so
                    # a re-run of this (e.g. gmap grid arriving/reloading
                    # after an NPC's coords were already normalized to
                    # world) can't double-offset it.
                    if 'x' in npc:
                        raw_x = npc['x']
                        npc['world_x'] = (raw_x if (raw_x >= 64 or raw_x < 0)
                                           else raw_x + gx * 64)
                    if 'y' in npc:
                        raw_y = npc['y']
                        npc['world_y'] = (raw_y if (raw_y >= 64 or raw_y < 0)
                                           else raw_y + gy * 64)
                    # Re-attribution, not movement - see the snap comment on
                    # the gmaplevelx/y branch above.
                    self._mark_npc_pos_snap(npc)
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
    # Victim-side arrow flight simulation (client-authoritative combat
    # parity, task 1)
    #
    # GServer-v2 without a running NPCServer never runs its own arrow
    # collision detection at all (msgPLI_ARROWADD, PlayerClientPackets.cpp:
    # 287-311, only reaches level->addArrow() when m_server->hasNPCServer()
    # is true) - it just relays PLO_ARROWADD to everyone else in the level
    # and washes its hands of the projectile. That means on a real server,
    # the VICTIM is the only one who can ever notice they got shot: each
    # client must simulate every other player's arrow itself and apply
    # damage to itself the instant its own collision box connects.
    #
    # Flight constants below are copied from pygserver's own server-side
    # arrow simulation (pygserver/combat.py Arrow/CombatManager) as the best
    # available reference for "how an arrow behaves", not because pygserver
    # needs this client-side copy to work (pygserver already does its own
    # authoritative simulation - see the double-damage guard below).
    # =========================================================================

    _ARROW_SPEED = 8.0    # tiles/sec (pygserver combat.py Arrow.speed)
    _ARROW_LIFETIME = 2.0  # seconds (pygserver combat.py Arrow.expired)
    _ARROW_DAMAGE = 0.5    # hearts = 1 half-heart (pygserver CombatManager.arrow_damage)
    _ARROW_HIT_RADIUS = 1.0  # tiles, AABB half-extent (pygserver _update_arrow)
    _ARROW_STEP = 0.05     # seconds/substep - matches pygserver's 50ms tick;
                            # sub-stepping avoids tunneling through the
                            # player's hitbox when update() is called at a
                            # lower rate than the arrow crosses it.
    # Grace period between "our own sim detected a hit" and actually
    # applying it (see _tick_arrow_sims). pygserver runs its OWN
    # independent server-side arrow simulation using the exact same speed/
    # lifetime constants (that's where they're copied from), so it detects
    # the same hit at very nearly the same simulated time - and unlike our
    # side, applying it there is unconditional: pygserver's apply_damage()
    # has no idea our client is also tracking this arrow, so it always
    # subtracts once, on its own schedule, no matter what we do locally
    # (confirmed live: self-applying immediately let a fresh server-side
    # hit land moments later, silently overwriting our hearts via a second,
    # independent CURPOWER push and taking a full 1.0 hearts off a single
    # 0.5-heart arrow). Waiting this long before WE apply gives a
    # server-authoritative hit - if one is coming at all - time to arrive
    # and be recorded in _arrow_hurt_suppress first, so our own attempt
    # backs off instead of adding a second reduction. On real GServer-v2 no
    # such packet is ever sent (arrows are a pure client relay there), so
    # this is a pure server-only concern; a quarter-second is small enough
    # not to be felt as its own gameplay guard.
    _ARROW_HIT_GRACE = 0.25
    # Suppression window for the double-damage guard - matches pygserver's
    # own post-hit invincibility duration (CombatManager.apply_damage sets
    # `self._invincible[player.id] = time.time() + 1.0`), so it can't be
    # tighter than the window during which a genuine second hit from
    # anywhere wouldn't register server-side there anyway.
    _ARROW_HURT_SUPPRESS_WINDOW = 1.0
    _OWN_ARROW_ECHO_WINDOW = 0.5  # seconds to match a self-fired arrow's echo

    _ARROW_DIR_VECTORS = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}

    def _start_arrow_sim(self, info: dict, now: Optional[float] = None):
        """Begin victim-side flight simulation for another player's arrow
        (PLO_ARROWADD). Skips arrows we fired ourselves (matched
        heuristically against _own_recent_arrows - see its docstring) and
        arrows with no usable direction vector."""
        dir_vec = self._ARROW_DIR_VECTORS.get(info.get('direction'))
        if dir_vec is None:
            return
        if now is None:
            now = time.time()

        self._own_recent_arrows = [
            e for e in self._own_recent_arrows if now - e[0] < self._OWN_ARROW_ECHO_WINDOW]
        for i, (fire_time, fdir, fx, fy) in enumerate(self._own_recent_arrows):
            if (fdir == info.get('direction')
                    and abs(fx - info['x']) < 1.0 and abs(fy - info['y']) < 1.0):
                del self._own_recent_arrows[i]
                return

        self._arrow_sims.append({
            'owner_id': info.get('owner_id', 0),
            'x': info['x'], 'y': info['y'],
            'dx': dir_vec[0], 'dy': dir_vec[1],
            'spawn_time': now, 'last_tick': now,
        })

    def _advance_arrow_sim(self, sim: dict, now: float, my_x: float, my_y: float) -> bool:
        """Step one arrow simulation forward from its last-checked time to
        `now`, sub-stepping at _ARROW_STEP so a low update() call rate can't
        let the arrow tunnel through the player's hitbox between checks.
        Returns True (and leaves `sim` at the point of impact) on hit."""
        dt_total = now - sim['last_tick']
        if dt_total <= 0:
            return False
        steps = max(1, int(dt_total / self._ARROW_STEP) + 1)
        step_dt = dt_total / steps
        hit = False
        for _ in range(steps):
            sim['x'] += sim['dx'] * self._ARROW_SPEED * step_dt
            sim['y'] += sim['dy'] * self._ARROW_SPEED * step_dt
            if (abs(sim['x'] - my_x) < self._ARROW_HIT_RADIUS
                    and abs(sim['y'] - my_y) < self._ARROW_HIT_RADIUS):
                hit = True
                break
        sim['last_tick'] = now
        return hit

    def _resolve_pending_arrow_hit(self, pending: dict):
        """Apply arrow damage to ourselves via the same self-authoritative
        hearts-update path (respond_to_hurt) the PLO_HURTPLAYER handler
        uses, unless a server hurt packet for this same owner already
        landed during the grace period (see _tick_arrow_sims / the
        double-damage guard docs above _ARROW_HIT_GRACE) - in which case
        this is a duplicate and is dropped."""
        owner_id = pending['owner_id']
        now = time.time()
        if owner_id in self._arrow_hurt_suppress and now < self._arrow_hurt_suppress[owner_id]:
            return
        self._arrow_hurt_suppress[owner_id] = now + self._ARROW_HURT_SUPPRESS_WINDOW
        self.respond_to_hurt(self._ARROW_DAMAGE, self.hurt_animation)
        if self.on_hurt:
            # damage_type 2 = ARROW, matching pygserver's DamageType.ARROW.
            self.on_hurt(owner_id, self._ARROW_DAMAGE, 2, pending['dx'], pending['dy'])

    def _tick_arrow_sims(self, now: Optional[float] = None):
        """Advance every tracked victim-side arrow simulation, queue
        self-damage for any that connect with our own collision box this
        tick (see _ARROW_HIT_GRACE for why it's queued rather than applied
        immediately), and resolve anything whose grace period has elapsed.
        Call regularly (update() does this automatically)."""
        if now is None:
            now = time.time()

        if self._arrow_hurt_suppress:
            self._arrow_hurt_suppress = {
                oid: exp for oid, exp in self._arrow_hurt_suppress.items() if exp > now}

        if self._arrow_sims:
            my_x = self.player.x % 64
            my_y = self.player.y % 64
            alive = []
            for sim in self._arrow_sims:
                if now - sim['spawn_time'] >= self._ARROW_LIFETIME:
                    continue  # expired - either a miss/dodge, or simply too old
                if self._advance_arrow_sim(sim, now, my_x, my_y):
                    self._pending_arrow_hits.append({
                        'owner_id': sim['owner_id'], 'dx': sim['dx'], 'dy': sim['dy'],
                        'resolve_at': now + self._ARROW_HIT_GRACE,
                    })
                    continue  # consumed on hit - handed off to the pending queue
                alive.append(sim)
            self._arrow_sims = alive

        if self._pending_arrow_hits:
            still_pending = []
            for pending in self._pending_arrow_hits:
                if now >= pending['resolve_at']:
                    self._resolve_pending_arrow_hit(pending)
                else:
                    still_pending.append(pending)
            self._pending_arrow_hits = still_pending

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

        # Flagged so re-entrant callers (a GS2 script sleep() pumping update
        # from inside a packet-fired handler) can detect they're already in
        # the packet loop and must not recurse into it.
        self._in_update = True
        try:
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
                    stats['last_traceback'] = traceback.format_exc()
                    if packet_id not in self._warned_packet_errors:
                        self._warned_packet_errors.add(packet_id)
                        logger.warning(
                            "Handler for packet %d raised %s: %s (further errors "
                            "for this packet id are counted in packet_stats but "
                            "not logged)", packet_id, type(e).__name__, e)
        finally:
            self._in_update = False

        self._tick_arrow_sims()

        return packets

    def _handle_packet(self, packet_id: int, data: bytes):
        """Handle a received packet."""

        # Level name - track which level we're receiving data for
        if packet_id == PacketID.PLO_LEVELNAME:
            level_name = parse_level_name(data)
            # .nw files are actual levels, .gmap is the world map name
            if level_name.endswith('.nw'):
                # A real level transition (server push via PLO_PLAYERWARP/
                # PLO_PLAYERWARP2 for RC warps/respawn, or a client-initiated
                # warp_to_level()) always (re-)announces the destination via
                # this packet — GServer-v2 PlayerClient.cpp:1421/1473. Segments
                # of the currently loaded gmap are announced the same way as
                # we stream across them and must NOT reset per-level state
                # (that would wipe the stitched world's chests/signs/items/
                # NPCs on every segment hop); distinguish the two by checking
                # whether level_name is one of the loaded gmap's segments.
                is_gmap_segment = (self.gmap_width > 0 and
                                    level_name in self.gmap_grid.values())
                if is_gmap_segment:
                    # A GMAP segment's PLO_LEVELNAME is ambiguous on its own:
                    # pygserver sends it both for a genuine warp/spawn (via
                    # _send_level, always followed by PLO_PLAYERWARP2) AND for
                    # a passive adjacent-segment preload (PLI_ADJACENTLEVEL,
                    # sent by request_adjacent_levels() below and answered by
                    # pygserver player.py _handle_adjacent_level, which streams
                    # only [PLO_LEVELNAME, board] for a neighbour so the world
                    # renders stitched — the player never moves and no warp
                    # packet follows). Blindly trusting every one as "we are
                    # now here" mislabels _current_level_name as whichever
                    # neighbour preloaded last: e.g. spawning into chicken1.nw
                    # (world (94, 94.5)) but ending up reporting chicken8.nw
                    # once its 8 surrounding segments finish preloading, while
                    # the NPCs/chests actually streamed still belong to
                    # chicken1.nw. PLO_PLAYERWARP2 is the reliable "we actually
                    # moved" signal — real warps/spawns always send it,
                    # preloads never do — and its handler below already sets
                    # _current_level_name from gmap_x/gmap_y, so leave it alone
                    # here rather than trust this packet directly.
                    pass
                elif (self._awaiting_warp_confirm
                      and level_name != self._awaiting_warp_confirm):
                    # A level stream already in flight is not authoritative
                    # evidence that a client-requested warp failed.  In
                    # particular, link-touch can race an old/adjacent board
                    # response queued before PLI_LEVELWARP.  Route its board
                    # through _pending_level_name below, but keep the requested
                    # destination active and the camera held.  A PLAYERWARP
                    # naming another level is the authoritative rejection.
                    pass
                elif level_name != self._current_level_name:
                    self._current_level_name = level_name
                    self._plain_level_change_epoch += 1
                    # Real warp: drop the old level's items/baddies/NPCs so
                    # stale entries (e.g. a link back through a door that
                    # doesn't exist here) don't leak into the new level,
                    # then restore this level's NPCs from the session cache
                    # (gs2emu won't re-stream them on a re-entry).
                    self._reset_level_state()
                    self._restore_cached_npcs(level_name)
                elif level_name == self._awaiting_warp_confirm:
                    # Client-initiated warp: _current_level_name already equals
                    # level_name (flipped optimistically at send), so the guard
                    # above missed. Reset now on the authoritative confirmation
                    # to purge any old-level NPC/chest props that leaked in
                    # during the send->confirm window. cache_npcs=False: those
                    # leaks are mis-stamped with THIS level, so caching them
                    # would poison _npc_cache. On a FIRST visit the server
                    # streams the real NPCs right after this packet; on a
                    # re-entry it streams nothing (per-session level cache),
                    # so restore this level's NPCs from our own session
                    # cache - warp_to_level's optimistic restore was just
                    # wiped by the reset above. (_npc_cache only ever holds
                    # entries snapshotted with cache_npcs=True, i.e. stamped
                    # BEFORE the warp, so no transit-window leak comes back.)
                    self._reset_level_state(cache_npcs=False)
                    self._restore_cached_npcs(level_name)
                    self._plain_level_change_epoch += 1
                if (self._awaiting_warp_confirm
                        and level_name == self._awaiting_warp_confirm):
                    # The requested destination announcement confirms the
                    # client warp. Other level streams can be stale/preloads;
                    # an authoritative PLAYERWARP handles a real rejection.
                    self._awaiting_warp_confirm = ""
                    self._warp_fallback = None
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
            # A cached-board destination already has its tiles active (set
            # synchronously in warp_to_level), so this announcement is the
            # release point - the server may not re-stream the board at all
            # (per-session level cache).
            self._maybe_release_local_transition()

        # PLO_WARPFAILED (15) - the server rejected a warp (GServer-v2
        # PlayerClient.cpp:1180/1275 sends it with the failed level name when
        # a target level can't be loaded/entered). warp_to_level flipped
        # level/position optimistically, so restore the pre-warp snapshot or
        # we'd be stranded reporting a phantom level the server never put us
        # in (its authoritative state still has us in the old level).
        # NB: gs2emu does NOT send this for a bad PLI_LEVELWARP - that
        # rejection is detected via the PLO_PLAYERPROPS path below.
        elif packet_id == PacketID.PLO_WARPFAILED:
            failed_level = data.decode('latin-1', errors='replace').strip()
            if self._awaiting_warp_confirm and (
                    not failed_level
                    or failed_level == self._awaiting_warp_confirm):
                self._restore_failed_warp("PLO_WARPFAILED")
            else:
                logger.warning("PLO_WARPFAILED for %r with no matching "
                               "pending warp", failed_level)

        # Player properties (our player data)
        elif packet_id == PacketID.PLO_PLAYERPROPS:
            props = parse_player_props(
                data, self._colors_len, self.prop_parse_diagnostics)

            # Silent warp rejection (gs2emu): msgPLI_LEVELWARP with an
            # unloadable level sends NO PLO_WARPFAILED - it "resolves" by
            # re-warping us to our CURRENT level (PlayerClientPackets.cpp:
            # 92-98), and the same-level warp path (PlayerClient.cpp:
            # 1198-1218) emits only X2/Y2 props. So a server-set position
            # arriving while our warp still awaits its PLO_LEVELNAME confirm
            # means the server re-anchored us in the PRE-warp level: restore
            # it, then let the props below apply the authoritative position.
            # (A confirmed warp clears the flag via PLO_LEVELNAME before any
            # in-level props arrive, so this can't fire on a successful one.)
            if (self._awaiting_warp_confirm and self._warp_fallback
                    and ('x' in props or 'y' in props)):
                self._restore_failed_warp(
                    "server re-anchored position without level confirm")

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
                # Weapon headers announced earlier in this login burst
                # couldn't be pulled yet (request_weapon_bytecode refuses
                # pre-auth) — pull them now.
                for wname, hdr in self.gs2_script_headers.items():
                    if hdr.get('type') == 'weapon' and not hdr.get('bytecode'):
                        req_key = (wname, hdr.get('crc', ''))
                        if req_key not in self._gs2_requested:
                            if self.request_weapon_bytecode(wname):
                                self._gs2_requested.add(req_key)

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
                weapon.setdefault('image', '')
                weapon.setdefault('script', '')
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

                # Double-damage guard: a server that runs its own
                # independent arrow-flight simulation in parallel with ours
                # (pygserver's CombatManager - see _tick_arrow_sims) can end
                # up telling us about a hit we ALREADY applied to ourselves
                # via that simulation. Real GServer-v2 never sends this for
                # arrows at all (no NPCServer => arrows are a pure client-
                # authoritative relay, see msgPLI_ARROWADD), so this is a
                # pygserver-only concern in practice.
                already_applied = (
                    attacker_id in self._arrow_hurt_suppress
                    and time.time() < self._arrow_hurt_suppress[attacker_id])

                # We got hurt - client is source of truth for health
                # Auto-respond with new health and hurt animation
                if self.auto_respond_hurt and damage > 0 and not already_applied:
                    self.respond_to_hurt(damage, self.hurt_animation)
                    # This may be the server's own independent detection of
                    # a hit our own arrow sim hasn't caught up to yet (it
                    # might not have even started - the PLO_ARROWADD relay
                    # and this PLO_HURTPLAYER aren't guaranteed to arrive in
                    # any particular order). Mark the owner suppressed
                    # UNCONDITIONALLY (not just when a sim already exists -
                    # a sim starting moments later must still respect this)
                    # and drop any in-flight sims from them so ours doesn't
                    # also apply this same hit once it resolves.
                    self._arrow_hurt_suppress[attacker_id] = (
                        time.time() + self._ARROW_HURT_SUPPRESS_WINDOW)
                    if any(s['owner_id'] == attacker_id for s in self._arrow_sims):
                        self._arrow_sims = [
                            s for s in self._arrow_sims if s['owner_id'] != attacker_id]
                    if any(p['owner_id'] == attacker_id for p in self._pending_arrow_hits):
                        self._pending_arrow_hits = [
                            p for p in self._pending_arrow_hits if p['owner_id'] != attacker_id]

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

        # Level board tiles (uncompressed, 8192 bytes; also reached for the
        # compressed/raw path - PLO_RAWDATA's payload is re-emitted with this
        # same packet_id once its byte count is satisfied, see protocol.py).
        elif packet_id == PacketID.PLO_BOARDPACKET:
            tiles = parse_board_packet(data)
            # Store in levels dict using the pending level name
            level_for_tiles = self._pending_level_name or self._current_level_name
            if level_for_tiles:
                self.levels[level_for_tiles] = tiles
            # self.tiles is the ACTIVE render/collision board and must only
            # ever switch on a real warp/segment change - never on a GMAP
            # adjacent-segment preload (request_adjacent_levels(), answered
            # by pygserver's _handle_adjacent_level with just [LEVELNAME,
            # board] for a neighbour so the world renders stitched via
            # self.levels[] above; the player never actually moves there).
            # Previously this unconditionally clobbered self.tiles with
            # whichever segment's board arrived LAST, so during a preload
            # burst the active board flip-flopped between our real segment
            # and up to 8 neighbours (symptom: /map returning contradictory
            # boards, collision/warp-validation following stale tiles).
            # _current_level_name is always updated (optimistically, at
            # send time) before the confirming board for an actual
            # warp/segment-cross arrives - see warp_to_level()/move() and
            # the PLO_LEVELNAME/PLO_PLAYERWARP2 handlers - so gating on it
            # here is sufficient and doesn't need extra state.
            if level_for_tiles == self._current_level_name:
                self.tiles = tiles
                self._tiles_level_name = level_for_tiles
                self._maybe_release_local_transition()
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
                    new_size = len(self._large_file_buffer) + len(file_data)
                    announced_limit = (
                        self._large_file_expected_size + LARGE_FILE_SIZE_SLACK)
                    if (new_size > MAX_LARGE_FILE_SIZE
                            or (self._large_file_expected_size > 0
                                and new_size > announced_limit)):
                        logger.warning(
                            "Aborting oversized file transfer for %r", filename)
                        self._large_file_pending = None
                        self._large_file_buffer = bytearray()
                        self._large_file_expected_size = 0
                        self._failed_files.add(filename)
                        self._pending_files.discard(filename)
                    else:
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
                self._large_file_expected_size = 0
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
                level = warp.get('level', '')
                if (self._awaiting_warp_confirm and level
                        and level != self._awaiting_warp_confirm):
                    self._restore_failed_warp(
                        "server player warp named another level")
                # x, y are local coords (0-63 range for non-GMAP levels)
                self.player.x = warp.get('x', 0)
                self.player.y = warp.get('y', 0)
                if level:
                    self.player.level = level

        # Player warp with GMAP position (packet 49)
        elif packet_id == PacketID.PLO_PLAYERWARP2:
            warp = parse_playerwarp2(data)
            if warp:
                level = warp.get('level', '')
                if (self._awaiting_warp_confirm and level
                        and level != self._awaiting_warp_confirm):
                    self._restore_failed_warp(
                        "server player warp named another level")
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
                # Segment warp with the grid already loaded: the world frame
                # is established right here, so a held transition can end.
                self._maybe_release_local_transition()

        # Level links
        elif packet_id == PacketID.PLO_LEVELLINK:
            link = parse_level_link(data)
            level_for_link = self._pending_level_name or self._current_level_name
            if link and level_for_link:
                if level_for_link not in self.links:
                    self.links[level_for_link] = []
                # Re-entering a level the server has already streamed us
                # (e.g. crossing a GMAP segment boundary out and back)
                # re-sends every PLO_LEVELLINK for that level, and this
                # handler used to append unconditionally - links list grew
                # a duplicate per revisit. Identity here is the parsed
                # fields themselves (dest/rect), matching how callers
                # de-duplicate downstream (see playtest_daemon._current_links).
                if link not in self.links[level_for_link]:
                    self.links[level_for_link].append(link)

        # NPC properties
        elif packet_id == PacketID.PLO_NPCPROPS:
            props = parse_npc_props(data)
            if props and 'id' in props:
                npc_id = props['id']
                # Associate the NPC with a level. Preference order:
                #   1. GMAPLEVELX/GMAPLEVELY props (41/42) -> gmap segment.
                #      gs2emu streams a gmap's NPCs under PLO_SETACTIVELEVEL
                #      <map>.gmap (the whole gmap is one level server-side,
                #      PlayerClient.cpp sendDynamicLevelData), so the pending
                #      level name is the .gmap - useless for placement. The
                #      grid cell carried in the props is the real attribution.
                #   2. The level this (already-known) NPC was previously
                #      attributed to - a partial runtime update without level
                #      info must not re-stamp it with whatever level happened
                #      to stream last (e.g. a stale neighbour-preload name).
                #   3. The pending/current level (fresh NPC on a plain level).
                npc_level = self._pending_level_name or self._current_level_name
                grid_cell = None
                gx = props.get('gmaplevelx')
                gy = props.get('gmaplevely')
                if gx is not None and gy is not None and (gx, gy) in self.gmap_grid:
                    grid_cell = (gx, gy)
                    npc_level = self.gmap_grid[grid_cell]
                else:
                    known = self.npcs.get(npc_id)
                    if (known is not None and known.get('_level')
                            and gx is None and gy is None):
                        npc_level = known['_level']
                    if self.gmap_grid and npc_level:
                        grid_cell = next(
                            (cell for cell, name in self.gmap_grid.items()
                             if name == npc_level), None)
                props['_level'] = npc_level

                # Convert NPC local coords to world coords if in GMAP.
                # parse_npc_props writes both NPCPROP.X/Y (props 2/3,
                # always LEVEL-LOCAL) and NPCPROP.X2/Y2 (props 75/76,
                # pixel-precision - LOCAL on this server, but WORLD per the
                # general protocol on a real GServer-v2) into the same
                # 'x'/'y' keys. Blindly adding the segment offset here
                # double-counts it whenever 'x'/'y' is already a world
                # value: seen live as an NPC's world_x/world_y reading
                # exactly +64,+64 past its true position for one update,
                # then reverting. Guard the same way as the OTHERPLPROPS
                # merge (BUG 1): only fold in the segment offset for a
                # value that's still in the local 0-63 range.
                if grid_cell is not None:
                    cgx, cgy = grid_cell
                    if 'x' in props:
                        raw_x = props['x']
                        props['world_x'] = (raw_x if (raw_x >= 64 or raw_x < 0)
                                             else raw_x + cgx * 64)
                    if 'y' in props:
                        raw_y = props['y']
                        props['world_y'] = (raw_y if (raw_y >= 64 or raw_y < 0)
                                             else raw_y + cgy * 64)
                elif not self.gmap_grid:
                    # Not in GMAP - local coords are world coords
                    if 'x' in props:
                        props['world_x'] = props['x']
                    if 'y' in props:
                        props['world_y'] = props['y']
                if npc_id in self.npcs:
                    self.npcs[npc_id].update(props)
                else:
                    # First sighting of this NPC (not an in-play movement
                    # update of an already-known one) - mark it so the
                    # renderer snaps its visual position rather than lerping
                    # in from wherever a stale same-id visual entry sits.
                    self._mark_npc_pos_snap(props)
                    self.npcs[npc_id] = props

        # Server-owned GS1 showimg layers. Updates are sparse and mutate the
        # same npc['imgs'] records used by locally interpreted GS1 commands.
        elif packet_id == PacketID.PLO_SHOWIMGNPC:
            info = parse_npc_showimgs(data)
            npc_id = info.get('npc_id')
            if npc_id is not None:
                npc = self.npcs.setdefault(npc_id, {})
                imgs = npc.setdefault('imgs', {})
                if info['clear']:
                    imgs.clear()
                for index, changes in info['records'].items():
                    rec = imgs.setdefault(index, {})
                    rec.update(changes)
                    rec.setdefault('screen', False)
                    rec.setdefault('vis', 4)

        # NPC deleted
        elif packet_id == PLO_NPCDEL:
            if len(data) >= 3:
                from .packets import PacketReader
                reader = PacketReader(data)
                npc_id = reader.read_gint3()
                npc = self.npcs.pop(npc_id, None)
                if npc is not None:
                    level = npc.get('_level')
                    cached = self._npc_cache.get(level) if level else None
                    if cached is not None:
                        cached.pop(npc_id, None)
                    if self.on_npc_del:
                        self.on_npc_del(npc_id)

        # NPC deleted, scoped to an explicit level (packet 150) - sent instead
        # of PLO_NPCDEL when the target player's active level isn't the NPC's
        # level, so it also purges any stale per-level cache entry (see
        # packets.parse_npcdel2 for why: GServer-v2 targets clients with a
        # past-visit cached copy, not just the current level roster).
        elif packet_id == PacketID.PLO_NPCDEL2:
            info = parse_npcdel2(data)
            npc_id = info['npc_id']
            level = info['level']
            if npc_id in self.npcs:
                del self.npcs[npc_id]
                if self.on_npc_del:
                    self.on_npc_del(npc_id)
            cached = self._npc_cache.get(level)
            if cached is not None:
                cached.pop(npc_id, None)

        # Other player properties
        elif packet_id == PacketID.PLO_OTHERPLPROPS:
            props = parse_other_player(
                data, self._colors_len, self.prop_parse_diagnostics)
            if props and 'id' in props:
                player_id = props['id']
                # JOINLEAVELVL=0 is the server's "this player left your
                # level" notification — drop them from the level roster
                # (they'd otherwise linger as a ghost at their last position).
                if props.get('joinleave') == 0:
                    self.players.pop(player_id, None)
                    if self.on_player_left:
                        self.on_player_left(player_id)
                    return
                # gs2emu (unlike pygserver) keeps sending cross-level updates
                # for players AFTER their leave notification, with CURLEVEL
                # naming their new level — verified via live beta4 packet
                # trace (leave packet followed one tick later by a props
                # packet that re-added the ghost). self.players is the
                # SAME-LEVEL roster (sword arcs, visibility), so a props
                # update naming a different level removes/skips instead.
                other_level = props.get('level')
                if other_level and self._current_level_name and \
                        other_level != self._current_level_name:
                    self.players.pop(player_id, None)
                    return
                # A non-empty CURCHAT prop is another player's chat bubble — the
                # primary in-level chat path. Surface it through on_chat.
                chat = props.get('chat')
                if chat and self.on_chat:
                    self.on_chat(player_id, chat)
                # Normalize the X/Y coordinate FRAME before merging. Classic
                # props 15/16 (X/Y) are always LEVEL-LOCAL (0-63), while
                # high-precision props 78/79 (X2/Y2) legitimately carry WORLD
                # pixels on a gmap - but parse_other_player writes both into
                # the same 'x'/'y' keys, and different server paths favor
                # different props for the SAME player (e.g. pygserver relays
                # plain movement via classic X/Y-derived local coords but
                # respond_to_hurt's PLI_PLAYERPROPS round-trips the client's
                # own WORLD x/y through X2/Y2 verbatim). Without normalizing,
                # players[pid]['x'/'y'] silently flips frame depending on
                # which prop arrived LAST: seen live as another player's y
                # reported as 97.25 instead of 33.25 (a whole segment high),
                # which made every sword-hit test against them miss forever
                # until they moved or warped. Store LEVEL-LOCAL canonically
                # in 'x'/'y' (wrap any world value via %64) and ALSO stash
                # 'world_x'/'world_y' whenever the wire value told us the
                # true world position (>=64, only possible from X2/Y2) so
                # consumers that need world coords (cross-segment hit tests)
                # can prefer that over re-deriving it from our own segment.
                # A fresh LOCAL-only update invalidates any previously known
                # world_x/world_y - we no longer know it's still correct -
                # rather than let a stale world coordinate silently survive
                # a merge alongside a now-different local one.
                if 'x' in props:
                    raw_x = props['x']
                    if raw_x >= 64 or raw_x < 0:
                        props['world_x'] = raw_x
                        props['x'] = raw_x % 64
                    else:
                        props['world_x'] = None
                if 'y' in props:
                    raw_y = props['y']
                    if raw_y >= 64 or raw_y < 0:
                        props['world_y'] = raw_y
                        props['y'] = raw_y % 64
                    else:
                        props['world_y'] = None
                if player_id in self.players:
                    # Merge props (None marks a value to DROP, not store -
                    # see the world_x/world_y invalidation above).
                    existing = self.players[player_id]
                    for key, value in props.items():
                        if value is None:
                            existing.pop(key, None)
                        else:
                            existing[key] = value
                else:
                    self.players[player_id] = {k: v for k, v in props.items()
                                                if v is not None}

        # Level chest (packet 4)
        elif packet_id == PacketID.PLO_LEVELCHEST:
            chest = parse_level_chest(data)
            if chest:
                # Match sign attribution exactly: during gmap preloading the
                # pending board owns streamed local coordinates, not necessarily
                # the segment containing the player.
                lvl = self._pending_level_name or self._current_level_name
                key = (chest['x'], chest['y'])
                self.chests.setdefault(lvl, {})[key] = chest['opened']
                # Remember the item an unopened chest holds (only sent on warp).
                if 'item' in chest:
                    self.chest_items.setdefault(lvl, {})[key] = chest['item']
                if self.on_chest:
                    self.on_chest(chest['x'], chest['y'], chest['opened'])

        # Disconnect message (packet 16) - server kicked us / is shutting down
        elif packet_id == PacketID.PLO_DISCMESSAGE:
            reason = data.decode('latin-1', errors='replace').strip()
            self.disconnect_reason = reason
            if self.on_disconnect:
                self.on_disconnect(reason)
            self.disconnect()

        # Process-list request (packet 182).  The server's PLI_PROCESSLIST
        # handler guntokenizes this payload into newline-separated identities;
        # one simple token is therefore a complete, truthful one-entry list.
        elif packet_id == PacketID.PLO_LISTPROCESSES:
            self._protocol.send_packet(PacketID.PLI_PROCESSLIST, b"pyReborn")

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
                if self.is_leader:
                    # We're this level's leader: GServer-v2 only ever relays
                    # another player's PLI_BADDYHURT to us (see the
                    # docstring above _leader_apply_baddy_damage) - nobody
                    # else will apply it, so we must apply it locally and
                    # tell the rest of the level the result.
                    self._leader_apply_baddy_damage(bid, bh['power'])
                else:
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
            self._start_arrow_sim(info)

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

        # Push-away/knockback impulse (packet 38). See packets.parse_push_away
        # for the GCHAR decode this uses (GServer-v2's IEnums.h doc comment is
        # the only reference for this packet in this workspace).
        elif packet_id == PacketID.PLO_PUSHAWAY:
            push = parse_push_away(data)
            if push and self.on_pushaway:
                self.on_pushaway(push['dx'], push['dy'])

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

        # NPC move-queue update, legacy pre-CLVER_2_3 clients (packet 165) -
        # the GCHAR-precision counterpart to PLO_MOVE2 above. GServer-v2 sends
        # exactly one of MOVE/MOVE2 per move-queue update depending on the
        # recipient's negotiated version (NPC.cpp:472-475), so mirror MOVE2's
        # handling rather than treating this as a separate stream.
        elif packet_id == PacketID.PLO_MOVE:
            info = parse_move(data)
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
            self.input_frozen = parse_fullstop(data)
            if self.on_fullstop:
                self.on_fullstop(self.input_frozen)

        # Alternate blank input-stop command (packet 177).
        elif packet_id == PacketID.PLO_FULLSTOP2:
            self.input_frozen = parse_fullstop2(data)
            if self.on_fullstop:
                self.on_fullstop(self.input_frozen)

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
                elif info['type'] == 'weapon':
                    # Header-only announcement (Weapon.cpp
                    # registerWeaponWithPlayer): the server waits for the
                    # client to pull the bytecode with PLI_UPDATESCRIPT (a
                    # real client skips the pull only on a local-cache CRC
                    # hit; we keep no disk cache, so always fetch). Once per
                    # (name, crc) so a re-announced unchanged script doesn't
                    # re-request forever.
                    req_key = (info['name'], info['crc'])
                    if req_key not in self._gs2_requested:
                        if self.request_weapon_bytecode(info['name']):
                            self._gs2_requested.add(req_key)

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
            if self.on_start_message:
                self.on_start_message(self.server_message)

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

        # Login-complete marker, blank (packet 168). GServer-v2 sends this
        # once per connection, right after PLO_HASNPCSERVER, purely to signal
        # "you have finished logging in" - see server/src/player/Player.cpp:
        # 700-709 ("This seems to inform the client that they have logged
        # in."). No payload to parse; just latch the flag.
        elif packet_id == PacketID.PLO_UNKNOWN168:
            self.login_complete = True
            if self.on_login_complete:
                self.on_login_complete()

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

        # Blank marker before weapon list (packet 190) - no-op. NOTE:
        # GServer-v2 (this workspace's ground truth) never actually sends
        # this packet - dependencies/gs2lib/include/IEnums.h:306 and
        # server/src/player/Player.cpp only list it in the packet-name enum
        # table, with no sendPacket call anywhere in server/src. Kept as a
        # defensive no-op in case another server implementation emits it.
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
        # A configured grid can outlive the player's presence in that world
        # (for example after a server-side warp to a standalone level).  Only
        # interpret player coordinates as world coordinates while the
        # authoritative current level still identifies that world.  Do not use
        # _pending_level_name/active_level here: adjacent-level preloads change
        # those stream-routing fields without moving the player.
        current_is_gmap = (
            self._current_level_name in self.gmap_grid.values()
            or bool(self.gmap_name and self._current_level_name == self.gmap_name)
        )
        if not self.gmap_grid or not current_is_gmap:
            return self._current_level_name

        # Player coords are GMAP-relative, so grid position is simply x // 64
        grid_x = int(self.player.x // 64)
        grid_y = int(self.player.y // 64)

        # Look up level name at this grid position
        return self.gmap_grid.get((grid_x, grid_y), self._current_level_name)

    def get_chest_opened(self, level_name: str, x: int, y: int) -> bool:
        """Return whether the chest at local coordinates is open."""
        return self.chests.get(level_name, {}).get((x, y), False)

    def set_chest_opened(self, level_name: str, x: int, y: int) -> None:
        """Mark the chest at local coordinates open in its owning level."""
        self.chests.setdefault(level_name, {})[(x, y)] = True

    def chests_in_level(self, level_name: str) -> Dict[Tuple[int, int], bool]:
        """Return chest state for one level, or an empty mapping."""
        # Accept the former flat shape when lightweight callers replace this
        # attribute directly; live client state always uses the nested shape.
        if self.chests and all(isinstance(key, tuple) for key in self.chests):
            return self.chests  # type: ignore[return-value]
        return self.chests.get(level_name, {})

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

        # The reference engine tests one whole-tile directional probe, not
        # collision-box overlap. These offsets are GServer-v2
        # PlayerClient.cpp testForLinks()'s touchTest table; Level.cpp
        # getLink() then performs an inclusive point-in-bounding-box test.
        # Floor the world point before folding it into a 64-tile segment so
        # the probe wraps coherently when it crosses a GMAP seam.
        px, py = self.player.x, self.player.y
        probe_offsets = ((1.5, 1.0), (0.0, 2.0),
                         (1.5, 3.5), (3.0, 2.0))
        dx, dy = probe_offsets[int(self.player.direction) & 3]
        tile_x = math.floor(px + dx) % 64
        tile_y = math.floor(py + dy) % 64

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

            if lx <= tile_x <= lx + lw and ly <= tile_y <= ly + lh:
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
        # OR a Reborn expression referencing playerx/playery — used by edge links
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
        transition_direction = self._edge_transition_direction(
            link, new_x, new_y)
        return self.warp_to_level(
            dest_level, new_x, new_y,
            transition_direction=transition_direction)

    def _edge_transition_direction(self, link: dict, dest_x: float,
                                   dest_y: float) -> Optional[int]:
        """Return the walk direction for an unambiguous boundary crossing.

        Direction values are the protocol/player convention: up, left, down,
        right. A qualifying link must touch the boundary being walked through
        and land on the opposite boundary of a standalone destination.
        """
        if (self.in_gmap_segment
                or link.get('dest_level', '') in self._known_gmap_segments):
            return None
        try:
            x = float(link.get('x', 0))
            y = float(link.get('y', 0))
            width = float(link.get('width', 1))
            height = float(link.get('height', 1))
            direction = int(self.player.direction) & 3
        except (TypeError, ValueError):
            return None

        source_edges = (y <= 1, x <= 1, y + height >= 63,
                        x + width >= 63)
        destination_edges = (dest_y >= 60, dest_x >= 60,
                             dest_y <= 1, dest_x <= 1)
        if source_edges[direction] and destination_edges[direction]:
            return direction
        return None

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
