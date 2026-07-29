"""
pyreborn - Client
Simple, synchronous client for Reborn servers.

Supports both TCP (native Python) and WebSocket (browser via Pyodide).
In browser, use proxy_url parameter to connect via WebSocket proxy.
"""

import json
import logging
import math
import os
import re
import tempfile
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

# LEVELWARP encodes coords as gchar half-tiles: byte = int(coord*2)+32, which
# must stay in [0, 255]. That bounds the warp target to [-16, 111.5] tiles.
WARP_COORD_MIN = -16.0
WARP_COORD_MAX = 111.5
MAX_LARGE_FILE_SIZE = 256 * 1024 * 1024
LARGE_FILE_SIZE_SLACK = 64 * 1024

from reborn_protocol import BDPROP, BDMODE
from reborn_protocol.props import PLAYER_PROPS, encode_value
from reborn_protocol.coords import (
    LEVEL_SIZE, in_level_bounds, level_index, local_coord, local_to_world,
    segment_at, segment_origin, world_to_local,
)

from .protocol import Protocol, WebSocketProtocol, IS_BROWSER
from .player import Player
from .asset_paths import normalize_asset_name, server_cache_dir
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
from .game.constants import (
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
    PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y,
)
from .packets import (
    PacketID,
    PacketBuilder,
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
    build_weapon_add,
    build_npc_props,
    build_flag_set,
    build_flag_del,
    build_level_warp,
    build_private_message,
    build_baddy_hurt,
    build_baddy_add,
    build_putnpc,
    build_open_chest,
    build_horse_add,
    build_baddy_props,
    build_wantfile,
    build_board_modify,
    build_update_file,
    build_bomb_add,
    build_bomb_del,
    build_explosion_add,
    build_item_add,
    build_arrow_add,
    build_horse_del,
    build_firespy,
    build_throwcarried,
    build_profile_get,
    build_profile_set,
    build_update_script,
    build_update_gani,
    build_update_class,
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
        self._large_file_pending = None
        self._large_file_discarding = None
        self._large_file_buffer = bytearray()
        self._large_file_expected_size = 0
        self._large_file_modtime = 0
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
            new_grid = segment_at(new_x, new_y)

            # If we're changing grid cells, we need to notify the server
            if new_grid != segment_at(self.player.x, self.player.y):
                # Look up the new level name from the GMAP grid
                new_level = self.gmap_grid.get(new_grid)
                if new_level:
                    new_level_name = new_level
                    crossing_boundary = True

        # Build and send movement packet
        # Always send LOCAL coordinates (0-63) - server tracks level separately
        local_x, local_y = world_to_local(new_x, new_y)
        # v2.30+/v6 clients report position via the high-precision X2/Y2
        # props (78/79); classic servers only understand X/Y (15/16).
        data = build_movement(local_x, local_y, direction,
                              use_new_format=self._use_pixel_props)
        if self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            # Update local state
            self.player.x = new_x
            self.player.y = new_y
            self.player.direction = direction
            self._note_position_sent()

            # If crossing GMAP boundary, send a level warp to notify server
            if crossing_boundary and new_level_name:
                self.enter_gmap_segment(new_level_name, local_x, local_y)

            return True

        return False

    def enter_gmap_segment(self, level_name: str, local_x: float,
                           local_y: float) -> bool:
        """Tell the server we walked into gmap segment `level_name`.

        A seam crossing is NOT a warp: no level-state reset, no roster drop —
        just PLI_LEVELWARP so the server re-homes us, plus a request for the
        newly-adjacent segments. Factored out of move_to() so scripted
        movement (which never calls move_to; see
        ActionsMixin._check_scripted_gmap_segment) announces crossings the
        exact same way."""
        if not self.connected or not self._authenticated:
            return False
        warp_data = build_level_warp(local_x, local_y, level_name)
        if not self._protocol.send_packet(PacketID.PLI_LEVELWARP, warp_data):
            return False
        self._current_level_name = level_name
        # Point the ACTIVE board at the segment we just walked into. The
        # neighbour's board is already in self.levels (preloaded by
        # request_adjacent_levels on an earlier crossing), and gs2emu will not
        # re-stream it - its per-session level cache only sends a board the
        # first time - so nothing else ever updates _tiles_level_name for a
        # re-crossing. Live-traced on hastur 2026-07-25: walking e6 -> d6 left
        # the active board naming e6 for the remaining 2.4 s of the session.
        cached_board = self.levels.get(level_name)
        if cached_board:
            self.tiles = cached_board
            self._tiles_level_name = level_name
        self.note_client_warp(level_name)
        self.request_adjacent_levels()
        return True

    def send_position(self) -> bool:
        """Re-broadcast the player's current position without moving.

        The server only tells other players our position when it changes, so a
        stationary player is invisible (position-wise) to anyone who joins after
        us. Calling this pushes our current X/Y so others can place us. Useful
        for tests and for an initial position announce after entering a level.
        """
        if not self.connected or not self._authenticated:
            return False
        local_x, local_y = world_to_local(self.player.x, self.player.y)
        data = build_movement(local_x, local_y, self.player.direction,
                              use_new_format=self._use_pixel_props)
        if not self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            return False
        self._note_position_sent()
        return True

    # -- last-transmitted position -----------------------------------------
    #
    # Every path that puts our position on the wire records it here, so
    # script-driven movement can tell whether the server has actually been
    # told where we are (see gs2_client._sync_script_position). Rounded to
    # the wire's own precision would still leave a stale-by-a-hair snapshot
    # re-sending forever, so this is the exact value the sender used.
    def _note_position_sent(self) -> None:
        self._last_sent_position = (round(float(self.player.x), 4),
                                    round(float(self.player.y), 4),
                                    int(self.player.direction or 0))

    @property
    def position_matches_wire(self) -> bool:
        """True when player.x/y/direction are what we last told the server."""
        last = getattr(self, '_last_sent_position', None)
        return last == (round(float(self.player.x), 4),
                        round(float(self.player.y), 4),
                        int(self.player.direction or 0))

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

    def _send_appearance_prop(self, prop_id: int, value) -> bool:
        """Send one appearance property through the normal player-props path."""
        if not self.connected or not self._authenticated:
            return False
        payload = bytes([prop_id + 32]) + encode_value(
            PLAYER_PROPS[prop_id], value, colors_len=self._colors_len)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, payload)

    @staticmethod
    def _remember_appearance(**fields) -> None:
        try:
            from .prefs import Prefs
            Prefs.load().remember_appearance(**fields)
        except OSError:
            pass

    def send_head_image(self, head_image=None) -> bool:
        """Set and send PLPROP_HEADIMAGE (a preset int or custom filename)."""
        value = self.player.head_image if head_image is None else head_image
        sent = self._send_appearance_prop(11, value)
        if sent:
            self.player.head_image = (
                f"head{value}.png" if isinstance(value, int) else str(value))
            self._remember_appearance(head=self.player.head_image)
        return sent

    def send_body_image(self, body_image=None) -> bool:
        """Set and send PLPROP_BODYIMAGE."""
        value = self.player.body_image if body_image is None else str(body_image)
        sent = self._send_appearance_prop(35, value)
        if sent:
            self.player.body_image = value
            self._remember_appearance(body=value)
        return sent

    def send_colors(self, colors=None) -> bool:
        """Set and send PLPROP_COLORS using the negotiated server width."""
        value = list(self.player.colors if colors is None else colors)
        sent = self._send_appearance_prop(13, value)
        if sent:
            self.player.colors = value[:self._colors_len]
            self._remember_appearance(colors=self.player.colors)
        return sent

    def _apply_login_appearance(self, server_props: dict) -> None:
        """Restore saved look fields absent from the first server props packet."""
        if self._login_appearance_applied:
            return
        self._login_appearance_applied = True
        try:
            from .prefs import Prefs
            prefs = Prefs.load()
        except OSError:
            return

        server_values = {}
        if 'head_image' in server_props:
            server_values['head'] = self.player.head_image
        elif prefs.appearance_head is not None:
            self.send_head_image(prefs.appearance_head)
        if 'body_image' in server_props:
            server_values['body'] = self.player.body_image
        elif prefs.appearance_body is not None:
            self.send_body_image(prefs.appearance_body)
        if 'colors' in server_props:
            server_values['colors'] = self.player.colors
        elif prefs.appearance_colors is not None:
            self.send_colors(prefs.appearance_colors)
        if server_values:
            try:
                prefs.remember_appearance(**server_values)
            except OSError:
                pass

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
        local_x, local_y = world_to_local(self.player.x, self.player.y)
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
            probe_lx, probe_ly = world_to_local(self.player.x, self.player.y)
            probe_x = probe_lx + 1 + dir_vec[0] * 1.5
            probe_y = probe_ly + 1.5 + dir_vec[1] * 1.5
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
        seg_ox, seg_oy = segment_origin(
            *segment_at(self.player.x, self.player.y))
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
                seg_off_x, seg_off_y = segment_origin(*seg)
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
                    # PLO_BADDYHURT handler (handlers/combat.py).
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
        gs2 = getattr(self, "gs2_host", None)
        if gs2 is not None:
            gs2.note_gani(("local", getattr(self.player, "id", 0)), gani_name)
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
        local_x, local_y = world_to_local(self.player.x, self.player.y)
        # A GS1/GS2 script writing `playerdir` stores a FLOAT; the SPRITE
        # prop is a single byte (same int-coercion family as update()'s
        # movement props above) — uncoerced it crashed set_animation on Era
        # ("'float' object cannot be interpreted as an integer").
        data = build_animation(wire_name, local_x, local_y,
                               int(self.player.direction or 0) & 3)
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
        # on a GMAP (move()/sword_attack() already localize for this
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
            *world_to_local(self.player.x, self.player.y),
            self.player.direction,
            gani_name,
            use_new_format=self._use_pixel_props,
        )
        if not self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            return False
        self._note_position_sent()
        return True

    def send_hit_objects(self, power: float, x: float, y: float) -> bool:
        """Report a scripted hit probe (PLI_HITOBJECTS) at level-local
        (x, y) — the GS1 `hitobjects` wire half; the server runs its own hit
        detection there (fires serverside NPCs' washit). Same builder the
        sword swing uses."""
        if not self.connected or not self._authenticated:
            return False
        from .packets import build_hit_objects
        return self._protocol.send_packet(
            PacketID.PLI_HITOBJECTS, build_hit_objects(power, x, y))

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

    def send_weapon_add(self, npc_id: int) -> bool:
        """Ask the server to grant the weapon represented by a level NPC."""
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(
            PacketID.PLI_WEAPONADD, build_weapon_add(npc_id))

    def delete_npc(self, npc_id: int) -> bool:
        """Ask the server to delete a server-owned NPC."""
        if not self.connected or not self._authenticated or npc_id <= 0:
            return False
        data = PacketBuilder().write_gint3(npc_id).build()
        return self._protocol.send_packet(PacketID.PLI_NPCDEL, data)

    def send_putnpc(self, image: str, script_file: str, x: float, y: float) -> bool:
        """GS1 `putnpc image,scriptfile,x,y`: ask the server to create a level
        NPC from one of ITS script files (PLI_PUTNPC). The new NPC streams back
        to everyone in the level via normal NPC props - see build_putnpc for
        why the client must not also spawn a local copy. Gated server-side on
        `putnpcenabled` (GTA and the classic-gs1 reference configs enable it)."""
        if not self.connected or not self._authenticated:
            return False
        data = build_putnpc(image, script_file, x, y)
        return self._protocol.send_packet(PacketID.PLI_PUTNPC, data)

    def send_baddy_add(self, x: float, y: float, baddy_type: int,
                       power: int, image: str) -> bool:
        """GS1 `putcomp`/`putnewcomp`: ask the server to add a baddy
        (PLI_BADDYADD); it comes back via the level-wide PLO_BADDYPROPS
        broadcast. `power` is half-hearts."""
        if not self.connected or not self._authenticated:
            return False
        data = build_baddy_add(x, y, baddy_type, power, image)
        return self._protocol.send_packet(PacketID.PLI_BADDYADD, data)

    def kill_all_baddies(self) -> bool:
        """GS1 `removecompus`: there is no dedicated wire op for the classic
        client, but the leader-authoritative baddy channel (PLI_BADDYPROPS,
        the same one hit resolution uses - see _leader_broadcast_baddy_props)
        lets us mark every baddy dead: the server applies MODE=DEAD to its
        copy and relays it to the level (see build_baddy_props' wire-format
        citation). putcomp/BADDYADD baddies have
        respawn disabled server-side, so dead is gone; level-placed baddies
        follow their normal respawn timer. Local state is updated in the same
        step because the relay excludes the sender when we are the leader."""
        ok = True
        for baddy_id, baddy in list(self.baddies.items()):
            if isinstance(baddy, dict):
                baddy['mode'] = int(BDMODE.DEAD)
            if self.connected and self._authenticated:
                data = build_baddy_props(baddy_id,
                                         {BDPROP.MODE: int(BDMODE.DEAD)})
                ok = self._protocol.send_packet(PacketID.PLI_BADDYPROPS,
                                                data) and ok
        return ok

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
        elif self.gs2_host is not None:
            self.gs2_host.begin_level_visit()
        # Warping back out of an interior into a segment of a world we already
        # downloaded: rebuild the grid now, so the coordinate conversion below
        # lands in the world frame and the renderer never has to sit frozen
        # waiting for the server to re-announce the .gmap.
        self.restore_known_gmap(level_name)
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
                    self.player.x, self.player.y = local_to_world(x, y, gx, gy)
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
        self.note_client_warp(level_name)
        # Everything the renderer needs may already be in hand: a destination
        # we've visited this session had its board re-pointed synchronously
        # above. Offer the release now instead of waiting for the server's
        # announcement to call it - _maybe_release_local_transition's own
        # guards (active board, gmap frame) make this a no-op for a
        # first-visit level, and on a re-entry they turn a full round trip of
        # frozen frames (measured 180 ms on hastur, worse on a slow link) into
        # an immediate cut to a view we could already draw.
        self._maybe_release_local_transition()
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

    def warp_names_pending_destination(self, level: str) -> bool:
        """Does a server warp packet naming `level` refer to the destination
        of the warp we're waiting on?

        A server-side warp INTO a gmap is announced by the world's name
        (`zlttp.gmap`), never by the destination segment's file name — so
        a plain `level != _awaiting_warp_confirm` test reads the confirmation
        of a legitimate warp as a rejection. Live-traced on hastur
        2026-07-25: walking out of `zlttp-linkshouse.nw` produced
        `PLO_PLAYERWARP2 (5, 6) "zlttp.gmap"` against a pending
        `zlttp-linkshouse.nw`->`zlttp-d6.nw` warp, and the bogus rollback
        killed the transition hold that exists precisely to stop the camera
        rendering a gmap re-entry in the interim standalone frame.
        """
        pending = self._awaiting_warp_confirm
        if not pending or not level:
            return False
        if level == pending:
            return True
        # `.gmap` names the world; it confirms any destination known to be one
        # of that world's segments. _known_gmap_segments (not gmap_grid) is the
        # right table: the grid is cleared while we're inside the interior.
        return level.endswith('.gmap') and pending in self._known_gmap_segments

    def note_client_warp(self, level_name: str) -> None:
        """Record a level change WE told the server about (a seam crossing via
        `enter_gmap_segment`, or a door/script warp via `warp_to_level`).

        Both send PLI_LEVELWARP, and the server answers one round trip later
        with a PLO_PLAYERWARP/PLAYERWARP2 whose coordinates are the ones we
        sent, re-quantised to half-tiles by `build_level_warp` on the way out.
        The packet therefore carries no position the client doesn't already
        have — but it arrives after the player has kept walking, so adopting
        it rewinds them by walk_speed x RTT. Measured on hastur (180 ms base
        RTT): 1.8 tiles / 29 px at a gmap seam (5.1 tiles on a slower sample)
        and 3.3 tiles / 53 px walking out of a door. See
        handlers/level.handle_player_warp2.
        """
        self._warp_echo = (level_name, time.monotonic())

    #: How long a recorded client warp stays eligible to absorb the server's
    #: echo. Comfortably above any playable round trip, far below the interval
    #: at which a stale entry could shadow a genuine server reposition into
    #: the same level.
    WARP_ECHO_MAX_AGE_S = 5.0

    def consume_warp_echo(self, level: str,
                          grid_pos: Optional[Tuple[int, int]] = None) -> bool:
        """True if a server warp packet is the echo of the level change we
        announced (see `note_client_warp`), and so should not move the player.

        Matches on any of the three names the server may use for the same
        destination: the level itself, the grid cell it occupies, or the
        world (`.gmap`) it belongs to. Consumes the record either way once a
        name matches, so only the FIRST warp for a destination is absorbed —
        a genuine later reposition to the same level still teleports.
        """
        echo = self._warp_echo
        if not echo:
            return False
        target, sent_at = echo
        matched = (level == target
                   or (grid_pos is not None
                       and self.gmap_grid.get(grid_pos) == target)
                   or (level.endswith('.gmap')
                       and target in self._known_gmap_segments))
        if not matched:
            return False
        self._warp_echo = None
        return time.monotonic() - sent_at <= self.WARP_ECHO_MAX_AGE_S

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
        self._reset_file_transfer_state(full_reset=False)
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
                power: int = 1, timer_ms: int = 3050,
                consume_ammo: bool = True) -> bool:
        """Place a bomb (PLI_BOMBADD). timer_ms is total fuse time; the server
        expects 50ms increments already counted down by ~200ms client-side, so
        this converts it the same way (see build_bomb_add).

        Ammo is client-authoritative on GServer-v2 (PLI_BOMBADD only spawns
        the projectile; the server never touches the count), so this refuses
        to fire at 0 bombs, decrements locally, and reports the new
        BOMBSCOUNT. pygserver additionally decrements server-side and echoes
        the authoritative count via PLO_PLAYERPROPS - that echo is an absolute
        value equal to our prediction, so the two don't double-decrement.

        consume_ammo=False is the GS1 `putbomb` path: a script-spawned bomb
        is a free level projectile, not a shot from the player's bag."""
        if not self.connected or not self._authenticated:
            return False
        if consume_ammo and self.player.bombs <= 0:
            logger.debug("put_bomb: no bombs left, not firing")
            return False
        if x is None:
            x = self.player.x
        if y is None:
            y = self.player.y
        data = build_bomb_add(x, y, power, timer_ms)
        ok = self._protocol.send_packet(PacketID.PLI_BOMBADD, data)
        if ok and consume_ammo:
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

    def send_explosion(self, radius: int, x: float, y: float,
                       power: int = 1) -> bool:
        """Report a client-scripted explosion (PLI_EXPLOSION; GS1
        putexplosion/putexplosion2). Coordinates are localized to the current
        segment like every other GCHAR-position packet."""
        if not self.connected or not self._authenticated:
            return False
        data = build_explosion_add(radius, *world_to_local(x, y), power)
        return self._protocol.send_packet(PacketID.PLI_EXPLOSION, data)

    def send_item_add(self, x: float, y: float, item_id: int) -> bool:
        """Drop a level item (PLI_ITEMADD; GS1 lay/lay2). The server relays a
        PLO_ITEMADD to the rest of the level."""
        if not self.connected or not self._authenticated:
            return False
        data = build_item_add(*world_to_local(x, y), item_id)
        return self._protocol.send_packet(PacketID.PLI_ITEMADD, data)

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
            x = local_coord(self.player.x)
        if y is None:
            y = local_coord(self.player.y)
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

        cached_data = self.get_file(filename)
        cached_modtime = self._cached_file_modtime(filename)
        if cached_data is not None and cached_modtime is not None:
            return self.request_file_if_modified(filename, cached_modtime)

        self._pending_files.add(filename)
        data = build_wantfile(filename)
        return self._protocol.send_packet(PacketID.PLI_WANTFILE, data)

    def request_file_if_modified(self, filename: str, mod_time: int) -> bool:
        """Ask the server to send a file only when its cached copy is stale."""
        if not self.connected or not self._authenticated:
            return False

        self._pending_files.add(filename)
        data = build_update_file(filename, mod_time)
        return self._protocol.send_packet(PacketID.PLI_UPDATEFILE, data)

    def get_file(self, filename: str) -> Optional[bytes]:
        """
        Get a previously downloaded file.

        Args:
            filename: Name of the file

        Returns:
            File data as bytes, or None if not downloaded
        """
        data = self._received_files.get(filename)
        if data is not None:
            return data

        key = normalize_asset_name(filename)
        if not key:
            return None
        try:
            data = (server_cache_dir(self.host, self.port) / key).read_bytes()
        except (OSError, ValueError):
            return None
        self._received_files[filename] = data
        return data

    def has_file(self, filename: str) -> bool:
        """Check if a file has been downloaded."""
        return self.get_file(filename) is not None

    def _load_cache_index(self) -> Dict[str, int]:
        """Load this server's advisory cache metadata once for the session."""
        if self._cache_index is not None:
            return self._cache_index

        index = {}
        try:
            raw = json.loads(
                (server_cache_dir(self.host, self.port) / "index.json").read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(raw, dict):
                index = {
                    str(key): int(value)
                    for key, value in raw.items()
                    if normalize_asset_name(str(key)) == str(key)
                }
        except (OSError, ValueError, TypeError):
            pass
        self._cache_index = index
        return index

    def _cached_file_modtime(self, filename: str) -> Optional[int]:
        """Return stored server metadata for a cached file, when available."""
        key = normalize_asset_name(filename)
        if not key:
            return None
        return self._load_cache_index().get(key)

    @staticmethod
    def _atomic_cache_write(path: Path, data: bytes) -> None:
        """Replace one cache file without exposing a partially written copy."""
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
            os.replace(temporary_name, path)
            temporary_name = None
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def _store_cached_file(
        self, filename: str, file_data: bytes, mod_time: int
    ) -> None:
        """Persist a completed download, ignoring every cache failure."""
        key = normalize_asset_name(filename)
        if not key:
            return
        try:
            directory = server_cache_dir(self.host, self.port)
            directory.mkdir(parents=True, exist_ok=True)
            self._atomic_cache_write(directory / key, file_data)
            index = self._load_cache_index()
            index[key] = int(mod_time)
            encoded = json.dumps(index, sort_keys=True).encode("utf-8")
            self._atomic_cache_write(directory / "index.json", encoded)
        except (OSError, ValueError, TypeError):
            pass

    def _invalidate_cached_file(self, filename: str) -> None:
        """Discard memory and disk copies after a server update notice."""
        key = normalize_asset_name(filename)
        if not key:
            return
        for received_name in list(self._received_files):
            if normalize_asset_name(received_name) == key:
                self._received_files.pop(received_name, None)
        try:
            (server_cache_dir(self.host, self.port) / key).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        try:
            index = self._load_cache_index()
            if key not in index:
                return
            index.pop(key, None)
            directory = server_cache_dir(self.host, self.port)
            encoded = json.dumps(index, sort_keys=True).encode("utf-8")
            self._atomic_cache_write(directory / "index.json", encoded)
        except (OSError, ValueError, TypeError):
            pass

    def is_file_pending(self, filename: str) -> bool:
        """Check if a file download is pending."""
        return filename in self._pending_files

    def did_file_fail(self, filename: str) -> bool:
        """True once a file has been written off and will not be re-requested.

        A single refusal is NOT enough - see server_refused() if you want to
        know whether the server said no at all. This is the gate the asset
        layer checks before re-asking, so it deliberately stays False while
        retries remain.
        """
        return filename in self._failed_files

    def server_refused(self, filename: str) -> bool:
        """True if the server has answered PLO_FILESENDFAILED at least once.

        Distinct from did_file_fail(): this reports the server's answer, that
        reports our decision to stop asking. A caller diagnosing "why is this
        asset missing" wants this one - otherwise an explicit refusal is
        indistinguishable from a request still in flight.
        """
        return self._file_attempts.get(filename, 0) > 0

    @property
    def failed_files(self) -> set:
        """Filenames written off after exhausting their retry budget."""
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
        # Which world we just stepped out of. Unlike gmap_name this survives
        # the exit, so warping back to one of its segments can rebuild the
        # grid from the already-downloaded file (see restore_known_gmap).
        if self.gmap_name:
            self._last_gmap_name = self.gmap_name
        self.gmap_name = ""
        self._requested_gmap = ""
        self._gmap_spawn_x = 0
        self._gmap_spawn_y = 0
        self.player.level = level_name
        self._current_level_name = level_name
        self._pending_level_name = level_name

    def restore_known_gmap(self, spawn_level: str) -> bool:
        """Rebuild the world grid for a segment we're warping back into.

        Walking out of an interior calls `_exit_gmap`, which drops the grid;
        walking back in leaves the client in the standalone local frame until
        the server re-announces the .gmap and the file download completes.
        The transition hold correctly refuses to release into that interim
        frame (see `_maybe_release_local_transition`), so the screen stays
        frozen for the whole round trip - measured at 240 ms on hastur for a
        door we had already used. The .gmap file is unchanged and already in
        `_received_files`, so rebuild from it now instead.

        Returns True if the grid was restored.
        """
        if self.gmap_width or spawn_level not in self._known_gmap_segments:
            return False
        blob = self._received_files.get(self._last_gmap_name)
        if not blob:
            return False
        try:
            self.load_gmap(blob.decode('latin-1', errors='replace'),
                           spawn_level=spawn_level)
        except Exception:
            logger.warning("cached %s failed to parse on gmap re-entry",
                           self._last_gmap_name)
            return False
        self.gmap_name = self._last_gmap_name
        self._requested_gmap = self._last_gmap_name
        return bool(self.gmap_width)

    def load_gmap(self, gmap_data: str, spawn_level: str = ""):
        """
        Parse GMAP data to build the level grid.

        Args:
            gmap_data: Contents of .gmap file
            spawn_level: Segment the player is entering, when the caller knows
                it. Normally the grid cell comes from the PLO_PLAYERWARP2 that
                precedes the download; a client-driven re-entry
                (`restore_known_gmap`) has no such packet and names the
                destination directly instead.
        """
        self.gmap_grid.clear()
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
        # grid position = segment_at(player.x, player.y)
        self._gmap_offset_x = 0
        self._gmap_offset_y = 0

        # Set current level based on spawn grid position from PLO_PLAYERWARP2
        # (which is received before GMAP file, so we can't use gmap_grid at that time)
        # If we have a spawn grid position, use it; otherwise fall back to calculating from coords
        spawn_pos = None
        if spawn_level:
            for grid_pos, seg in self.gmap_grid.items():
                if seg == spawn_level:
                    spawn_pos = grid_pos
                    break
        if spawn_pos is not None:
            pass
        elif self._gmap_spawn_x != 0 or self._gmap_spawn_y != 0:
            spawn_pos = (self._gmap_spawn_x, self._gmap_spawn_y)
        else:
            spawn_pos = segment_at(self.player.x, self.player.y)

        if spawn_pos in self.gmap_grid:
            self._current_level_name = self.gmap_grid[spawn_pos]

            # Convert player coords to world coords if they're still local
            # (PLAYERWARP2 arrives before GMAP, so coords are local at that point)
            if self.player.x < LEVEL_SIZE and self.player.y < LEVEL_SIZE:
                self.player.x, self.player.y = local_to_world(
                    self.player.x, self.player.y, *spawn_pos)

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
                seg_ox, seg_oy = segment_origin(gx, gy)
                if 'x' in npc:
                    raw_x = npc['x']
                    npc['world_x'] = (raw_x if (raw_x >= LEVEL_SIZE or raw_x < 0)
                                       else raw_x + seg_ox)
                if 'y' in npc:
                    raw_y = npc['y']
                    npc['world_y'] = (raw_y if (raw_y >= LEVEL_SIZE or raw_y < 0)
                                       else raw_y + seg_oy)
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
                    seg_ox, seg_oy = segment_origin(gx, gy)
                    if 'x' in npc:
                        raw_x = npc['x']
                        npc['world_x'] = (raw_x if (raw_x >= LEVEL_SIZE or raw_x < 0)
                                           else raw_x + seg_ox)
                    if 'y' in npc:
                        raw_y = npc['y']
                        npc['world_y'] = (raw_y if (raw_y >= LEVEL_SIZE or raw_y < 0)
                                           else raw_y + seg_oy)
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
            my_x, my_y = world_to_local(self.player.x, self.player.y)
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

        # Player coords are GMAP-relative, so the grid cell is simply their segment
        return self.gmap_grid.get(segment_at(self.player.x, self.player.y),
                                  self._current_level_name)

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
        tile_x, tile_y = world_to_local(math.floor(px + dx), math.floor(py + dy))

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
        px, py = world_to_local(self.player.x, self.player.y)
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
    '_large_file_pending': ('file_transfers', 'large_file_pending'),
    '_large_file_discarding': ('file_transfers', 'large_file_discarding'),
    '_large_file_buffer': ('file_transfers', 'large_file_buffer'),
    '_large_file_expected_size': ('file_transfers', 'large_file_expected_size'),
    '_large_file_modtime': ('file_transfers', 'large_file_modtime'),

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
