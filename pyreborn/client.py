"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import logging
import traceback
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_LARGE_FILE_SIZE = 256 * 1024 * 1024
LARGE_FILE_SIZE_SLACK = 64 * 1024

from reborn_protocol.coords import (
    LEVEL_SIZE, in_level_bounds, level_index,
)

from .clock import Clock
from .protocol import Protocol, WebSocketProtocol, IS_BROWSER
from .player import Player
from .gmap_coords import get_ci, in_grid, level_at, same_level
# BoundedLRU / MAX_CACHED_* keep their old client.py names for callers and
# tests that reach for them there (tests/unit/test_security_correctness.py).
from .client_state import (  # noqa: F401  (BoundedLRU/MAX_CACHED_* re-exported)
    BoundedLRU,
    MAX_CACHED_FILES,
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
    derive_state_aliases,
)
from .packets import PacketID
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
from .client_callbacks import CallbackMixin, emit
from .client_combat import CombatMixin
from .client_files import FileTransferMixin
from .client_gmap import GmapMixin
from .client_movement import MovementMixin
from .client_warp import WarpMixin


class Client(CallbackMixin, MovementMixin, CombatMixin, AppearanceMixin, ActionsMixin, WarpMixin,
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
                 proxy_url: Optional[str] = None,
                 source_address: Optional[str] = None):
        """
        Create a new client.

        Args:
            host: Server hostname or IP
            port: Server port (default 14900)
            version: Protocol version ("2.22" or "6.037")
            proxy_url: WebSocket proxy URL for browser (e.g., "ws://localhost:14901")
                       Required when running in browser, ignored otherwise.
            source_address: Local IP to bind before connecting (native sockets only).
        """
        self.host = host
        self.port = port
        self.version = version
        self.proxy_url = proxy_url
        self.persist_downloads = True
        # The one clock of this client and of any GameClient built over it.
        self.clock = Clock()

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
        self._init_callback_listeners()
        self.instrumentation = Instrumentation(HANDLED_PLO_IDS)
        self.entities.item_clock = self.clock.sim_now

        # Use WebSocketProtocol in browser, regular Protocol otherwise
        if IS_BROWSER:
            if not proxy_url:
                raise ValueError("proxy_url is required when running in browser")
            self._protocol = WebSocketProtocol(proxy_url, host, port, version)
        else:
            self._protocol = Protocol(host, port, version, source_address=source_address)

        # A dropped socket (EOF, send/recv error) reaches the app through
        # on_disconnect exactly once per session; see _notify_disconnect.
        self._socket_dropped = False
        self._logging_in = False
        self._disconnect_notified = False
        self._protocol.on_disconnect = self._on_protocol_disconnect

        self.player = Player(clock=self.clock)
        self._login_appearance_applied = False
        self._last_self_props = None

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
        # TServerList.cpp:333 -> TTiles.cpp:285-287 clears server tiledefs.
        self.level_state.tiletypes.reset_tiledefs()
        self._authenticated = False
        self._socket_dropped = False
        self._disconnect_notified = False
        self._login_appearance_applied = False
        self._reset_file_transfer_state()
        # Server mode and COLORS-width evidence describe ONE server session
        # (the mode is read once at server start, GServer-v2 Server.cpp:
        # 188-193); a reused Client must not carry them to the next one.
        # TClient.cpp:5638-5639: a new session also clears the pending
        # serverwarp target and the sent-destination memory.
        self.session.reset(
            'server_mode', 'classic_mode_disabled', 'server_warp_info',
            'last_server_warp', 'last_server_warp_at',
            'server_warp_declined_until', 'server_warp_offers',
            'server_warp_notice_at')
        self._clear_hide_player()
        self._last_self_props = None
        # The visited-level store describes ONE session: the new server has
        # no record of what we hold, so a stale mod time would make it send
        # nothing for a level it never streamed.
        self.levels.clear()
        self.level_modtimes.clear()
        self.level_state.streaming_level_name = ""
        self.level_state.level_layers.clear()
        self._npc_cache.clear()
        # a new session must not age (or delete) old items
        self.entities.reset('items', 'item_stamps')
        self.instrumentation.reset('prop_parse_diagnostics')
        if self.gs2_host is not None:
            self.gs2_host.reset_session()
        if self.input_frozen:
            self.input_frozen = False
            emit(self, 'on_fullstop', False)
        return self._protocol.connect()

    def _reset_file_transfer_state(self, full_reset: bool = True) -> None:
        """Clear active download state and, for a new session, retry history."""
        self._large_file_transfers.clear()
        if full_reset:
            self._pending_files.clear()
            self._failed_files.clear()
            self._file_attempts.clear()
            self._cache_index = None
            self._update_packages.clear()
            self._requested_files.clear()

    def disconnect(self):
        """Disconnect from the server."""
        if self.gs2_host is not None:
            self.gs2_host.reset_session()
        self._clear_hide_player(notify=True)
        # An explicit disconnect never fires on_disconnect (that hook reports
        # the server or the network ending the session), and a later socket
        # event from the closing transport must stay silent too.
        self._disconnect_notified = True
        self._socket_dropped = False
        self._protocol.disconnect()
        self._authenticated = False

    def _on_protocol_disconnect(self) -> None:
        """Protocol callback: the socket dropped under us. Only flags it; the
        notification waits for the end of update(), after the final received
        bundle (possibly a PLO_DISCMESSAGE with the reason) was dispatched."""
        self._socket_dropped = True

    def _notify_disconnect(self, reason: str) -> None:
        """Fire on_disconnect(reason) at most once per session."""
        if self._disconnect_notified:
            return
        self._disconnect_notified = True
        emit(self, 'on_disconnect', reason)

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
                in_grid(self.gmap_grid, self._current_level_name))

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

        # A drop during login belongs to the failed login, not to an
        # established session: hold the drop notification while we wait, and
        # discard it if the login fails.
        self._logging_in = True
        ok = False
        try:
            ok = self._login_wait(username, password, timeout)
        finally:
            self._logging_in = False
            if not ok:
                self._socket_dropped = False
                if not self.connected:
                    self._disconnect_notified = True
        return ok

    def _login_wait(self, username: str, password: str, timeout: float) -> bool:
        # Send login packet
        if not self._protocol.send_login(username, password):
            return False

        self.player.account = username
        self._login_time = self.clock.frame_now()
        self.disconnect_reason = ""

        # Wait for authentication response
        start = self.clock.frame_now()
        while self.clock.frame_now() - start < timeout:
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
        Read incoming packets, and run the simulation ticks that are due.

        Packets are applied as they arrive. The library's own simulations
        (NPC movement, item expiry, sword/arrow/bomb ticks, ...) run in fixed
        ticks (`run_tick`, pyreborn/clock.py). Without a host driving the
        ticks, this call runs the ticks the frame time since the previous call
        makes due, with the same policy a GameClient frame uses: at most
        `Clock.MAX_TICKS_PER_FRAME`, the rest dropped. A long `timeout` is
        waited out in slices that end on tick boundaries, so a bot that waits
        in update() keeps its simulation at real speed. When a host
        (GameClient) drives the ticks, update() only handles packets.

        Args:
            timeout: How long to wait for packets (seconds)

        Returns:
            List of (packet_id, data) tuples received
        """
        clock = self.clock
        if clock.host_driven or clock._in_tick or getattr(self, '_in_update', False):
            return self._receive(timeout)
        self.run_due_ticks(clock.pump_headless())
        deadline = clock.frame_now() + max(0.0, timeout)
        received: List[Tuple[int, bytes]] = []
        while True:
            before = clock.frame_now()
            wait = min(max(0.0, deadline - before),
                       clock.time_to_next_tick())
            packets = self._receive(wait)
            received.extend(packets)
            self.run_due_ticks(clock.pump_headless())
            after = clock.frame_now()
            # A time source that did not move during the wait (a stub
            # transport, a frozen test clock) would never reach the deadline.
            if (packets or not self.connected or after >= deadline
                    or after <= before):
                return received

    def run_due_ticks(self, count: int) -> None:
        """Run `count` simulation ticks (begin_tick + run_tick each)."""
        clock = self.clock
        for _ in range(count):
            clock.begin_tick()
            clock._in_tick = True
            try:
                self.run_tick()
            finally:
                clock._in_tick = False

    def run_tick(self) -> None:
        """One simulation tick of the library's own simulations.

        The reference runs these once per 50 ms timer call (TAdventure.cpp:
        471-496, TServerLevel.cpp:1212-1224). The clock's tick has already
        advanced (`Clock.begin_tick`), so everything here reads the new
        `sim_now()`. A GameClient calls this from its own tick; a headless
        client gets it from update()."""
        from .npc_movement import tick_moves
        tick_moves(self)
        self.expire_items()
        self._tick_sword_attack()
        self._tick_arrow_sims()
        self._tick_bomb_sims()
        if self.hide_player_until:
            self._tick_hide_player()
        self._expire_explosions()
        self.player.tick_emoticon()

    def _receive(self, timeout: float) -> List[Tuple[int, bytes]]:
        """Wait up to `timeout` for packets and dispatch them; no ticks."""
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

        if self._socket_dropped and not self._logging_in:
            self._socket_dropped = False
            try:
                self._notify_disconnect(
                    self.disconnect_reason or "Connection lost")
            except Exception:
                logger.exception("on_disconnect callback raised")

        # A stalled download is a real-time wait, not simulation: checked on
        # every receive, against frame time.
        if self._update_packages:
            from .update_packages import expire_stalled
            expire_stalled(self)

        return packets

    def _handle_packet(self, packet_id: int, data: bytes):
        """Handle a received packet.

        One table lookup into handlers.PACKET_HANDLERS (`@handles(<id>)` on a
        function in pyreborn/handlers/), then the caller's own on_packet hook.
        A handler returning handlers.STOP consumes the packet outright and
        suppresses that hook.
        """
        # The first self-props packet decides which appearance fields the
        # server supplied. Read them from the handler's own parse
        # (handlers/entities.py handle_player_props) rather than parsing
        # again: a second parse could settle an ambiguous COLORS width
        # differently and would double-count the width evidence.
        login_pending = (packet_id == PacketID.PLO_PLAYERPROPS
                         and not self._authenticated)
        if login_pending:
            self._last_self_props = None
        handler = PACKET_HANDLERS.get(packet_id)
        if handler is not None and handler(self, data) is STOP:
            return
        if (login_pending and self._authenticated
                and self._last_self_props is not None):
            self._apply_login_appearance(self._last_self_props)

        # Listeners (library/game subscribers), then the embedder's own hook.
        for listener in vars(self).get('_packet_listeners', {}).get(packet_id, ()):
            listener(data)
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

        board = get_ci(self.levels, level_name)
        if board is not None and len(board) >= 4096:
            _patch(board)
        if same_level(level_name, self._tiles_level_name) and self.tiles and len(self.tiles) >= 4096:
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
            in_grid(self.gmap_grid, self._current_level_name)
            or bool(self.gmap_name and self._current_level_name == self.gmap_name)
        )
        if not self.gmap_grid or not current_is_gmap:
            return self._current_level_name

        # Player coords are GMAP-relative, so the grid cell is simply their segment
        return (level_at(self.gmap_grid, self.player.x, self.player.y)
                or self._current_level_name)

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

    def expire_items(self, now: Optional[float] = None) -> List[Tuple[str, float, float, str]]:
        """Drop ground items whose lifetime ran out; return what was dropped.

        The reference server removes an item after its lifetime without telling
        anyone (Level.cpp:711-716), so each client ages its own copy and removes
        it (reference client TServerLevel.cpp:1400-1470, animateExtras). An item
        the model holds with no start stamp (a GS1 or local drop) starts now.

        Like that client, each timer-expired item also goes out as PLI_ITEMDEL
        (reference client TServerLevel.cpp:1468-1469: `time < 0` calls
        sendRemoveExtra, packet shape as the pickup). Only the timer path
        sends: pickup and PLO_ITEMDEL removals never reach this function, and
        the reference only walks the level the player is in, so buckets of any
        other level are pruned silently.
        """
        from . import ground_items
        expired = ground_items.expire_items(
            self, self.item_clock() if now is None else now)
        if expired and self.connected:
            for level_name, x, y, _item_type in expired:
                if level_name == self._current_level_name:
                    self.send_item_del(x, y)
        return expired

    def remove_item_local(self, level_name: str, x: float, y: float) -> Optional[str]:
        """Forget one ground item and its expiry stamp; return its type or None.

        The one removal path for every way an item leaves the model: the
        player's own take, a GS1 `take`, a server PLO_ITEMDEL, the timer. Fires
        `on_item(x, y, type, False)` only when an item was actually there, so
        a later echo for the same spot is a no-op and never calls back twice.
        """
        key = (x, y)
        self.item_stamps.pop((level_name, key), None)
        bucket = self.items.get(level_name)
        item_type = bucket.pop(key, None) if isinstance(bucket, dict) else None
        if item_type is not None:
            emit(self, 'on_item', x, y, item_type, False)
        return item_type

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

    def bombs_in_level(
            self, level_name: str) -> Dict[int, dict]:
        """Return placement-id -> bomb for one level, in placement order."""
        return self.bombs.get(level_name, {})

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
# The state lives on the components in client_state.py. Each declared field
# there becomes a get/set property on Client under its historical flat name
# (the pygame game/ layer, game_tester and ~50 test modules read and write
# these directly). The mapping is derived from the components' declared fields
# (client_state.derive_state_aliases), so adding state is ONE edit: declare the
# field in the component's constructor. The only explicit entries are the
# per-component ALIAS_PRIVATE sets (flat name = "_" + field), ALIAS_PROPERTIES
# and NO_ALIAS knobs in client_state.py.
# =============================================================================

_STATE_ALIASES: Dict[str, Tuple[str, str]] = derive_state_aliases()


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


# Public names for the state the game layer reads. The flat names above that
# carry a leading underscore are historical; the game layer uses these.
_PUBLIC_STATE_ALIASES = (
    'current_level_name', 'pending_level_name', 'board_layers_level_name',
    'local_level_transition', 'local_level_transition_epoch',
    'local_level_transition_started', 'local_level_transition_direction',
    'plain_level_change_epoch', 'gmap_offset_x', 'gmap_offset_y',
)

for _public_name in _PUBLIC_STATE_ALIASES:
    _component, _field = _STATE_ALIASES['_' + _public_name]
    if hasattr(Client, _public_name):
        raise RuntimeError(
            "public state alias %r would shadow an existing Client attribute"
            % _public_name)
    setattr(Client, _public_name, _state_alias(_component, _field))


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
