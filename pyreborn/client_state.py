"""State components composed by Client.

Client used to carry ~156 flat attributes assigned in one 414-line __init__.
They are grouped here by what owns them, and Client keeps every one of them
readable/writable under its original name (see client._STATE_ALIASES), so
existing call sites, the pygame game/ layer, game_tester and the test suite are
unaffected.

Nothing here talks to the network or to Client: these are plain state holders.
"""

from typing import Callable, Dict, List, Optional, Tuple

from . import tiletypes as _tiletypes
from .clock import Clock
from .protocol import VERSIONS, ClientType
from .lru import LruCache as BoundedLRU  # noqa: F401  (client.py re-exports the name)

# What an EntityState reads when no Client has rebound `item_clock`.
_DEFAULT_CLOCK = Clock()

MAX_CACHED_FILES = 512
MAX_REQUESTED_FILES = 4096


class StateComponent:
    """Base of every state component below.

    The component's declared fields are whatever its constructor assigns to
    public (non-underscore) attributes. That one declaration drives two things:

    * `reset()` restores declared defaults (all fields, or the named ones).
    * client.py derives the flat `Client.<name>` alias for each field from
      `state_fields()` and `ALIAS_PRIVATE`, so a new field is added in ONE place.

    Class knobs a component may override:

    * `ALIAS_PRIVATE` - fields whose flat Client name carries a leading
      underscore (`_authenticated` for `authenticated`).
    * `ALIAS_PROPERTIES` - fields implemented as class-level properties, which
      `vars()` cannot see.
    * `NO_ALIAS` - fields deliberately not exposed on Client.
    """

    ALIAS_PRIVATE: frozenset = frozenset()
    ALIAS_PROPERTIES: Tuple[str, ...] = ()
    NO_ALIAS: frozenset = frozenset()

    _ctor_args: tuple = ()

    @classmethod
    def _default_args(cls) -> tuple:
        return ()

    @classmethod
    def state_fields(cls) -> List[str]:
        """Declared field names, from a default-constructed instance."""
        probe = cls(*cls._default_args())
        names = [n for n in vars(probe) if not n.startswith('_')]
        names += [n for n in cls.ALIAS_PROPERTIES if n not in names]
        return names

    def reset(self, *fields: str) -> None:
        """Restore declared defaults: the named fields, or all when none given.

        Mutable containers are cleared and refilled in place, so a reference
        another object holds to one of them stays valid.
        """
        fresh = type(self)(*self._ctor_args)
        for name in (fields or self.state_fields()):
            default = getattr(fresh, name)
            current = getattr(self, name, None)
            if (type(current) is type(default)
                    and isinstance(default, (dict, list, set))):
                current.clear()
                if isinstance(default, dict):
                    current.update(default)
                elif isinstance(default, list):
                    current.extend(default)
                else:
                    current.update(default)
            else:
                setattr(self, name, default)


class SessionState(StateComponent):
    """Connection/handshake state plus everything the server announces about
    the session itself (flags, MOTD, freeze state, cookies)."""

    ALIAS_PRIVATE = frozenset({
        'colors_len', 'file_no_modtime', 'use_pixel_props', 'original_flow',
        'authenticated',
        'login_time', 'raw_data_expected', 'in_update'})

    @classmethod
    def _default_args(cls) -> tuple:
        return ("2.22",)

    def __init__(self, version: str):
        self._ctor_args = (version,)
        # PLPROP_COLORS width PRIOR: 5, the reference default. The width is a
        # server-wide mode (`servermode = newworld` -> 8), not a client-version
        # fact, so it is not derived from `version`. The width actually in
        # force is colors_width.colors_len_in_force(): PLO_NEWWORLDMODE (177)
        # decides, else the session's parse evidence, else this prior. A wrong
        # width misaligns the whole player-props packet.
        self.colors_len = 5
        # Clients older than 2.1 receive PLO_FILE without the 5-byte modtime
        # header (GServer Player.cpp sendFile: "Older client versions didn't
        # send the modTime"). Only the 1.x entries qualify.
        self.file_no_modtime = str(version).startswith("1.")
        # v2.30+/v6 clients report movement with hi-res X2/Y2 pixel props;
        # classic servers only track X/Y. Keyed off the negotiated version.
        self.use_pixel_props = not (str(version).startswith("1.")
                                    or str(version).startswith("2."))

        # The server's original-client flow serves only login type
        # PLTYPE_CLIENT (versions 1.411 and 2.17 here), and sends
        # PLO_LEVELNAME only for the first level (GServer-v2
        # PlayerLogin.cpp:68-69, PlayerClientOriginal.cpp:158-160).
        self.original_flow = VERSIONS[version].client_type is ClientType.TYPE_CLIENT \
            if version in VERSIONS else False

        # Authentication state
        self.authenticated = False
        self.login_time = 0.0

        # Raw-data announcement bookkeeping (PLO_RAWDATA). The actual
        # reassembly happens in protocol.py, which re-emits the payload under
        # its real packet id.
        self.raw_data_expected = 0

        # Server time (from heartbeat)
        self.server_time = 0

        # True while update() is dispatching received packets (see update()).
        self.in_update = False

        # Ghost mode state
        self.ghost_mode = 0

        # Server-control state (tier 3).
        self.frozen = False              # PLO_FREEZEPLAYER2 / PLO_UNFREEZEPLAYER
        self.classic_mode_disabled = False  # packet 176 (KINGDOMSMODE; legacy flag name)
        self.server_mode = ''            # 'kingdoms' (176) / 'newworld' (177) marker
        self.input_frozen = False        # only a legacy lock now; no packet sets it
        self.npcs_hidden = False         # PLO_HIDENPCS
        self.login_complete = False      # PLO_ONLINEMODE (blank "you're logged in" marker)
        self.server_warp_info: Optional[dict] = None  # last PLO_SERVERWARP target
        self.last_server_warp = ""       # last destination send_server_warp sent
        self.last_server_warp_at = 0.0   # monotonic time of that send
        self.server_warp_declined_until = 0.0  # monotonic end of the decline cooldown
        self.server_warp_offers = 0      # consent prompts opened this session
        self.server_warp_notice_at = None  # monotonic time of the last blocked-warp notice
        self.hide_player_until = 0.0     # monotonic end of a hideplayer() hide
        self.hide_player_hearts = None   # hearts last seen while hidden
        self.profiles: Dict[str, dict] = {}  # account -> profile (PLO_PROFILE)
        self.npcserver_addr: Optional[dict] = None  # PLO_NPCSERVERADDR
        self.net_cookie = ""             # PLO_SETNETCOOKIE

        # Misc server state (populated by the corresponding PLO handlers).
        self.global_flags: Dict[str, str] = {}   # PLO_FLAGSET: server-wide flags
        # PLO_STAFFGUILDS: None = never sent (client defaults apply for
        # isadmin), a list -- INCLUDING an empty one -- is server-authoritative
        # (see gs2_client._is_admin_guild)
        self.staff_guilds: Optional[List[str]] = None
        self.status_list: List[str] = []    # PLO_STATUSLIST (selectable statuses)
        self.server_message = ""            # PLO_STARTMESSAGE (MOTD)
        self.server_text = ""               # PLO_SERVERTEXT (last text answer)
        self.has_npc_server = False         # PLO_HASNPCSERVER (44) flag
        self.rpg_window_lines: List[str] = []   # PLO_RPGWINDOW (last window)
        self.default_weapon = 0             # PLO_DEFAULTWEAPON
        self.server_signature = 0           # PLO_SIGNATURE
        self.disconnect_reason = ""         # last PLO_DISCMESSAGE text (e.g. login reject)
        self.ghost_icon = False             # PLO_GHOSTICON


class LevelState(StateComponent):
    """The current level and every per-level thing keyed by level name."""

    ALIAS_PRIVATE = frozenset({
        'tiles_level_name', 'current_level_name', 'level_scope',
        'level_scope_segment', 'npc_level', 'adjacent_level_requests',
        'board_layers_level_name'})
    ALIAS_PROPERTIES = ('current_level_name',)
    NO_ALIAS = frozenset({'tiletypes', 'level_layers', 'streaming_level_name'})   # client.level_state.<name>

    def __init__(self):
        self.tiletypes = _tiletypes.TileTypeSelection()
        # Level data: 4096 tile IDs (64x64 grid) for current level
        self.tiles: List[int] = []
        self.tiles_level_name = ""     # which level self.tiles currently holds

        # GMAP support: multiple levels keyed by level name
        # Every level visited this session stays until disconnect: the server
        # never re-streams a board, links or signs for a level it marks
        # visited, so evicting one would leave a blank board on re-entry (the
        # reference client's level list has no cap either).
        self.levels: Dict[str, List[int]] = {}
        self.current_level_name = ""   # The player's actual level (set once at login)
        # The reference client keeps two level targets. `level_scope` is the
        # PLO_LEVELNAME one (TClient.cpp:3224-3241, `serverlevel`): signs,
        # chests, links, boards, board changes, items, explosions, baddies and
        # horses land there. It is a level name, or the current map's `.gmap`
        # name, which stands for the player's own segment (the resolvers in
        # client_gmap.py). An adjacent preload sets it to the neighbour for
        # the length of that static block, and the closing PLO_LEVELNAME
        # sets it back. `npc_level` is the PLO_SETACTIVELEVEL one
        # (TClient.cpp:3777-3784, `npcserverlevel`) that NPC packets read.
        self.level_scope = ""
        self.npc_level = ""
        # The last non-preload level PLO_LEVELNAME named: the segment a
        # `.gmap` scope falls back to while no position places the player.
        self.level_scope_segment = ""
        # The level whose static data is streaming right now (the last
        # PLO_LEVELNAME), adjacent preload or not. PLO_LEVELMODTIME ends that
        # data, before the set-active-level packet names the level.
        self.streaming_level_name = ""
        self.adjacent_level_requests: set[str] = set()
        self.level_modtimes: Dict[str, int] = {}  # PLO_LEVELMODTIME per level

        # Links: maps level_name -> list of link dicts
        self.links: Dict[str, List[dict]] = {}

        # Level chests: maps level name -> {(x, y): opened (bool)}
        self.chests: Dict[str, Dict[Tuple[int, int], bool]] = {}
        # Items held by chests, keyed in the same per-level shape. Item names
        # are known only for unopened chests announced on level entry.
        self.chest_items: Dict[str, Dict[Tuple[int, int], str]] = {}
        # The chest's sign index, same shape and same availability rule. The
        # level editor's export writes it back out, so a level round trip
        # must not lose it.
        self.chest_signs: Dict[str, Dict[Tuple[int, int], int]] = {}

        # Level signs: maps (x, y) -> text
        self.signs: Dict[str, Dict[Tuple[float, float], str]] = {}  # level -> {(x,y): text}
        # The same signs in ARRIVAL ORDER: level -> [(x, y, text), ...].
        # GS1 `say <n>` addresses signs by index, and the (x, y) dict above
        # cannot answer that: say-only signs are conventionally all parked at
        # "SIGN 0 0" (GTA's abermose7.nw stacks five there), so they collapse
        # to one dict key. Reset per level when a fresh board streams
        # (handlers/level.py) - servers that never re-stream a level's static
        # data per session (gs2emu) simply keep the first list.
        self.sign_lists: Dict[str, list] = {}

        # Board layers: maps layer_id -> tile data
        self.board_layers: Dict[int, bytes] = {}
        self.board_layers_level_name = ""
        # Extra board layers of levels we have left (level -> {layer: tiles}),
        # for the same reason as `levels`: the server sends layers only with a
        # fresh board.
        self.level_layers: Dict[str, Dict[int, bytes]] = {}

        # Gmap level-height overrides from PLO_BOARDHEIGHTS: (map_x, map_y) ->
        # {'block_x', 'block_y', 'block_width', 'block_height', 'heights'}.
        self.board_heights: Dict[Tuple[int, int], dict] = {}

        self.is_leader = False          # PLO_ISLEADER: we drive level NPCs/baddies

    # Every "the player is now in level X" write in client.py and
    # handlers/level.py flows through this one property (via the
    # _current_level_name alias), so it is THE hook that keeps the
    # per-session tilestype selection (TileTypeSelection.set_current_level /
    # TTiles::GetLevelTiles) in step with the player's level — for the
    # headless client as well as pygame.
    @property
    def current_level_name(self) -> str:
        return self._current_level_name_value

    @current_level_name.setter
    def current_level_name(self, value: str) -> None:
        self._current_level_name_value = value
        self.tiletypes.set_current_level(value)


class GmapState(StateComponent):
    """The loaded .gmap world: its grid, dimensions and coordinate framing."""

    ALIAS_PRIVATE = frozenset({
        'requested_gmap', 'gmap_spawn_x', 'gmap_spawn_y', 'gmap_offset_x',
        'gmap_offset_y', 'known_gmap_segments', 'last_gmap_name'})

    def __init__(self):
        # GMAP grid: maps (x, y) -> level_name
        self.gmap_grid: Dict[Tuple[int, int], str] = {}
        self.gmap_width = 0
        self.gmap_height = 0
        self.gmap_name = ""            # name of the loaded .gmap (e.g. chicken.gmap)
        # Last .gmap that WAS loaded, kept across _exit_gmap so a warp back
        # into one of its segments can rebuild the grid from the downloaded
        # file (Client.restore_known_gmap) instead of waiting for the server.
        self.last_gmap_name = ""
        self.requested_gmap = ""       # .gmap we've already sent a WANTFILE for
        self.bigmap_info: Dict = {}    # PLO_BIGMAP (171): image/levels_file/x/y (M-key map)
        self.minimap_info: Dict = {}   # PLO_MINIMAP (172): same shape (corner map)
        self.gmap_spawn_x = 0   # GMAP grid x from PLO_PLAYERWARP2
        self.gmap_spawn_y = 0   # GMAP grid y from PLO_PLAYERWARP2
        # Offset between world coordinate grid and GMAP grid
        # world_grid = gmap_grid + offset
        self.gmap_offset_x = 0
        self.gmap_offset_y = 0
        # Every level name that has EVER been a segment of a loaded .gmap
        # this session. Unlike gmap_grid this survives _exit_gmap, so a warp
        # back out of an interior can tell "this destination will become a
        # gmap segment again" and keep the transition held until the world
        # frame is re-established (see _maybe_release_local_transition).
        self.known_gmap_segments: set = set()


class WarpState(StateComponent):
    """In-flight level change: what we optimistically flipped to, what the
    server still has to confirm, and the renderer's transition hold."""

    ALIAS_PRIVATE = frozenset({
        'awaiting_warp_confirm', 'local_level_transition',
        'local_level_transition_epoch', 'local_level_transition_started',
        'local_level_transition_direction', 'plain_level_change_epoch',
        'warp_fallback', 'warp_echo'})

    def __init__(self):
        # Destination of a client-initiated warp awaiting the server's
        # authoritative PLO_LEVELNAME confirmation (see warp_to_level).
        self.awaiting_warp_confirm = ""
        # A client-initiated, standalone level change whose destination board
        # has not become the active board yet.  This is deliberately separate
        # from level_scope: gmap neighbour streaming changes that field
        # without moving the local player.
        self.local_level_transition = ""
        # Bumped when a held transition finishes (or is rolled back).  The
        # pygame renderer consumes this to snap even when the coordinate jump
        # is small enough that ordinary movement would interpolate it.
        self.local_level_transition_epoch = 0
        self.plain_level_change_epoch = 0
        # monotonic() stamp of when the current hold started - the renderer
        # fails open (releases) if confirmation never arrives.
        self.local_level_transition_started = 0.0
        # One-shot renderer hint for a standalone boundary-link transition.
        # It survives the board-ready release just long enough for the pygame
        # renderer to replace the cut with a static two-frame slide.
        self.local_level_transition_direction: Optional[int] = None
        # Pre-warp (level, x, y) snapshot to restore if the server rejects
        # the warp with PLO_WARPFAILED (warp_to_level flips state
        # optimistically, so a rejected warp would otherwise strand us at a
        # phantom level the server never confirmed).
        self.warp_fallback: Optional[Tuple[str, float, float]] = None
        # (destination level, monotonic()) of the last level change WE told
        # the server about, so its round-trip-late echo can be recognised and
        # not applied as a position. See Client.note_client_warp /
        # consume_warp_echo.
        self.warp_echo: Optional[Tuple[str, float]] = None


class EntityState(StateComponent):
    """Everything living in the world: NPCs, players, baddies, items and the
    transient bomb/arrow/horse entities."""

    ALIAS_PRIVATE = frozenset({'npc_cache', 'npc_pos_epoch'})
    NO_ALIAS = frozenset({'next_bomb_id'})   # reached as client.entities.next_bomb_id

    def __init__(self):
        # NPCs: maps npc_id -> npc dict with x, y, image, etc.
        self.npcs: Dict[int, dict] = {}
        # Per-level NPC snapshots so re-entering a level we've already visited
        # repopulates its NPCs even when the server only streams them on first
        # entry. Maps level_name -> {npc_id: props}.
        self.npc_cache: Dict[str, Dict[int, dict]] = {}
        # Monotonic counter backing npc['_pos_epoch'] (see _mark_npc_pos_snap):
        # bumped whenever an NPC's world_x/world_y is set OUTSIDE an actual
        # movement update (initial stream, gmap re-attribution, cache restore),
        # so the pygame renderer (render_entities.py's _render_entities) can
        # tell "the NPC's world position field jumped because it moved" apart
        # from "it jumped because we just found out where it really is" and
        # snap the visual position instead of lerping across the jump.
        self.npc_pos_epoch = 0
        # NPCs: maps npc_id -> {x, y, duration_ms, dx, dy, options} most recent
        # PLO_MOVE2/NPCMOVED update (in addition to self.npcs full props).
        self.npc_moves: Dict[int, dict] = {}

        # Other players: maps player_id -> player dict with x, y, nickname, account, etc.
        # This is the IN-LEVEL set (from PLO_OTHERPLPROPS), used for rendering.
        self.players: Dict[int, dict] = {}
        # GLOBAL roster of every player id seen via PLO_OTHERPLPROPS this
        # session -- the engine's `allplayers` (TGameEnvironment::allplayers,
        # fed by scriptfun_client_setotherplayerprops, FourPlay
        # TClient.cpp:3076-3160). Unlike `players`, entries survive level
        # leaves and cross-level updates; they are only removed by the
        # DISCONNECT prop (51) or PLO_DELPLAYER. Includes the id>=16000
        # externals/channel pseudo-players the serverlist-chat leg pushes.
        self.all_players: Dict[int, dict] = {}
        # Server-wide online roster from PLO_ADDPLAYER/PLO_DELPLAYER: the server
        # dumps everyone on login and announces joins/leaves. Maps id -> dict
        # with account/nickname/level/etc.
        self.player_list: Dict[int, dict] = {}

        # Ground-item coordinates are level-local on the wire. Keep the owning
        # level or identical positions in adjacent gmap boards overwrite each
        # other and every off-origin item is later mistaken for segment zero.
        self.items: Dict[str, Dict[Tuple[float, float], str]] = {}
        # When each ground item's client-side lifetime started: the moment it
        # reached this client (see ground_items.ITEM_LIFETIME_TICKS). The
        # server expires an item silently, so the client prunes `items` itself
        # (Client.expire_items). `item_clock` is injectable for tests.
        self.item_stamps: Dict[Tuple[str, Tuple[float, float]], float] = {}
        # Client rebinds this to its own clock's now().
        self.item_clock: Callable[[], float] = _DEFAULT_CLOCK.sim_now

        # Baddy coordinates are level-local on the wire. Keep the owning level
        # or identical positions in adjacent gmap boards are later folded onto
        # whichever segment currently contains the player.
        self.baddies: Dict[str, Dict[int, dict]] = {}

        # Weapons: maps weapon_name -> weapon dict with name, image, script
        self.weapons: Dict[str, dict] = {}

        # Bomb coordinates are level-local on the wire. Each level's ordered
        # mapping uses a client-wide placement id, so stacked bombs coexist.
        # Each record is the simulated bomb: x/y level-local wire position,
        # wx/wy world position, owner_id, from_player, power, placed_at and
        # fuse_s (seconds from placed_at to detonation). See _tick_bomb_sims.
        self.bombs: Dict[str, Dict[int, dict]] = {}
        self.next_bomb_id = 0
        self.arrows: List[dict] = []  # transient - arrows don't persist/despawn explicitly
        # Horse coordinates are level-local on the wire. Keep the owning level
        # or identical positions in adjacent gmap boards overwrite each other
        # and are later folded onto the player's current segment.
        self.horses: Dict[str, Dict[Tuple[float, float], dict]] = {}

        # Active explosions for rendering: list of {x, y, radius, power, time}
        self.active_explosions: List[dict] = []


class CombatState(StateComponent):
    """Client-authoritative combat bookkeeping (see the arrow-simulation
    section in client.py for the design these fields implement)."""

    ALIAS_PRIVATE = frozenset({
        'arrow_sims', 'pending_arrow_hits', 'arrow_hurt_suppress',
        'local_arrow_reports', 'own_recent_arrows'})

    def __init__(self):
        # Victim-side arrow flight simulation (client-authoritative combat
        # parity - see _tick_arrow_sims for the full design). Each entry:
        # {owner_id, x, y, dx, dy, spawn_time, last_tick}.
        self.arrow_sims: List[dict] = []
        # Arrow hits our own sim detected but hasn't applied yet - see
        # _ARROW_HIT_GRACE. Each entry: {owner_id, dx, dy, resolve_at}.
        self.pending_arrow_hits: List[dict] = []
        # owner_id -> suppress-until epoch time. Guards against double
        # damage on servers (pygserver) that ALSO run their own independent
        # server-side arrow simulation and send a real PLO_HURTPLAYER for
        # the same hit - see _tick_arrow_sims's docstring.
        self.arrow_hurt_suppress: Dict[int, float] = {}
        # Only locally applied arrows may consume one matching server echo.
        self.local_arrow_reports: Dict[int, float] = {}
        # Arrows we fired ourselves, so an echo of our own PLI_ARROWADD
        # coming back as PLO_ARROWADD (pygserver's handle_arrow_add
        # broadcasts to the WHOLE level including the shooter; GServer-v2
        # excludes the sender) isn't mistaken for an incoming attack and
        # simulated against ourselves. pyReborn doesn't track its own
        # numeric player id (PLO_PLAYERPROPS never carries one for "self"),
        # so entries are matched heuristically on direction/position/timing
        # instead of owner id - see _start_arrow_sim. Each entry:
        # (fire_time, direction, x, y).
        self.own_recent_arrows: List[Tuple[float, int, float, float]] = []

        # Auto-respond settings
        self.auto_respond_hurt = True  # Automatically send hurt response with health update
        self.hurt_animation = "hurt"   # Animation to use when hurt


class FileTransfers(StateComponent):
    """Download bookkeeping, including the large-file chunk protocol."""

    ALIAS_PRIVATE = frozenset({
        'pending_files', 'received_files', 'failed_files', 'file_attempts',
        'uptodate_files', 'cache_index', 'large_file_transfers',
        'update_packages', 'requested_files'})

    def __init__(self):
        # File download tracking
        self.pending_files: set = set()  # Files we're waiting for
        self.received_files: Dict[str, bytes] = BoundedLRU(MAX_CACHED_FILES)
        self.failed_files: set = set()  # Files that failed to download
        self.file_attempts: Dict[str, int] = {}
        self.uptodate_files: set = set()  # Files confirmed unchanged by the server
        self.cache_index: Optional[Dict[str, object]] = None

        # One server interleaved pics1.png with another large download and the
        # old single buffer silently replaced pics1.png's first half; its tail
        # was then cached as a complete image with modtime zero. Keep the wire
        # transaction state keyed by filename so unrelated starts cannot
        # replace bytes already in flight.
        self.large_file_transfers: Dict[str, dict] = {}

        # Update packages (.gupd) by name -> update_packages.UpdatePackage, and
        # the normalised names this session asked for (PLO_UPDATEPACKAGEISUPDATED
        # re-requests only those; FourPlay TClient.cpp:2407-2436).
        self.update_packages: Dict[str, object] = {}
        self.requested_files: Dict[str, bool] = BoundedLRU(MAX_REQUESTED_FILES)


class ScriptTransport(StateComponent):
    """Script/bytecode transport plus the optional GS1/GS2 host attachments
    that received scripts are handed to."""

    ALIAS_PRIVATE = frozenset({'gs2_requested'})

    def __init__(self):
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
        self.gs2_requested: set = set()


class Instrumentation(StateComponent):
    """Packet-coverage counters and parser diagnostics read by the QA probes."""

    ALIAS_PRIVATE = frozenset({'warned_packet_errors', 'handled_plo_ids'})

    @classmethod
    def _default_args(cls) -> tuple:
        return ((),)

    def __init__(self, handled_plo_ids):
        self._ctor_args = (handled_plo_ids,)
        # Packet coverage instrumentation (for the QA coverage harness).
        # Maps packet_id -> {'received': n, 'handled': n, 'errors': n, 'last_error': str}
        self.packet_stats: Dict[int, Dict[str, object]] = {}
        # Packet ids we've already logged a handler-exception warning for, so
        # a persistently-failing packet type doesn't spam the log every frame
        # (the count is still visible in packet_stats[id]['errors']).
        self.warned_packet_errors: set = set()
        # PLO ids this instance has a handler for. Subclasses (e.g.
        # RCClient) extend this so coverage counts their handlers too.
        self.handled_plo_ids = set(handled_plo_ids)
        # Player-property decoder anomalies are probe-visible. A warning means
        # the alternate known COLORS width recovered a clean parse; an error
        # means neither known width consumed the property stream cleanly.
        self.prop_parse_diagnostics = {
            'warnings': 0, 'errors': 0, 'width_fallbacks': 0,
        }


class Callbacks(StateComponent):
    """The `on_*` hooks an embedding app assigns. Each is None until set."""

    def __init__(self):
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
        # File failure callback: handler(filename)
        self.on_file_send_failed: Optional[Callable[[str], None]] = None
        # Update-package events (reference onUpdatePackageDownloaded,
        # onPackagesDownloadComplete, onUpdatePackageFailed):
        # progress(name, received, size), downloaded(name), complete(),
        # failed(gupd_filename).
        self.on_update_package_progress: Optional[Callable[[str, int, int], None]] = None
        self.on_update_package_downloaded: Optional[Callable[[str], None]] = None
        self.on_packages_download_complete: Optional[Callable[[], None]] = None
        self.on_update_package_failed: Optional[Callable[[str], None]] = None

        # Sign callback: handler(x, y, text) - when sign text is received
        self.on_sign: Optional[Callable[[float, float, str], None]] = None

        # Explosion callback: handler(x, y, radius, power) - explosion effect
        self.on_explosion: Optional[Callable[[float, float, int, int], None]] = None

        # A classic bush was cut: world origin and bushobj/putLeaps row.
        self.on_bush_cut: Optional[Callable[[float, float, int], None]] = None
        self.on_leaps: Optional[Callable[[int, float, float], None]] = None

        # Hit objects callback: handler(x, y, power, player_id) - object hit feedback
        self.on_hit_objects: Optional[Callable[[float, float, int, int], None]] = None

        # Minimap callback: handler(data) - minimap data received
        self.on_minimap: Optional[Callable[[bytes], None]] = None

        # Board layer callback: handler(layer, x, y, tiles) - extra level layer
        self.on_board_layer: Optional[Callable[[int, int, int, bytes], None]] = None

        # Ghost mode callback: handler(enabled) - ghost/spectator mode toggled
        self.on_ghost_mode: Optional[Callable[[int], None]] = None
        # Initial server message callback: handler(text).
        self.on_start_message: Optional[Callable[[str], None]] = None

        # Board modify callback: handler(info) - info is the dict from
        # parse_board_modify/parse_board_modify2 (x, y, width, height, tiles,
        # layer, and map_x/map_y for gmap deltas). Fired after self.tiles /
        # self.levels[...] has already been patched.
        self.on_board_modify: Optional[Callable[[dict], None]] = None

        # File-up-to-date callback: handler(filename) - server confirmed our
        # cached copy is current.
        self.on_file_uptodate: Optional[Callable[[str], None]] = None

        # Entity family callbacks (tier 2).
        self.on_bomb_add: Optional[Callable[[dict], None]] = None
        self.on_bomb_del: Optional[Callable[[float, float], None]] = None
        # A registry bomb detonated in the client simulation (fuse end, chain
        # or PLO_EXPLOSION never fire this): handler(record, cells) where cells
        # are the ExplosionCell objects of every cross, in world coordinates.
        self.on_bomb_exploded: Optional[Callable[[dict, list], None]] = None
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
        # A script's serverwarp() was suppressed by the decline cooldown or
        # the per-session offer cap: handler(destination), at most one call
        # per SERVER_WARP_NOTICE_INTERVAL seconds.
        self.on_server_warp_blocked: Optional[Callable[[str], None]] = None
        # Inbound triggeraction: handler(info) with player_id/npc_id/x/y/action.
        self.on_triggeraction: Optional[Callable[[dict], None]] = None
        # Profile received: handler(profile dict) (PLO_PROFILE).
        self.on_profile: Optional[Callable[[dict], None]] = None
        # NPCs hidden by server: handler() (PLO_HIDENPCS).
        self.on_hide_npcs: Optional[Callable[[], None]] = None
        # Login-complete notification: handler() (PLO_ONLINEMODE, blank -
        # see Player.cpp:709 "This seems to inform the client that they
        # have logged in.").
        self.on_login_complete: Optional[Callable[[], None]] = None

        # Chest callback: handler(x, y, opened) - level chest state
        self.on_chest: Optional[Callable[[int, int, bool], None]] = None

        # Disconnect callback: handler(reason) - server sent PLO_DISCMESSAGE
        self.on_disconnect: Optional[Callable[[str], None]] = None

        # Bytecode arrival callback: handler(kind, key, blob).
        self.on_gs2_bytecode: Optional[Callable[[str, object, bytes], None]] = None

        # Callbacks for the misc packets.
        self.on_server_text: Optional[Callable[[str], None]] = None
        self.on_rpg_window: Optional[Callable[[List[str]], None]] = None
        self.on_baddy_hurt: Optional[Callable[[int, int], None]] = None
        self.on_flag: Optional[Callable[[str, str], None]] = None
        self.on_flag_del: Optional[Callable[[str], None]] = None


# Client attribute name -> component class. client.py builds the flat state
# aliases (Client.<field>) from these classes' declared fields.
COMPONENT_CLASSES: Dict[str, type] = {
    'session': SessionState,
    'level_state': LevelState,
    'gmap_state': GmapState,
    'warp_state': WarpState,
    'entities': EntityState,
    'combat_state': CombatState,
    'file_transfers': FileTransfers,
    'scripts': ScriptTransport,
    'instrumentation': Instrumentation,
    'callbacks': Callbacks,
}


def derive_state_aliases() -> Dict[str, Tuple[str, str]]:
    """Flat Client attribute name -> (component attribute, field)."""
    aliases: Dict[str, Tuple[str, str]] = {}
    for component, cls in COMPONENT_CLASSES.items():
        for field in cls.state_fields():
            if field in cls.NO_ALIAS:
                continue
            name = '_' + field if field in cls.ALIAS_PRIVATE else field
            if name in aliases:
                raise RuntimeError("duplicate state alias %r" % name)
            aliases[name] = (component, field)
    return aliases
