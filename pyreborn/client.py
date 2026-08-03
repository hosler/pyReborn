"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import logging
import time
import traceback
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_LARGE_FILE_SIZE = 256 * 1024 * 1024
LARGE_FILE_SIZE_SLACK = 64 * 1024

from reborn_protocol.coords import (
    LEVEL_SIZE, in_level_bounds, level_index, segment_at,
)

from .protocol import Protocol, WebSocketProtocol, IS_BROWSER
from .player import Player
# BoundedLRU / MAX_CACHED_* keep their old client.py names for callers and
# tests that reach for them there (tests/unit/test_security_correctness.py).
from .client_state import (  # noqa: F401  (BoundedLRU/MAX_CACHED_* re-exported)
    BoundedLRU,
    MAX_CACHED_FILES,
    MAX_CACHED_LEVELS,
    Callbacks,
    CombatState,
    EntityState,
    FileTransfers,
    GmapState,
    Instrumentation,
    LevelState,
    ScriptTransport,
    SessionState,
    WarpState,
)
from .packets import (
    PacketID,
    parse_player_props,
)
# Importing the package registers every @handles handler; PACKET_HANDLERS is
# the complete inbound-packet dispatch table (see _handle_packet).
from .handlers import PACKET_HANDLERS, STOP

# Every PLO packet id the dispatch table has a handler for. Used by the
# packet-coverage harness to distinguish "handled" from "silently dropped";
# derived from the registry, so it cannot drift from the handlers themselves
# (it used to be a hand-maintained name list).
HANDLED_PLO_IDS = set(PACKET_HANDLERS)


from .client_actions import ActionsMixin
from .client_appearance import AppearanceMixin
from .client_combat import CombatMixin
from .client_files import FileTransferMixin
from .client_gmap import GmapMixin
from .client_movement import MovementMixin
from .client_warp import WarpMixin


class Client(MovementMixin, CombatMixin, AppearanceMixin, ActionsMixin, WarpMixin,
             FileTransferMixin, GmapMixin):
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

    # (x, y, direction) of the last position we actually transmitted, or None
    # before the first one. See _note_position_sent.
    _last_sent_position = None

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
        self.persist_downloads = True

        # Grouped state (see client_state.py). Every field on these components
        # is also reachable under its historical flat name on the client
        # itself - _STATE_ALIASES at the bottom of this module installs the
        # delegating properties.
        self.session = SessionState(version)
        self.level_state = LevelState()
        self.gmap_state = GmapState()
        self.warp_state = WarpState()
        self.entities = EntityState()
        self.combat_state = CombatState()
        self.file_transfers = FileTransfers()
        self.scripts = ScriptTransport()
        self.callbacks = Callbacks()
        self.instrumentation = Instrumentation(HANDLED_PLO_IDS)

        # Use WebSocketProtocol in browser, regular Protocol otherwise
        if IS_BROWSER:
            if not proxy_url:
                raise ValueError("proxy_url is required when running in browser")
            self._protocol = WebSocketProtocol(proxy_url, host, port, version)
        else:
            self._protocol = Protocol(host, port, version)

        self.player = Player()
        self._login_appearance_applied = False

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
        self._login_appearance_applied = False
        self._reset_file_transfer_state()
        if self.input_frozen:
            self.input_frozen = False
            if self.on_fullstop:
                self.on_fullstop(False)
        return self._protocol.connect()

    def _reset_file_transfer_state(self, full_reset: bool = True) -> None:
        """Clear active download state and, for a new session, retry history."""
        self._large_file_transfers.clear()
        if full_reset:
            self._pending_files.clear()
            self._failed_files.clear()
            self._file_attempts.clear()
            self._cache_index = None

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
        real segments stitch together with their neighbors and span past 64.
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
    # Update Loop
    # =========================================================================

    def update(self, timeout: float = 0.01) -> List[Tuple[int, bytes]]:
        """
        Read incoming packets. Call this regularly (e.g., in game loop).

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
        """Handle a received packet.

        One table lookup into handlers.PACKET_HANDLERS (`@handles(<id>)` on a
        function in pyreborn/handlers/), then the caller's own on_packet hook.
        A handler returning handlers.STOP consumes the packet outright and
        suppresses that hook.
        """
        login_appearance = None
        if packet_id == PacketID.PLO_PLAYERPROPS and not self._authenticated:
            # The handler performs the authoritative parse and records any
            # width fallback/error diagnostics; this look-ahead is only for
            # deciding which appearance fields the server supplied.
            login_appearance = parse_player_props(data, self._colors_len)
        handler = PACKET_HANDLERS.get(packet_id)
        if handler is not None and handler(self, data) is STOP:
            return
        if login_appearance is not None and self._authenticated:
            self._apply_login_appearance(login_appearance)

        # Custom handler
        if packet_id in self.on_packet:
            self.on_packet[packet_id](data)

    def get_tile(self, x: int, y: int) -> int:
        """Get tile ID at position (0-63, 0-63). Returns 0 if out of bounds."""
        if not self.tiles or not in_level_bounds(x, y):
            return 0
        return self.tiles[level_index(x, y)]

    def _apply_board_modify(self, level_name: str, info: dict) -> None:
        """Patch a PLO_BOARDMODIFY/BOARDMODIFY2 tile delta into cached board
        data (self.levels[level_name] and, if it is the active level,
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
                if ty < 0 or ty >= LEVEL_SIZE:
                    i += w
                    continue
                for col in range(w):
                    tx = x + col
                    if 0 <= tx < LEVEL_SIZE:
                        board[level_index(tx, ty)] = tiles[i]
                    i += 1

        board = self.levels.get(level_name)
        if board is not None and len(board) >= 4096:
            _patch(board)
        if level_name == self._tiles_level_name and self.tiles and len(self.tiles) >= 4096:
            _patch(self.tiles)

    def get_current_level_from_position(self) -> str:
        """
        Get the GMAP level the player is in based on position.
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

        # Player coords are GMAP-relative, so the grid cell is simply their segment
        return self.gmap_grid.get(segment_at(self.player.x, self.player.y),
                                  self._current_level_name)

    def get_chest_opened(self, level_name: str, x: int, y: int) -> bool:
        """Return True if the chest at local coordinates is open."""
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

    def items_in_level(self, level_name: str) -> Dict[Tuple[float, float], str]:
        """Return ground items for one level, or an empty mapping."""
        # Accept the former flat shape when lightweight callers replace this
        # attribute directly; live client state always uses the nested shape.
        if self.items and all(isinstance(key, tuple) for key in self.items):
            return self.items  # type: ignore[return-value]
        return self.items.get(level_name, {})

    def baddies_in_level(self, level_name: str) -> Dict[int, dict]:
        """Return baddies for one level, or an empty mapping."""
        # Accept the former flat shape when lightweight callers replace this
        # attribute directly; live client state always uses the nested shape.
        if self.baddies and all(isinstance(key, int) for key in self.baddies):
            return self.baddies  # type: ignore[return-value]
        return self.baddies.get(level_name, {})

    def horses_in_level(
            self, level_name: str) -> Dict[Tuple[float, float], dict]:
        """Return horses for one level, or an empty mapping."""
        # Accept the former flat shape when lightweight callers replace this
        # attribute directly; live client state always uses the nested shape.
        if self.horses and all(isinstance(key, tuple) for key in self.horses):
            return self.horses  # type: ignore[return-value]
        return self.horses.get(level_name, {})

    def find_baddy(self, baddy_id: int) -> Optional[Tuple[str, dict]]:
        """Return the owning level and baddy for an existing id, if any."""
        if self.baddies and all(isinstance(key, int) for key in self.baddies):
            baddy = self.baddies.get(baddy_id)
            return (self._current_level_name, baddy) if baddy is not None else None
        for level_name, baddies in self.baddies.items():
            if baddy_id in baddies:
                return level_name, baddies[baddy_id]
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
# State-component aliases
#
# Client attribute name -> (component attribute on Client, field on it). The
# state lives on the components in client_state.py; each entry below installs
# a get/set property so every historical flat name still works - the pygame
# game/ layer, game_tester and ~50 test modules read and write these directly.
# Adding state means adding it to a component AND listing it here.
# =============================================================================

_STATE_ALIASES: Dict[str, Tuple[str, str]] = {
    # --- session / handshake ------------------------------------------------
    '_colors_len': ('session', 'colors_len'),
    '_file_no_modtime': ('session', 'file_no_modtime'),
    '_use_pixel_props': ('session', 'use_pixel_props'),
    '_authenticated': ('session', 'authenticated'),
    '_login_time': ('session', 'login_time'),
    '_raw_data_expected': ('session', 'raw_data_expected'),
    '_in_update': ('session', 'in_update'),
    'server_time': ('session', 'server_time'),
    'ghost_mode': ('session', 'ghost_mode'),
    'ghost_icon': ('session', 'ghost_icon'),
    'frozen': ('session', 'frozen'),
    'input_frozen': ('session', 'input_frozen'),
    'classic_mode_disabled': ('session', 'classic_mode_disabled'),
    'npcs_hidden': ('session', 'npcs_hidden'),
    'login_complete': ('session', 'login_complete'),
    'server_warp_info': ('session', 'server_warp_info'),
    'profiles': ('session', 'profiles'),
    'npcserver_addr': ('session', 'npcserver_addr'),
    'net_cookie': ('session', 'net_cookie'),
    'global_flags': ('session', 'global_flags'),
    'staff_guilds': ('session', 'staff_guilds'),
    'status_list': ('session', 'status_list'),
    'server_message': ('session', 'server_message'),
    'server_text': ('session', 'server_text'),
    'has_npc_server': ('session', 'has_npc_server'),
    'rpg_window_lines': ('session', 'rpg_window_lines'),
    'default_weapon': ('session', 'default_weapon'),
    'server_signature': ('session', 'server_signature'),
    'disconnect_reason': ('session', 'disconnect_reason'),

    # --- level / board ------------------------------------------------------
    'tiles': ('level_state', 'tiles'),
    '_tiles_level_name': ('level_state', 'tiles_level_name'),
    'levels': ('level_state', 'levels'),
    '_current_level_name': ('level_state', 'current_level_name'),
    '_pending_level_name': ('level_state', 'pending_level_name'),
    'active_level': ('level_state', 'active_level'),
    'level_modtimes': ('level_state', 'level_modtimes'),
    'links': ('level_state', 'links'),
    'chests': ('level_state', 'chests'),
    'chest_items': ('level_state', 'chest_items'),
    'chest_signs': ('level_state', 'chest_signs'),
    'signs': ('level_state', 'signs'),
    'sign_lists': ('level_state', 'sign_lists'),
    'board_layers': ('level_state', 'board_layers'),
    'board_heights': ('level_state', 'board_heights'),
    'is_leader': ('level_state', 'is_leader'),

    # --- gmap world --------------------------------------------------------
    'gmap_grid': ('gmap_state', 'gmap_grid'),
    'gmap_width': ('gmap_state', 'gmap_width'),
    'gmap_height': ('gmap_state', 'gmap_height'),
    'gmap_name': ('gmap_state', 'gmap_name'),
    '_requested_gmap': ('gmap_state', 'requested_gmap'),
    'bigmap_info': ('gmap_state', 'bigmap_info'),
    '_gmap_spawn_x': ('gmap_state', 'gmap_spawn_x'),
    '_gmap_spawn_y': ('gmap_state', 'gmap_spawn_y'),
    '_gmap_offset_x': ('gmap_state', 'gmap_offset_x'),
    '_gmap_offset_y': ('gmap_state', 'gmap_offset_y'),
    '_known_gmap_segments': ('gmap_state', 'known_gmap_segments'),
    '_warp_echo': ('warp_state', 'warp_echo'),
    '_last_gmap_name': ('gmap_state', 'last_gmap_name'),

    # --- in-flight warp / transition ---------------------------------------
    '_awaiting_warp_confirm': ('warp_state', 'awaiting_warp_confirm'),
    '_warp_fallback': ('warp_state', 'warp_fallback'),
    '_local_level_transition': ('warp_state', 'local_level_transition'),
    '_local_level_transition_epoch': ('warp_state', 'local_level_transition_epoch'),
    '_local_level_transition_started': ('warp_state', 'local_level_transition_started'),
    '_local_level_transition_direction': ('warp_state', 'local_level_transition_direction'),
    '_plain_level_change_epoch': ('warp_state', 'plain_level_change_epoch'),

    # --- entities ----------------------------------------------------------
    'npcs': ('entities', 'npcs'),
    '_npc_cache': ('entities', 'npc_cache'),
    '_npc_pos_epoch': ('entities', 'npc_pos_epoch'),
    'npc_moves': ('entities', 'npc_moves'),
    'players': ('entities', 'players'),
    'player_list': ('entities', 'player_list'),
    'all_players': ('entities', 'all_players'),
    'items': ('entities', 'items'),
    'baddies': ('entities', 'baddies'),
    'weapons': ('entities', 'weapons'),
    'bombs': ('entities', 'bombs'),
    'arrows': ('entities', 'arrows'),
    'horses': ('entities', 'horses'),
    'active_explosions': ('entities', 'active_explosions'),

    # --- combat ------------------------------------------------------------
    '_arrow_sims': ('combat_state', 'arrow_sims'),
    '_pending_arrow_hits': ('combat_state', 'pending_arrow_hits'),
    '_arrow_hurt_suppress': ('combat_state', 'arrow_hurt_suppress'),
    '_own_recent_arrows': ('combat_state', 'own_recent_arrows'),
    'auto_respond_hurt': ('combat_state', 'auto_respond_hurt'),
    'hurt_animation': ('combat_state', 'hurt_animation'),

    # --- file transfers ----------------------------------------------------
    '_pending_files': ('file_transfers', 'pending_files'),
    '_received_files': ('file_transfers', 'received_files'),
    '_failed_files': ('file_transfers', 'failed_files'),
    '_file_attempts': ('file_transfers', 'file_attempts'),
    '_uptodate_files': ('file_transfers', 'uptodate_files'),
    '_cache_index': ('file_transfers', 'cache_index'),
    '_large_file_transfers': ('file_transfers', 'large_file_transfers'),

    # --- script / bytecode transport ---------------------------------------
    'gs1_host': ('scripts', 'gs1_host'),
    'gs2_host': ('scripts', 'gs2_host'),
    'gs2_bytecode': ('scripts', 'gs2_bytecode'),
    'gs2_script_headers': ('scripts', 'gs2_script_headers'),
    'gani_setbackto': ('scripts', 'gani_setbackto'),
    '_gs2_requested': ('scripts', 'gs2_requested'),

    # --- instrumentation ---------------------------------------------------
    'packet_stats': ('instrumentation', 'packet_stats'),
    '_warned_packet_errors': ('instrumentation', 'warned_packet_errors'),
    '_handled_plo_ids': ('instrumentation', 'handled_plo_ids'),
    'prop_parse_diagnostics': ('instrumentation', 'prop_parse_diagnostics'),

    # --- callbacks ---------------------------------------------------------
    'on_packet': ('callbacks', 'on_packet'),
    'on_chat': ('callbacks', 'on_chat'),
    'on_level': ('callbacks', 'on_level'),
    'on_hurt': ('callbacks', 'on_hurt'),
    'on_item': ('callbacks', 'on_item'),
    'on_pm': ('callbacks', 'on_pm'),
    'on_add_player': ('callbacks', 'on_add_player'),
    'on_del_player': ('callbacks', 'on_del_player'),
    'on_baddy': ('callbacks', 'on_baddy'),
    'on_weapon_add': ('callbacks', 'on_weapon_add'),
    'on_projectile': ('callbacks', 'on_projectile'),
    'on_file': ('callbacks', 'on_file'),
    'on_file_send_failed': ('callbacks', 'on_file_send_failed'),
    'on_sign': ('callbacks', 'on_sign'),
    'on_explosion': ('callbacks', 'on_explosion'),
    'on_hit_objects': ('callbacks', 'on_hit_objects'),
    'on_minimap': ('callbacks', 'on_minimap'),
    'on_board_layer': ('callbacks', 'on_board_layer'),
    'on_ghost_mode': ('callbacks', 'on_ghost_mode'),
    'on_start_message': ('callbacks', 'on_start_message'),
    'on_board_modify': ('callbacks', 'on_board_modify'),
    'on_file_uptodate': ('callbacks', 'on_file_uptodate'),
    'on_bomb_add': ('callbacks', 'on_bomb_add'),
    'on_bomb_del': ('callbacks', 'on_bomb_del'),
    'on_arrow_add': ('callbacks', 'on_arrow_add'),
    'on_horse_add': ('callbacks', 'on_horse_add'),
    'on_horse_del': ('callbacks', 'on_horse_del'),
    'on_firespy': ('callbacks', 'on_firespy'),
    'on_throwcarried': ('callbacks', 'on_throwcarried'),
    'on_pushaway': ('callbacks', 'on_pushaway'),
    'on_npc_moved': ('callbacks', 'on_npc_moved'),
    'on_npc_move': ('callbacks', 'on_npc_move'),
    'on_npc_del': ('callbacks', 'on_npc_del'),
    'on_sword_hit_npc': ('callbacks', 'on_sword_hit_npc'),
    'on_freeze': ('callbacks', 'on_freeze'),
    'on_fullstop': ('callbacks', 'on_fullstop'),
    'on_say2': ('callbacks', 'on_say2'),
    'on_player_left': ('callbacks', 'on_player_left'),
    'on_server_warp': ('callbacks', 'on_server_warp'),
    'on_triggeraction': ('callbacks', 'on_triggeraction'),
    'on_profile': ('callbacks', 'on_profile'),
    'on_hide_npcs': ('callbacks', 'on_hide_npcs'),
    'on_login_complete': ('callbacks', 'on_login_complete'),
    'on_chest': ('callbacks', 'on_chest'),
    'on_disconnect': ('callbacks', 'on_disconnect'),
    'on_gs2_bytecode': ('callbacks', 'on_gs2_bytecode'),
    'on_server_text': ('callbacks', 'on_server_text'),
    'on_rpg_window': ('callbacks', 'on_rpg_window'),
    'on_baddy_hurt': ('callbacks', 'on_baddy_hurt'),
    'on_flag': ('callbacks', 'on_flag'),
    'on_flag_del': ('callbacks', 'on_flag_del'),
}


def _state_alias(component: str, field: str) -> property:
    """Build the Client property that reads/writes component.field."""

    def getter(self):
        return getattr(getattr(self, component), field)

    def setter(self, value):
        setattr(getattr(self, component), field, value)

    return property(getter, setter,
                    doc="Alias of self.%s.%s (see client_state.%s)."
                        % (component, field, component))


for _alias_name, (_alias_component, _alias_field) in _STATE_ALIASES.items():
    if hasattr(Client, _alias_name):
        raise RuntimeError(
            "state alias %r would shadow an existing Client attribute"
            % _alias_name)
    setattr(Client, _alias_name, _state_alias(_alias_component, _alias_field))


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
