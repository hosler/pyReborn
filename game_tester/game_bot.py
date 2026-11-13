"""
GameBot - Headless game client wrapper for automated testing.

Provides high-level actions and bug detection callbacks.

PARITY WITH PYGAME CLIENT:
This module aims to behave identically to pygame_game.py (GameClient)
so that bugs detected here would also affect real players.

Key parity features:
- Collision detection using tiletypes.py
- Water/swimming state detection
- Door/link collision on movement
- Same movement step size (0.25 tiles)
"""

import math
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable, Any
from dataclasses import dataclass, field

# Add pyreborn to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyreborn import Client
from pyreborn.client_warp import LINK_PROBE_OFFSETS
from pyreborn.gmap_coords import grid_index, grid_of, local_from_world
from pyreborn.game.constants import (
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
)
from reborn_protocol.coords import in_level_bounds, local_to_world, segment_at
from pyreborn.tiletypes import (
    TileType, get_tile_type, is_blocking, is_swimming_water, selection_for,
)

from .login import login_client
from .pathing import UNREACHABLE, plan_path
from .world_graph import Hop, WorldGraph
import logging
from pyreborn.logutil import log_swallowed
logger = logging.getLogger(__name__)


@dataclass
class ActionLog:
    """Record of an action taken by the bot."""
    timestamp: float
    action: str
    args: Dict[str, Any]
    result: Any
    duration: float


@dataclass
class Issue:
    """A detected bug or anomaly."""
    timestamp: float
    severity: str  # HIGH, MEDIUM, LOW, WARN
    category: str  # position, data, combat, timeout, disconnect
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    screenshot: Optional[bytes] = None


# ---------------------------------------------------------------------------
# Declarative action registry (see GameBot.ACTIONS)
#
# The playtest daemon carried its own dispatch for the same twelve actions -
# which method each command means plus how its query parameters coerce - and
# the two had drifted: `arrow` and `grab` called client methods directly,
# skipping the bot's action log (so those actions were invisible in /log) and
# any guard the bot method adds. The registry lives with the bot; a transport
# only hands over each parameter's raw string (playtest_daemon.do_act()).
# ---------------------------------------------------------------------------

def _as_int(default: Any) -> Callable[[Optional[str]], int]:
    """Absent -> `default` (pass None for "required": int(None) raises)."""
    return lambda raw: int(default if raw is None else raw)


def _as_float(default: Any) -> Callable[[Optional[str]], float]:
    return lambda raw: float(default if raw is None else raw)


def _move_component(raw: str | float | None) -> float:
    value = float(0 if raw is None else raw)
    if not math.isfinite(value):
        raise ValueError("move components must be finite")
    return max(-1.0, min(1.0, value))


def _as_str(default: Optional[str]) -> Callable[[Optional[str]], Optional[str]]:
    return lambda raw: default if raw is None else raw


def _as_opt_int(raw: Optional[str]) -> Optional[int]:
    """Absent -> None, i.e. "let the bot pick" (e.g. sword direction)."""
    return None if raw is None else int(raw)


def _as_opt_coord(raw: Optional[str]) -> Optional[float]:
    """Absent (or blank) -> None, i.e. "auto-target the nearest one".

    Keeps the daemon's original `float(x) if x else None`: `x=0` is the string
    "0", which is truthy, so it still means the coordinate 0.
    """
    return float(raw) if raw else None


def _as_flag(default: bool) -> Callable[[Optional[str]], bool]:
    return lambda raw: default if raw is None else raw not in ('0', 'false',
                                                               'False', '')


@dataclass(frozen=True)
class ActionParam:
    """One parameter of a declared action.

    `name` is the transport-facing name. `arg` is the bot method's keyword.
    They differ where the wire name is shorter, e.g. dir -> direction.
    """
    name: str
    coerce: Callable[[Optional[str]], Any]
    arg: str = ""

    @property
    def keyword(self) -> str:
        return self.arg or self.name


@dataclass(frozen=True)
class BotAction:
    """A bot method reachable by name, with its parameter coercions."""
    name: str
    method: str
    params: Tuple[ActionParam, ...] = ()
    #: Arguments fixed by the registry rather than the caller.
    fixed: Tuple[Tuple[str, Any], ...] = ()

    def bind(self, raw: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        """Coerce this action's parameters from a raw name -> string lookup."""
        kwargs = {param.keyword: param.coerce(raw(param.name))
                  for param in self.params}
        kwargs.update(self.fixed)
        return kwargs

    def run(self, bot: "GameBot", raw: Callable[[str], Optional[str]]) -> Any:
        return getattr(bot, self.method)(**self.bind(raw))


def _blocking_tile_in_footprint(board: List[int], x: float,
                                y: float, tilestype=None) -> Optional[int]:
    """Return a blocking tile under the direction-less movement probes."""
    for ox, oy in ((1.5, 2.0), (2.0, 0.5)):
        tx, ty = math.floor(x + ox), math.floor(y + oy)
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            continue
        tile = board[ty * 64 + tx]
        if is_blocking(tile, tilestype):
            return tile
    return None


def _validate_warp_dest(level_name: str, x: float, y: float,
                        board_lookup: Callable[[str], Any], client=None) -> Optional[str]:
    """Best-effort check that warping to local (x, y) on level_name will not
    strand the bot on a blocking tile. Returns an error string if it would,
    None if it looks clear OR the destination level's board is not cached
    yet (never having visited it, there is nothing to check against - let
    the warp through rather than block on it)."""
    board = board_lookup(level_name)
    if not board or len(board) < 4096:
        return None
    tilestype = selection_for(client).tilestype_for_level(level_name)
    tile = _blocking_tile_in_footprint(board, x, y, tilestype)
    if tile is not None:
        return (f'warp destination ({x},{y}) on {level_name!r} is blocking '
                f'(tile={tile}); pass force=1 to override')
    return None


class GameBot:
    """
    Automated game player for testing.

    Wraps pyReborn Client with high-level actions and anomaly detection.

    Usage:
        bot = GameBot("testbot1", "localhost", 14900)
        bot.connect()
        bot.walk_to(35, 35)
        bot.sword_attack()
        issues = bot.get_issues()
        bot.disconnect()
    """

    def __init__(self, name: str, host: str = "localhost", port: int = 14900,
                 password: str = "testpass", version: str = "6.037",
                 source_address: Optional[str] = None):
        self.name = name
        self.host = host
        self.port = port
        self.password = password

        # Classic (2.x) servers reject the v6 handshake outright, so a bot
        # pointed at one needs its protocol version. Defaults to 6.037 so
        # every existing caller behaves exactly as before; see
        # game_tester/version_probe.py for finding what a server accepts.
        self.client = Client(host, port, version=version, source_address=source_address)
        self.issues: List[Issue] = []
        self.action_log: List[ActionLog] = []
        self.position_history: List[Tuple[float, float, float]] = []  # (x, y, time)

        # Callback tracking
        self.chat_received: List[Tuple[int, str, float]] = []  # (player_id, msg, time)
        self.hurt_received: List[Tuple[int, float, float]] = []  # (attacker, damage, time)
        self.pm_received: List[Tuple[int, str, float]] = []  # (from_id, msg, time)
        self.say2_received: List[Tuple[str, float]] = []  # (text, time) NPC dialogue/signs

        # Setup callbacks
        self._setup_callbacks()

        # State tracking
        self._stuck_count = 0
        self._connected = False

        # Local harnesses track clients and seed dynamic daemon account names.
        from .local_world import local_world_for
        world = local_world_for(host, port)
        if world is not None:
            world.register_bot(self)
        self._stuck_warned = False  # Only warn once when stuck

        # Death/respawn tracking (parity with pygame_game.py's _was_dead):
        # the server silently refills hearts and resets position on respawn,
        # so without watching for the hearts>0 <-> hearts<=0 transition a
        # kill is completely invisible to a playtest agent's /log.
        self._was_dead = False

        # Parity with pygame client: swimming state
        self.is_swimming = False

        # Door/link auto-traversal state (parity with pygame_game.py's
        # ActionsMixin._try_link_warp): rising-edge latch so a link only
        # fires the moment we step onto it, plus a post-warp suppression so
        # we don't immediately bounce back through a return link or an
        # overlapping link at the arrival point. See _maybe_follow_link().
        self._was_on_link = False
        self._link_arrival: Optional[Tuple[float, float]] = None
        self.world_graph: WorldGraph | None = None

    def _setup_callbacks(self):
        """Setup client callbacks for tracking."""
        self.client.on_chat = self._on_chat
        self.client.on_hurt = self._on_hurt
        self.client.on_pm = self._on_pm
        self.client.on_say2 = self._on_say2

    def _on_chat(self, player_id: int, message: str):
        """Track chat messages received."""
        self.chat_received.append((player_id, message, time.time()))

    def _on_hurt(self, attacker_id: int, damage: float, damage_type: int,
                 source_x: float, source_y: float):
        """Track damage received."""
        self.hurt_received.append((attacker_id, damage, time.time()))

    def _on_pm(self, from_id: int, message: str):
        """Track private messages received."""
        self.pm_received.append((from_id, message, time.time()))

    def _on_say2(self, text: str):
        """Track sign/NPC dialogue messages (PLO_SAY2 from say2/signs).

        Without this, scripted NPC dialogue is invisible to bots and playtest
        agents report working NPCs as silent."""
        self.say2_received.append((text, time.time()))

    def _log_action(self, action: str, args: Dict[str, Any], result: Any,
                    start_time: float):
        """Log an action for debugging."""
        self.action_log.append(ActionLog(
            timestamp=start_time,
            action=action,
            args=args,
            result=result,
            duration=time.time() - start_time
        ))

    def _add_issue(self, severity: str, category: str, description: str,
                   context: Optional[Dict[str, Any]] = None):
        """Add a detected issue."""
        self.issues.append(Issue(
            timestamp=time.time(),
            severity=severity,
            category=category,
            description=description,
            context=context or {}
        ))

    # ========== Connection ==========

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect and login to server.

        Every failure path closes the socket before returning: a bot that got
        as far as the TCP connect (or all the way to a refused login) used to
        be left holding an open connection, and since most callers only check
        the bool they never cleaned it up - leaked sockets plus an account the
        server still considers logged in, which then poisons the next run.
        """
        start = time.time()
        try:
            outcome = login_client(self.client, self.name, self.password,
                                   timeout=timeout)
        except Exception as e:
            self._abandon_connection()
            self._add_issue("HIGH", "connect", f"Connection error: {e}")
            self._log_action("connect", {"name": self.name}, False, start)
            return False

        if not outcome.ok:
            self._abandon_connection()
            # The server's own reason (version mismatch, staff-only, bad
            # password) is otherwise invisible to callers that only print
            # get_issues() - see conftest.py's bots fixture.
            detail = f": {outcome.rejection}" if outcome.rejection else ""
            self._add_issue("HIGH", "connect",
                            f"Login failed for {self.name}{detail}")
            return False

        self._connected = True
        self._log_action("connect", {"name": self.name}, True, start)
        return True

    def _abandon_connection(self):
        """Close a connection that never made it in-game (see connect())."""
        self._connected = False
        try:
            self.client.disconnect()
        except Exception:
            log_swallowed(logger, level=logging.DEBUG)

    def disconnect(self):
        """Disconnect from server."""
        start = time.time()
        self.client.disconnect()
        self._connected = False
        self._log_action("disconnect", {}, True, start)

    @property
    def connected(self) -> bool:
        """Check if still connected."""
        return self._connected and self.client.connected

    # ========== Movement ==========

    def update(self, duration: float = 0.1):
        """Process packets for a duration."""
        end_time = time.time() + duration
        while time.time() < end_time:
            self.client.update(timeout=0.05)
            time.sleep(0.01)

        # Track position
        self.position_history.append((self.client.x, self.client.y, time.time()))
        # Keep only last 100 positions
        if len(self.position_history) > 100:
            self.position_history = self.position_history[-100:]

        # Check for stuck
        self._check_stuck()

        # Check for death/respawn
        self._check_death_respawn()

    def _check_death_respawn(self):
        """Detect a hearts>0 -> hearts<=0 (death) or hearts<=0 -> hearts>0
        (respawn) transition and log it as an issue.

        Without this, deaths are invisible to a playtest agent: the server
        just silently refills hearts and warps the player back after a
        short delay - hurt_received records the damage that was dealt, but
        never that a hit was fatal, so a bot getting killed shows up in
        /log as nothing more than an ordinary hurt event followed by an
        unexplained position jump. Mirrors pygame_game.py's identical
        `_was_dead` transition tracking (game/setup.py, pygame_game.py).
        """
        is_dead = self.client.player.hearts <= 0
        if is_dead and not self._was_dead:
            self._add_issue("MEDIUM", "combat",
                           f"Bot died at ({self.client.x:.1f}, {self.client.y:.1f})")
        elif self._was_dead and not is_dead:
            self._add_issue("LOW", "combat",
                           f"Bot respawned at ({self.client.x:.1f}, {self.client.y:.1f})")
        self._was_dead = is_dead

    def move(self, dx: float, dy: float, check_collision: bool = True,
             follow_links: bool = True) -> bool:
        """Attempt ONE quarter-tile step, scaled by dx/dy clamped to [-1, 1].

        Fractional components allow a waypoint correction smaller than a step.
        Check the complete feet rectangle at the actual step destination so
        planning and movement agree on where the bot can stand.

        Args:
            dx: X step multiplier, clamped to [-1, 1]
            dy: Y step multiplier, clamped to [-1, 1]
            check_collision: If True, check blocking tiles and NPCs
            follow_links: If True (default), auto-warp through a door/link the
                bot ends up standing on, matching the real client
                (pygame_game.py's ActionsMixin calls _try_link_warp() after
                every move). Link warps are CLIENT-initiated - the server
                only streams link rectangles, it never triggers the warp -
                so without this a headless bot silently walks straight
                through doors/cave entrances and never enters them. Pass
                False to inspect a link without taking it.

        Returns:
            True if moved, False if blocked or failed
        """
        start = time.time()
        dx, dy = _move_component(dx), _move_component(dy)
        old_x, old_y = self.client.x, self.client.y

        dest_x = old_x + dx * 0.25
        dest_y = old_y + dy * 0.25

        # Check the actual step destination before moving.
        if check_collision and self._is_position_blocked(dest_x, dest_y, dx, dy):
            # Position is blocked - don't move. Still check for a link: cave/
            # door entrances sit on solid tiles you can't step onto, so
            # walking into one blocks the move but should still trigger the
            # warp (pygame_game.py's _move() does the same - it calls
            # _try_link_warp() from its "fully blocked" branch too).
            self._log_action("move", {"dx": dx, "dy": dy, "blocked": True}, False, start)
            if follow_links:
                self._maybe_follow_link()
            return False

        # Move only 0.25 tiles (client.move uses step=0.25 by default)
        result = self.client.move(dx, dy)
        self.update(0.05)

        # Update swimming state after move (parity with pygame)
        self._update_swimming_state()

        # Check if actually moved
        moved = (abs(self.client.x - old_x) > 0.01 or
                 abs(self.client.y - old_y) > 0.01)

        self._log_action("move", {"dx": dx, "dy": dy}, moved, start)

        # Check for door/edge link at the new position (auto-warp on
        # walk-into, parity with pygame's _try_link_warp()).
        if follow_links:
            self._maybe_follow_link()

        return moved

    def walk_to(self, target_x: float, target_y: float, timeout: float = 10.0,
                follow_links: bool = True, *, pathing: bool = True,
                tolerance: float = 0.5) -> bool:
        """
        Walk to a target position using A*, with greedy walking as fallback.

        target_x/target_y are in the same frame as self.x/self.y: WORLD
        coordinates on a GMAP (local + grid*64, matching client.x/client.y
        and the /state x/y the playtest daemon reports), local (0-63) on a
        plain level. self.client.x/y already track world coords across a
        GMAP without wrapping (client.move() never resets to local - it only
        sends local coords over the wire), so this comparison is safe as
        long as callers pass the same frame - do not pass a local (0-63)
        target while on a GMAP.

        Links are obstacles unless the goal lies inside that link. For a
        targeted link, follow_links is forwarded to move(). A warp out of
        this world ends the walk; segment crossings within one GMAP continue.
        After the last lattice waypoint, approach the exact goal greedily
        until its distance is within tolerance.

        pathing: set False to use the original greedy loop. Planning failure
        or four stalled ticks after each of three replans also falls back to
        that loop, sharing the original timeout and movement reporting.
        An exhausted search allows two seconds of greedy recovery without
        progress toward the goal before reporting a LOW target unreachable.

        Returns True if reached target, False if stuck/timeout/warped away.
        """
        start = time.time()
        walk_start = time.monotonic()
        walk_deadline = walk_start + timeout
        start_level = self.level
        start_gmap = self.client.gmap_name if self.client.in_gmap_segment else None

        def warped():
            # A segment-name change preserves the world frame. Interiors and
            # another GMAP do not, even if the old grid is still cached.
            same_world = (start_gmap is not None and self.client.in_gmap_segment
                          and self.client.gmap_name == start_gmap)
            return ((self.level != start_level and not same_world)
                    or (start_gmap is not None and
                        (not self.client.in_gmap_segment
                         or self.client.gmap_name != start_gmap)))

        def walk_step(dx, dy):
            if self._walk_link_blocked(self.client.x + dx * 0.25,
                                       self.client.y + dy * 0.25,
                                       target_x, target_y):
                self.update(0.05)
                return False
            return self.move(dx, dy, follow_links=follow_links)

        # Did we ever actually move during this call? Distinguishes a
        # permanent hard strand (never moved a single step, even after the
        # stuck-recovery sidestepping below tried other directions) from an
        # ordinary timeout where progress was made but the target just
        # wasn't reached in time - see the two _add_issue calls below.
        moved_ever = False
        path = None
        waypoint = 0
        stalled_ticks = 0
        replans = 0
        if (pathing and timeout > 0
                and math.hypot(target_x - self.client.x,
                               target_y - self.client.y) > tolerance):
            path = self._plan_walk_path(
                target_x, target_y, walk_start + min(timeout * 0.4, 2.0))
        unreachable = path is UNREACHABLE
        if unreachable:
            path = None
        progress_at = time.monotonic()
        best_distance = math.hypot(target_x - self.client.x, target_y - self.client.y)

        while time.monotonic() < walk_deadline:
            dx = target_x - self.client.x
            dy = target_y - self.client.y

            # Check if arrived
            if math.hypot(dx, dy) <= tolerance:
                self._log_action("walk_to", {"x": target_x, "y": target_y}, True, start)
                return True

            if path is not None:
                while waypoint < len(path):
                    wx, wy = path[waypoint]
                    if abs(wx - self.client.x) > 1e-6 or abs(wy - self.client.y) > 1e-6:
                        break
                    waypoint += 1
                if waypoint == len(path):
                    path = None
                    continue
                wx, wy = path[waypoint]
                old_x, old_y = self.client.x, self.client.y
                move_dx = max(-1, min(1, (wx - old_x) / 0.25))
                move_dy = max(-1, min(1, (wy - old_y) / 0.25))
                walk_step(move_dx, move_dy)
                if (abs(self.client.x - old_x) < 0.01
                        and abs(self.client.y - old_y) < 0.01):
                    # Blocked move() returns before pumping incoming packets.
                    self.update(0.05)
                if warped():
                    self._log_action("walk_to", {"x": target_x, "y": target_y,
                                                 "warped_to": self.level}, False, start)
                    return False
                moved = (abs(self.client.x - old_x) > 0.01
                         or abs(self.client.y - old_y) > 0.01)
                moved_ever |= moved
                before = math.hypot(wx - old_x, wy - old_y)
                after = math.hypot(wx - self.client.x, wy - self.client.y)
                stalled_ticks = stalled_ticks + 1 if after >= before - 0.01 else 0
                if stalled_ticks >= 4:
                    now = time.monotonic()
                    replan_deadline = min(
                        walk_deadline, now + min(max(0.0, walk_deadline - now) * 0.1, 0.5))
                    path = (self._plan_walk_path(target_x, target_y, replan_deadline)
                            if replans < 3 and now < walk_deadline else None)
                    unreachable = path is UNREACHABLE
                    if unreachable:
                        path = None
                        progress_at = time.monotonic()
                        best_distance = math.hypot(target_x - self.client.x,
                                                   target_y - self.client.y)
                    replans += 1
                    waypoint = 0
                    stalled_ticks = 0
                continue

            # Determine direction
            move_dx = max(-1, min(1, dx / 0.25))
            move_dy = max(-1, min(1, dy / 0.25))

            # Try to move
            old_x, old_y = self.client.x, self.client.y
            walk_step(move_dx, move_dy)

            if warped():
                # A link fired mid-walk (see move()/_maybe_follow_link) and
                # dropped us on a different level - target_x/target_y were
                # meant for start_level's frame and are now meaningless.
                self._log_action("walk_to", {"x": target_x, "y": target_y,
                                             "warped_to": self.level}, False, start)
                return False

            # Check if stuck
            if abs(self.client.x - old_x) < 0.01 and abs(self.client.y - old_y) < 0.01:
                self._stuck_count += 1
                if self._stuck_count > 10:
                    # Try alternate route: sidestep along the axis we're NOT
                    # blocked on, in the direction that actually helps reach
                    # the target (sign of dx/dy) - not a fixed south-then-
                    # east regardless of where the target is. The old fixed
                    # heuristic could walk a bot further from a west/north
                    # target every time it got stuck (live repro: action log
                    # showed dx:+1 "east" move steps while the target was
                    # west of the bot).
                    if move_dx != 0:
                        step_y = 1 if dy >= 0 else -1
                        walk_step(0, step_y)
                        walk_step(0, step_y)
                    if move_dy != 0:
                        step_x = 1 if dx >= 0 else -1
                        walk_step(step_x, 0)
                        walk_step(step_x, 0)
                    self._stuck_count = 0
            else:
                self._stuck_count = 0
                moved_ever = True

            if (unreachable and abs(self.client.x - old_x) < 0.01
                    and abs(self.client.y - old_y) < 0.01):
                # Blocked move() does not pump packets. Keep recovery responsive
                # to server changes and avoid spinning during the grace period.
                self.update(0.05)

            if warped():
                self._log_action("walk_to", {"x": target_x, "y": target_y,
                                             "warped_to": self.level}, False, start)
                return False

            if unreachable:
                distance = math.hypot(target_x - self.client.x, target_y - self.client.y)
                if distance < best_distance - 0.05:
                    best_distance = distance
                    progress_at = time.monotonic()
                elif distance > tolerance and time.monotonic() - progress_at >= 2.0:
                    self._add_issue("LOW", "movement",
                                    f"target unreachable: target=({target_x}, {target_y})")
                    self._log_action("walk_to", {"x": target_x, "y": target_y}, False, start)
                    return False

        if math.hypot(target_x - self.client.x, target_y - self.client.y) <= tolerance:
            self._log_action("walk_to", {"x": target_x, "y": target_y}, True, start)
            return True

        if moved_ever:
            self._add_issue("LOW", "movement", f"walk_to timeout: target=({target_x}, {target_y})")
        else:
            # Never moved at all despite the full timeout (including the
            # stuck-recovery sidestepping in every direction above) - this
            # is a hard strand, not "ran out of time while making progress",
            # and deserves a higher severity + the bot's actual position so
            # it can be found on the map.
            self._add_issue("MEDIUM", "movement",
                           f"movement strand: no movement at all from "
                           f"({self.client.x:.1f}, {self.client.y:.1f}) toward "
                           f"target=({target_x}, {target_y})")
        self._log_action("walk_to", {"x": target_x, "y": target_y}, False, start)
        return False

    def _navigation_graph(self, graph=None):
        graph = graph if graph is not None else self.world_graph
        if graph is None:
            graph = WorldGraph()
        for level, links in list(self.client.links.items()):
            graph.add_observed(level, links)
        if self.client.in_gmap_segment:
            graph._add_seams(self.client.gmap_grid)
        return graph

    def travel_to(self, level_name: str, x: float | None = None,
                  y: float | None = None, *, timeout: float = 60.0,
                  graph: WorldGraph | None = None) -> bool:
        """Walk through a shortest chain of links/seams, without cheat warps.

        A supplied graph (or a daemon's configured world_graph) is merged with
        observed links. Otherwise only observed links are known. Optional final
        x/y use walk_to's WORLD coordinate frame on a GMAP. Both are required
        together. Unexpected landings allow at most three route replans.
        """
        if not isinstance(level_name, str) or not level_name.strip():
            raise ValueError('travel requires a level name')
        if (x is None) != (y is None):
            raise ValueError('travel requires both x and y')
        if not math.isfinite(timeout) or (x is not None and
                not all(math.isfinite(v) for v in (x, y))):
            raise ValueError('travel coordinates and timeout must be finite')
        start = time.time()
        deadline = time.monotonic() + timeout
        target = level_name.strip().casefold()
        graph = self._navigation_graph(graph)

        def finish(ok, reason=''):
            if not ok:
                self._add_issue('LOW', 'movement',
                                f'travel unreachable: level={level_name!r}; {reason}')
            self._log_action('travel_to', {'level': level_name, 'x': x, 'y': y}, ok, start)
            return ok

        replans = 0
        while time.monotonic() < deadline:
            graph = self._navigation_graph(graph)
            route = graph.route(self.level, target)
            if route is None:
                return finish(False, 'no route')
            if not route:
                ok = x is None or self.walk_to(x, y, timeout=max(0, deadline - time.monotonic()))
                return finish(ok and self.level.casefold() == target
                              and time.monotonic() <= deadline, 'final walk failed or timeout')
            unexpected = False
            for hop in route:
                if time.monotonic() >= deadline:
                    return finish(False, 'timeout')
                source = self.level.casefold()
                self._travel_hop(hop, deadline)
                # walk_to returns False on an ordinary door warp, so judge
                # arrival by the resolved level, after pumping in-flight data.
                warp_deadline = min(deadline, time.monotonic() + 3.0)
                while (self.level.casefold() != hop.dest_level.casefold()
                       and time.monotonic() < warp_deadline):
                    self.update(min(0.05, warp_deadline - time.monotonic()))
                if self.level.casefold() == hop.dest_level.casefold():
                    self.update(min(0.1, max(0, deadline - time.monotonic())))
                    continue
                if self.level.casefold() == source:
                    return finish(False, 'link did not reach destination or timeout')
                unexpected = True
                break
            if unexpected:
                replans += 1
                if replans > 3:
                    return finish(False, 'replan limit')
        return finish(False, 'timeout')

    def _travel_targets(self, hop: Hop):
        """Standable trigger positions, or crossing points along a seam."""
        c = self.client
        cells = grid_index(c.gmap_grid, casefold=True)
        cell = cells.get(hop.source_level.casefold()) if c.in_gmap_segment else None
        ox, oy = local_to_world(0, 0, *cell) if cell is not None else (0, 0)
        if hop.seam:
            if cell is None or hop.dest_level.casefold() not in cells:
                return []
            points = [(hop.x + ox, t * .5 + oy, 0, 0) for t in range(128)] if hop.width < 1 else [
                (t * .5 + ox, hop.y + oy, 0, 0) for t in range(128)]
        else:
            points = []
            # The reference uses a continuous directional probe, including
            # the rectangle's far edge. Probe-ready standable positions also
            # handle solid doors: face them and attempt the last blocked step.
            for tx in range(max(0, math.ceil(hop.x)), min(63, math.floor(hop.x + hop.width)) + 1):
                for ty in range(max(0, math.ceil(hop.y)), min(63, math.floor(hop.y + hop.height)) + 1):
                    for direction, (px, py) in enumerate(LINK_PROBE_OFFSETS):
                        dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[direction]
                        for fraction in (0, .5):
                            if not (hop.x <= tx + fraction + dx * .25 <= hop.x + hop.width
                                    and hop.y <= ty + fraction + dy * .25 <= hop.y + hop.height):
                                continue
                            points.append((tx + fraction - px + ox,
                                           ty + fraction - py + oy, dx, dy))
        points = [p for p in points if not self._path_position_blocked(*p[:2])]
        points.sort(key=lambda p: (
            not (hop.x + ox <= p[0] < hop.x + ox + hop.width and
                 hop.y + oy <= p[1] < hop.y + oy + hop.height),
            math.hypot(p[0] - c.x, p[1] - c.y)))
        return points

    def _travel_hop(self, hop, deadline):
        c = self.client
        source = self.level.casefold()
        cell = grid_of(c.gmap_grid, source, casefold=True) if c.in_gmap_segment else None
        origin = local_to_world(0, 0, *cell) if cell is not None else (0, 0)
        # Reuse walk_to's targeted-link exemption even when the standable
        # approach lies just outside a solid door's rectangle.
        self._travel_link_goal = (hop.x + origin[0], hop.y + origin[1])
        try:
            # Respect arrival suppression: physically leave the arrival point
            # before trying a nearby return door, rather than clearing latches.
            if (self._link_arrival is not None
                    and abs(c.x - self._link_arrival[0]) < 1.5
                    and abs(c.y - self._link_arrival[1]) < 1.5):
                ax, ay = self._link_arrival
                escape = [(ax + dx, ay + dy) for dx, dy in
                          ((4, 0), (-4, 0), (0, 4), (0, -4),
                           (2, 0), (-2, 0), (0, 2), (0, -2))]
                for point in escape:
                    if not self._path_position_blocked(*point):
                        self.walk_to(*point, timeout=max(0, deadline - time.monotonic()),
                                     follow_links=False, tolerance=0.1)
                        if self.level.casefold() != source:
                            return
                        if (time.monotonic() < deadline
                                and (abs(c.x - ax) >= 1.5 or abs(c.y - ay) >= 1.5)
                                and self.check_link_collision() is None):
                            # Let normal movement observe the off-link state;
                            # the approach must get a fresh rising edge too.
                            self.move(0, 0, follow_links=True)
                            break
            planning_deadline = min(deadline, time.monotonic() + 2)
            for tx, ty, dx, dy in self._travel_targets(hop):
                if time.monotonic() >= deadline or self.level.casefold() != source:
                    return
                # Reject disconnected approaches before spending the walking
                # budget on them. walk_to performs its usual bounded planning.
                if self._plan_walk_path(tx, ty, planning_deadline) is UNREACHABLE:
                    continue
                reached = self.walk_to(tx, ty, timeout=max(0, deadline - time.monotonic()),
                                       follow_links=True, tolerance=0.1)
                if self.level.casefold() != source:
                    return
                if reached and not hop.seam and time.monotonic() < deadline:
                    c.player.direction = {(0, -1): 0, (-1, 0): 1,
                                          (0, 1): 2, (1, 0): 3}[dx, dy]
                    self.move(dx, dy, follow_links=True)
                    # A warp may be asynchronous; let travel_to await it before
                    # attempting any more movement in the source coordinate frame.
                    return
        finally:
            del self._travel_link_goal

    def _plan_walk_path(self, target_x: float, target_y: float,
                        deadline: float | None = None):
        """Snapshot nearby players as soft costs in the bot's world frame."""
        others = []
        c = self.client
        grid = c.gmap_grid if c.in_gmap_segment else {}
        cells = grid_index(grid)
        for pid, player in list(c.players.items()):
            if pid == c.player.id or player.get('x') is None or player.get('y') is None:
                continue
            level = player.get('level')
            if level and level != self.level and level not in cells:
                continue
            px, py = player['x'], player['y']
            if grid:
                cell = cells.get(level, segment_at(c.x, c.y))
                px, py = local_to_world(px, py, *cell)
            wx, wy = player.get('world_x'), player.get('world_y')
            others.append((px if wx is None else wx, py if wy is None else wy))

        def cost(x, y):
            # Two classic 2x2 feet boxes overlap within two tiles per axis.
            width = PLAYER_COLLISION_RIGHT - PLAYER_COLLISION_LEFT
            height = PLAYER_COLLISION_BOTTOM - PLAYER_COLLISION_TOP
            return sum(4.0 for px, py in others
                       if abs(x - px) < width and abs(y - py) < height)

        def blocked(x, y):
            return (self._path_position_blocked(x, y)
                    or self._walk_link_blocked(x, y, target_x, target_y))

        return plan_path((c.x, c.y), (target_x, target_y),
                         blocked, cost=cost, deadline=deadline)

    def _path_position_blocked(self, x: float, y: float) -> bool:
        """Use exactly the standing clearance used by move()."""
        return self._is_position_blocked(x, y)

    def _walk_link_blocked(self, x, y, goal_x, goal_y):
        """Avoid door footprints and directional triggers unless targeted.

        Seam links between GMAP neighbours are ordinary world movement.
        Other links use inclusive continuous probes, matching check_link_collision.
        Test all facings since a path node can be approached from any side.
        """
        c = self.client
        goal_x, goal_y = getattr(self, '_travel_link_goal', (goal_x, goal_y))
        grid = c.gmap_grid if c.in_gmap_segment else {}
        cells = grid_index(grid)
        for level, links in c.links.items():
            if level != self.level and level not in cells:
                continue
            origin = local_to_world(0, 0, *cells[level]) if level in cells else (0, 0)
            for link in links:
                lx, ly = link.get('x', 0), link.get('y', 0)
                width, height = link.get('width', 1), link.get('height', 1)
                edge = lx <= 1 or lx + width >= 63 or ly <= 1 or ly + height >= 63
                if grid and edge and link.get('dest_level') in c.get_adjacent_levels(level):
                    continue
                lx, ly = lx + origin[0], ly + origin[1]
                if lx <= goal_x < lx + width and ly <= goal_y < ly + height:
                    continue
                if (x + PLAYER_COLLISION_LEFT < lx + width + 1
                        and x + PLAYER_COLLISION_RIGHT > lx
                        and y + PLAYER_COLLISION_TOP < ly + height + 1
                        and y + PLAYER_COLLISION_BOTTOM > ly):
                    return True
                for ox, oy in LINK_PROBE_OFFSETS:
                    if lx <= x + ox <= lx + width and ly <= y + oy <= ly + height:
                        return True
        return False

    def _check_stuck(self):
        """Check if bot is stuck in same position.

        Uses a higher threshold (30 samples) to avoid false positives
        during normal gameplay pauses (connecting, loading, etc).
        """
        if len(self.position_history) < 30:
            return

        recent = self.position_history[-30:]
        positions = set((round(p[0], 1), round(p[1], 1)) for p in recent)

        if len(positions) == 1:
            # All 30 positions are the same - only warn once
            if not self._stuck_warned:
                self._add_issue("WARN", "movement",
                               f"Bot appears stuck at ({self.client.x:.1f}, {self.client.y:.1f})")
                self._stuck_warned = True
        else:
            # Movement detected, reset warning flag
            self._stuck_warned = False

    # ========== Collision Detection (Parity with pygame_game.py) ==========

    def _resolve_level_name(self, x: Optional[float] = None,
                             y: Optional[float] = None) -> str:
        """Resolve which level owns a world position even when
        client._current_level_name is a poor proxy for "the level the
        player is standing in" while on a GMAP.

        client.py's PLO_LEVELNAME handler updates _current_level_name on
        EVERY level-name announcement it parses, including the board streams
        for neighbouring segments that request_adjacent_levels() pulls in
        right after a gmap loads (and again on every segment crossing) - it
        really means "which segment's packets are we parsing right now", not
        "where is the player". Confirmed live: connect to a gmap start
        level, let it settle ~1s, and _current_level_name has silently
        become whichever of the 8 neighbours streamed in last, even though
        the player never moved (e.g. spawns on chicken1.nw at world
        (94,94) and _current_level_name reads "chicken8.nw"). Every method
        here that read tiles/links for "the current level" was keying off
        that field and got the wrong board/links as soon as a bot loaded a
        gmap - that is the root cause behind walk_to() reading blocking data
        from a neighbouring segment's board and producing nonsensical
        moves/timeouts, and check_link_collision() missing doors entirely.

        Derives the level from the actual world position via the grid
        instead (mirrors client.get_current_level_from_position(), but for
        an arbitrary probed point rather than only the player's own
        position - collision lookahead probes a point up to a tile away,
        which can itself be across a segment boundary).
        """
        c = self.client
        if x is None:
            x = c.x
        if y is None:
            y = c.y
        # A loaded grid can remain configured while the player is on a
        # standalone level.  Only probe it when the authoritative current
        # level identifies a member segment, matching Client's resolver.
        if c.in_gmap_segment and c.gmap_grid:
            grid_x = math.floor(x / 64)
            grid_y = math.floor(y / 64)
            name = c.gmap_grid.get((grid_x, grid_y))
            if name:
                return name
        return c._current_level_name

    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates).

        Matches pygame_game.py:_get_tile_at() for parity.
        """
        # Get the tiles for whichever level actually owns (x, y) - see
        # _resolve_level_name for why this can't just be
        # client._current_level_name on a GMAP.
        if self.client.is_gmap:
            level_name = self._resolve_level_name(x, y)
            tiles = self.client.levels.get(level_name, self.client.tiles)
        else:
            tiles = self.client.tiles

        if not tiles:
            return 0  # Default to walkable

        # Convert to tile indices. floor() (not int()) so negatives don't
        # truncate toward 0, and bounds-check BEFORE any %64: off-level
        # coords on a single level must read as out-of-world, not wrap
        # around to the far side of the board (int(-1.5)%64 == 63 used to
        # let bots walk off the west edge and sample east-side tiles).
        tx = math.floor(x)
        ty = math.floor(y)
        if self.client.is_gmap:
            tx %= 64
            ty %= 64
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return -1  # out of world: blocking, not water

        tile_idx = ty * 64 + tx
        if tile_idx >= len(tiles):
            return -1

        return tiles[tile_idx]

    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check every tile overlapped by the half-open 2x2 feet rectangle.

        The sprite anchor is (x, y); feet span (x+.5, y+1) to (x+2.5, y+3).
        Merely touching a wall edge is allowed. Both planning and actual
        movement use this predicate, including across loaded GMAP seams.
        """
        c = self.client
        left, right = x + PLAYER_COLLISION_LEFT, x + PLAYER_COLLISION_RIGHT
        top, bottom = y + PLAYER_COLLISION_TOP, y + PLAYER_COLLISION_BOTTOM
        for tx in range(math.floor(left), math.ceil(right)):
            for ty in range(math.floor(top), math.ceil(bottom)):
                check_x, check_y = max(left, tx), max(top, ty)
                if c.in_gmap_segment:
                    level = c.gmap_grid.get(segment_at(check_x, check_y))
                    if not level or not c.levels.get(level):
                        return True
                elif not in_level_bounds(check_x, check_y):
                    return True
                tilestype = selection_for(c).tilestype_for_level(
                    self._resolve_level_name(check_x, check_y))
                if is_blocking(self._get_tile_at(check_x, check_y), tilestype):
                    return True
                if c.npcs and self._npc_blocks_at(check_x, check_y):
                    return True
        if c.npcs:
            host = self._npc_collision_host()
            for npc in c.npcs.values():
                rect = host.npc_image_rect(npc)
                if rect is None:
                    continue
                nx, ny, width, height = rect
                px, py = max(left, nx), max(top, ny)
                if (px < min(right, nx + width) and py < min(bottom, ny + height)
                        and host.npc_blocks_at(px, py)):
                    return True
        return False

    def _npc_blocks_at(self, check_x, check_y):
        return self._npc_collision_host().npc_blocks_at(check_x, check_y)

    def _npc_collision_host(self):
        # Reuse the pygame client's NPC wall predicate without pygame.
        from pyreborn.gs1_client import ClientGS1
        host = self.client.gs1_host
        if host is None:
            host = getattr(self, '_npc_collision', None)
            if host is None or host.client is not self.client:
                host = self._npc_collision = ClientGS1(self.client)
        return host

    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the standing point is in deep, swimmable water."""
        tile_id = self._get_tile_at(x, y)
        tilestype = selection_for(self.client).tilestype_for_level(
            self._resolve_level_name(x, y))
        return is_swimming_water(tile_id, tilestype)

    def _update_swimming_state(self):
        """Update swimming state based on current position.

        Matches pygame_game.py:_update_swimming_state() for parity: sample the
        standing point between the feet (sprite top-left + (1.5, 2.5)), not
        either movement probe or the sprite's top-left corner.
        """
        self.is_swimming = self._check_water_at_position(self.client.x + 1.5,
                                                         self.client.y + 2.5)

    def check_link_collision(self) -> Optional[dict]:
        """Check if bot is standing on a door/warp link.

        Returns the link dict if on a door link, None otherwise.

        Reimplemented rather than delegated to client.check_link_collision():
        that method keys client.links off client._current_level_name, which
        is not reliable as "the player's level" on a GMAP (see
        _resolve_level_name). Same body-sampling / edge-link-filtering logic
        as the client version, just keyed by the position-derived level.
        """
        c = self.client
        level_name = self._resolve_level_name()
        links = c.links.get(level_name, [])
        if not links:
            return None

        # Keep the client probe geometry in the position-derived level frame.
        px, py = c.x, c.y
        dx, dy = LINK_PROBE_OFFSETS[c.player.direction & 3]
        tile_x, tile_y = local_from_world(
            c.gmap_grid if c.in_gmap_segment else None, level_name, px + dx, py + dy)

        for link in links:
            lx = link.get('x', 0)
            ly = link.get('y', 0)
            lw = link.get('width', 1)
            lh = link.get('height', 1)

            # Edge links (GMAP adjacency) don't trigger a warp for a segment
            # we're already streamed - only for actual GMAP neighbours.
            is_edge = (lx <= 1 or lx + lw >= 63 or ly <= 1 or ly + lh >= 63)
            dest_level = link.get('dest_level', '')
            is_adjacent = dest_level in c.get_adjacent_levels(level_name)
            if is_edge and is_adjacent:
                continue

            if lx <= tile_x <= lx + lw and ly <= tile_y <= ly + lh:
                return link

        return None

    def _maybe_follow_link(self) -> bool:
        """Auto-warp through a door/link the bot is standing on.

        Parity with pygame_game.py's ActionsMixin._try_link_warp(): link
        warps are CLIENT-initiated (the server only streams link rectangles,
        it never triggers the warp itself), so a headless bot that never
        runs this check can walk straight through/past a door and just keep
        going - confirmed live (chicken_cave_entrance.nw's door at (30,5)
        3x1 was walked onto and past without ever warping).

        Only fires on the rising edge (was-off -> now-on) so a return link
        does not immediately bounce back, and stays suppressed until the bot
        physically moves away from where the last warp dropped it (the new
        level's links can arrive a few frames late).

        Returns True if a warp was triggered.
        """
        if self._link_arrival is not None:
            ax, ay = self._link_arrival
            if abs(self.client.x - ax) >= 1.5 or abs(self.client.y - ay) >= 1.5:
                self._link_arrival = None

        link = self.check_link_collision()
        if not link:
            self._was_on_link = False
            return False
        if self._link_arrival is not None:
            self._was_on_link = True
            return False
        if not self._was_on_link:
            start = time.time()
            self._was_on_link = True
            warped = self.use_link(link)
            self.update(0.3)
            self._link_arrival = (self.client.x, self.client.y)
            self._log_action("auto_link_warp", {"link": link}, warped, start)
            return warped
        return False

    def use_link(self, link: dict) -> bool:
        """Warp through a link (door/cave entrance).

        Wraps client.use_link() for convenience.
        """
        return self.client.use_link(link)

    # ========== Combat ==========

    def sword_attack(self, direction: Optional[int] = None) -> bool:
        """Swing sword."""
        start = time.time()
        result = self.client.sword_attack(direction)
        self.update(0.2)
        self._log_action("sword_attack", {"direction": direction}, result, start)
        return result

    def shoot(self, direction: Optional[int] = None) -> bool:
        """Shoot a projectile (PLI_SHOOT, no ammo cost)."""
        start = time.time()
        result = self.client.shoot(direction)
        self.update(0.2)
        self._log_action("shoot", {"direction": direction}, result, start)
        return result

    def shoot_arrow(self, direction: Optional[int] = None) -> bool:
        """Fire an actual arrow (PLI_ARROWADD, consumes ammo).

        Distinct packet from shoot(): client.shoot() sends PLI_SHOOT (a
        generic projectile, no ammo), client.shoot_arrow() sends PLI_ARROWADD
        and refuses at 0 arrows (pyreborn/client.py:1913).
        """
        start = time.time()
        result = self.client.shoot_arrow(direction=direction)
        self.update(0.2)
        self._log_action("shoot_arrow", {"direction": direction}, result, start)
        return result

    def grab(self) -> bool:
        """Play the grab animation (bush/sign/pot pickup)."""
        start = time.time()
        result = self.client.set_animation('grab')
        self.update(0.1)
        self._log_action("grab", {}, result, start)
        return result

    def drop_bomb(self, power: int = 1) -> bool:
        """Drop bomb."""
        start = time.time()
        result = self.client.drop_bomb(power)
        self.update(0.5)
        self._log_action("drop_bomb", {"power": power}, result, start)
        return result

    def attack_player(self, player_id: int, damage: float = 0.5) -> bool | str:
        """Attack another player."""
        start = time.time()
        if player_id not in self.client.players:
            error = f"no visible player with id {player_id}"
            self._log_action("attack_player", {"id": player_id, "damage": damage}, error, start)
            return error
        result = self.client.attack_player(player_id, damage)
        self.update(0.1)
        self._log_action("attack_player", {"id": player_id, "damage": damage}, result, start)
        return result

    # ========== Items ==========

    def pickup_item(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """Pick up item at position (default: current position)."""
        start = time.time()
        result = self.client.pickup_item(x, y)
        self.update(0.1)
        self._log_action("pickup_item", {"x": x, "y": y}, result, start)
        return result

    # Server-side proximity cap (pygserver items.py:handle_open_chest -
    # abs(player.x - x) <= 3.0 and same for y, in LOCAL level coords). A
    # request outside this is a guaranteed silent no-op server-side, so
    # reject it here instead of burning a round trip.
    CHEST_REACH = 3.0

    def open_chest(self, x: Optional[float] = None, y: Optional[float] = None,
                   poll_timeout: float = 1.0) -> Any:
        """Open a chest.

        With explicit (x, y) - LOCAL level coords, same frame as
        client.chests' keys - opens the chest there if it is in reach.

        Without coords, auto-targets the nearest known chest (from
        client.chests, populated by the level's chest announcements on
        entry) within reach, rather than silently defaulting to the BOT'S
        OWN position: client.open_chest(None, None) resolves x/y to
        player.x/player.y internally and still returns True ("packet sent
        successfully"), even when there is no chest under the player at
        all. Confirmed live via the playtest daemon: open_chest with no
        args logged args {'x': None, 'y': None}, result:true, and no
        chest_items/rupees change - a silent no-op reported as success.

        Returns:
            True  - the chest was confirmed opened (polled client.chests
                    for up to poll_timeout seconds).
            False - a real open request was sent (in reach, resolved
                    coords) but no open confirmation arrived in time.
            str   - no coords given and no chest is known within reach (or
                    at all), or explicit coords are out of reach: an
                    explanation instead of a misleading True.
        """
        start = time.time()
        # LOCAL (0-63) frame, matching client.chests' keys - self.client.x/y
        # are WORLD coords on a GMAP (see walk_to's docstring), so this must
        # wrap the same way bot_map()/_get_tile_at() do for level-local data.
        local_px, local_py = self.client.x % 64, self.client.y % 64
        level_name = self._resolve_level_name(self.client.x, self.client.y)
        chests = self.client.chests_in_level(level_name)

        if x is None or y is None:
            if not chests:
                msg = "no known chests in this level (client.chests is empty)"
                self._log_action("open_chest", {"x": x, "y": y}, msg, start)
                return msg
            # Nearest chest wins; prefer an unopened one over an already-
            # opened one at a similar distance so re-opening the same loot
            # doesn't shadow a genuinely reachable fresh chest.
            (cx, cy), opened = min(
                chests.items(),
                key=lambda item: (item[1], abs(local_px - item[0][0]) +
                                            abs(local_py - item[0][1])))
            if abs(local_px - cx) > self.CHEST_REACH or abs(local_py - cy) > self.CHEST_REACH:
                msg = (f"nearest known chest ({cx},{cy}) is out of reach from "
                      f"({local_px:.1f},{local_py:.1f}); walk closer or pass x=&y=")
                self._log_action("open_chest", {"x": x, "y": y}, msg, start)
                return msg
            x, y = cx, cy
        elif abs(local_px - x) > self.CHEST_REACH or abs(local_py - y) > self.CHEST_REACH:
            msg = (f"chest ({x},{y}) is out of reach from "
                  f"({local_px:.1f},{local_py:.1f}); reach is {self.CHEST_REACH} tiles")
            self._log_action("open_chest", {"x": x, "y": y}, msg, start)
            return msg

        self.client.open_chest(x, y)

        # Report success ONLY if the chest actually opened - poll
        # client.chests briefly for the server's confirmation rather than
        # trusting "packet sent" as "chest opened" (see docstring above).
        deadline = time.time() + poll_timeout
        opened_now = self.client.get_chest_opened(level_name, x, y)
        while not opened_now and time.time() < deadline:
            self.update(0.1)
            opened_now = self.client.get_chest_opened(level_name, x, y)

        self._log_action("open_chest", {"x": x, "y": y}, opened_now, start)
        return opened_now

    # ========== Communication ==========

    def say(self, message: str) -> bool:
        """Send chat message."""
        start = time.time()
        result = self.client.say(message)
        self.update(0.1)
        self._log_action("say", {"message": message}, result, start)
        return result

    def say_and_wait_echo(self, message: str, timeout: float = 2.0) -> bool:
        """Send chat and wait for echo. Returns True if echo received."""
        start = time.time()
        initial_count = len(self.chat_received)

        self.client.say(message)

        # Wait for echo
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.update(0.1)
            # Check if we received the message back
            for pid, msg, ts in self.chat_received[initial_count:]:
                if message in msg:
                    self._log_action("say_and_wait_echo", {"message": message}, True, start)
                    return True

        self._add_issue("LOW", "chat", f"Chat echo not received: {message}")
        self._log_action("say_and_wait_echo", {"message": message}, False, start)
        return False

    def send_pm(self, player_id: int, message: str) -> bool:
        """Send private message."""
        start = time.time()
        result = self.client.send_pm(player_id, message)
        self.update(0.1)
        self._log_action("send_pm", {"to": player_id, "message": message}, result, start)
        return result

    # ========== Warping ==========

    def warp_to(self, level_name: str, x: float = 30.0, y: float = 30.0) -> bool:
        """Warp to a level."""
        start = time.time()
        old_level = self.level
        result = self.client.warp_to_level(level_name, x, y)

        # Wait for level to load. Uses self.level (position-derived), not
        # client._current_level_name directly: warping onto a GMAP segment
        # triggers the same adjacent-segment streaming burst that corrupts
        # _current_level_name (see _resolve_level_name) - checking that raw
        # field here made warp_to() spuriously report failure/timeout for a
        # warp that actually succeeded.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            self.update(0.1)
            if self.level == level_name:
                break

        success = self.level == level_name
        if not success:
            self._add_issue("MEDIUM", "warp",
                           f"Warp failed: {old_level} -> {level_name}")

        self._log_action("warp_to", {"level": level_name, "x": x, "y": y}, success, start)
        return success

    def warp_to_checked(self, level_name: str, x: float = 30.0, y: float = 30.0,
                        force: bool = False) -> Any:
        """warp_to() that refuses a destination which looks blocking.

        Returns the refusal as a string instead of stranding the bot on a wall
        (an LLM playtest agent then has something actionable instead of a bot
        that can no longer move). Force=True skips the check.
        """
        if not force:
            # Prefer the live/active board (client.tiles) when warping within
            # the bot's own current level: client.levels[level] can hold a
            # WRONG board for a level on a GMAP world - confirmed live,
            # client.levels['chicken1.nw'] held a neighbouring segment's tiles
            # while client.tiles (and self.level, via _resolve_level_name)
            # correctly tracked chicken1.nw. Same root cause as the level-name
            # corruption _resolve_level_name works around. levels[level] is
            # still the only thing available for a level the bot isn't
            # currently on, so that's a best-effort fallback with the same
            # caveat.
            def board_lookup(lvl):
                if lvl == self.level:
                    return self.client.tiles
                return self.client.levels.get(lvl)

            problem = _validate_warp_dest(level_name, x, y, board_lookup, self.client)
            if problem:
                self._log_action("warp_to_checked",
                                 {"level": level_name, "x": x, "y": y},
                                 problem, time.time())
                return problem
        return self.warp_to(level_name, x, y)

    def use_nearest_door(self) -> bool:
        """Use the nearest door link."""
        start = time.time()
        link = self.check_link_collision()
        if link:
            result = self.client.use_link(link)
            self.update(0.5)
            self._log_action("use_door", {"link": link}, result, start)
            return result

        self._log_action("use_door", {}, False, start)
        return False

    # ========== NPC Interaction ==========

    def get_nearest_npc(self) -> Optional[int]:
        """Get ID of nearest NPC."""
        if not self.client.npcs:
            return None

        min_dist = float('inf')
        nearest_id = None

        for npc_id, npc in self.client.npcs.items():
            dx = npc.get('x', 0) - self.client.x
            dy = npc.get('y', 0) - self.client.y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_id = npc_id

        return nearest_id

    def interact_with_npc(self, npc_id: int) -> bool:
        """Walk to and interact with an NPC."""
        start = time.time()
        if npc_id not in self.client.npcs:
            self._log_action("interact_npc", {"id": npc_id}, False, start)
            return False

        npc = self.client.npcs[npc_id]
        x, y = npc.get('x', 0), npc.get('y', 0)

        # Walk to NPC
        if not self.walk_to(x, y - 1, timeout=5.0):  # Stand in front
            self._log_action("interact_npc", {"id": npc_id}, False, start)
            return False

        # Trigger action (pressing towards NPC)
        self.client.triggeraction("npcclick", x, y, npc_id)
        self.update(0.2)

        self._log_action("interact_npc", {"id": npc_id}, True, start)
        return True

    # ========== Flags ==========

    def set_flag(self, name: str, value: str = "") -> bool:
        """Set a player flag."""
        start = time.time()
        result = self.client.set_flag(name, value)
        self.update(0.1)
        self._log_action("set_flag", {"name": name, "value": value}, result, start)
        return result

    # ========== State Queries ==========

    @property
    def x(self) -> float:
        return self.client.x

    @property
    def y(self) -> float:
        return self.client.y

    @property
    def level(self) -> str:
        """The level the bot is actually standing in.

        Uses _resolve_level_name() rather than client._current_level_name
        directly - see that method's docstring for why the raw field is
        unreliable on a GMAP.
        """
        return self._resolve_level_name()

    @property
    def hearts(self) -> float:
        return self.client.player.hearts

    @property
    def players(self) -> Dict[int, dict]:
        return self.client.players

    @property
    def npcs(self) -> Dict[int, dict]:
        return self.client.npcs

    @property
    def items(self) -> Dict[Tuple[float, float], str]:
        return self.client.items_in_level(self._resolve_level_name())

    @property
    def tiles(self) -> List[int]:
        return self.client.tiles

    # ========== Issue Retrieval ==========

    def get_issues(self, severity: Optional[str] = None) -> List[Issue]:
        """Get detected issues, optionally filtered by severity."""
        if severity:
            return [i for i in self.issues if i.severity == severity]
        return self.issues

    def clear_tracking(self):
        """Clear all tracking data (issues, logs, callbacks)."""
        self.issues.clear()
        self.action_log.clear()
        self.position_history.clear()
        self.chat_received.clear()
        self.hurt_received.clear()
        self.pm_received.clear()

    # ========== Action Registry ==========

    #: Named actions a transport (playtest_daemon's /act) can drive, with the
    #: coercion for each parameter. Keys and parameter names are the daemon's
    #: HTTP command/query names, which LLM playtest agents' prompts are
    #: written against - see PLAYTEST_BRIEF.md; changing one is a breaking
    #: change for them.
    ACTIONS: Dict[str, BotAction] = {
        action.name: action for action in (
            BotAction('move', 'move', (
                ActionParam('dx', _move_component),
                ActionParam('dy', _move_component),
                ActionParam('follow_links', _as_flag(True)))),
            BotAction('walkto', 'walk_to', (
                ActionParam('x', _as_float(None), 'target_x'),
                ActionParam('y', _as_float(None), 'target_y'),
                ActionParam('follow_links', _as_flag(True))),
                fixed=(('timeout', 8.0),)),
            BotAction('travel', 'travel_to', (
                ActionParam('level', _as_str(None), 'level_name'),
                ActionParam('x', _as_opt_coord),
                ActionParam('y', _as_opt_coord))),
            BotAction('say', 'say_and_wait_echo', (
                ActionParam('msg', _as_str(''), 'message'),)),
            BotAction('sword', 'sword_attack', (
                ActionParam('dir', _as_opt_int, 'direction'),)),
            BotAction('bomb', 'drop_bomb', (
                ActionParam('power', _as_int(1)),)),
            BotAction('arrow', 'shoot_arrow', (
                ActionParam('dir', _as_opt_int, 'direction'),)),
            BotAction('grab', 'grab'),
            BotAction('attack', 'attack_player', (
                ActionParam('pid', _as_int(None), 'player_id'),)),
            BotAction('pm', 'send_pm', (
                ActionParam('pid', _as_int(None), 'player_id'),
                ActionParam('msg', _as_str(''), 'message'))),
            BotAction('warp', 'warp_to_checked', (
                ActionParam('level', _as_str(None), 'level_name'),
                ActionParam('x', _as_float(30)),
                ActionParam('y', _as_float(30)),
                ActionParam('force', _as_flag(False)))),
            BotAction('open_chest', 'open_chest', (
                ActionParam('x', _as_opt_coord),
                ActionParam('y', _as_opt_coord))),
            BotAction('pickup', 'pickup_item', (
                ActionParam('x', _as_opt_coord),
                ActionParam('y', _as_opt_coord))),
        )
    }
