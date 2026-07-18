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
from pyreborn.tiletypes import TileType, get_tile_type, is_blocking, is_water


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
                 password: str = "testpass"):
        self.name = name
        self.host = host
        self.port = port
        self.password = password

        self.client = Client(host, port, version="6.037")
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
        self._last_x = 0.0
        self._last_y = 0.0
        self._stuck_count = 0
        self._connected = False
        self._stuck_warned = False  # Only warn once when stuck

        # Parity with pygame client: swimming state
        self.is_swimming = False

        # Door/link auto-traversal state (parity with pygame_game.py's
        # ActionsMixin._try_link_warp): rising-edge latch so a link only
        # fires the moment we step onto it, plus a post-warp suppression so
        # we don't immediately bounce back through a return link or an
        # overlapping link at the arrival point. See _maybe_follow_link().
        self._was_on_link = False
        self._link_arrival: Optional[Tuple[float, float]] = None

        # Collision settings (match pygame_game.py)
        self._feet_offset_x = 1.0  # Center of 2-tile wide sprite
        self._feet_offset_y = 3.0  # Bottom of 3-tile tall sprite

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
        """Connect and login to server."""
        start = time.time()
        try:
            self.client.connect()
            if not self.client.login(self.name, self.password, timeout=timeout):
                self._add_issue("HIGH", "connect", f"Login failed for {self.name}")
                return False

            # Poll until we get level data
            deadline = time.time() + timeout
            while time.time() < deadline:
                self.client.update(timeout=0.1)
                if self.client._current_level_name and len(self.client.tiles) > 0:
                    break
                time.sleep(0.05)

            self._connected = True
            self._last_x = self.client.x
            self._last_y = self.client.y
            self._log_action("connect", {"name": self.name}, True, start)
            return True

        except Exception as e:
            self._add_issue("HIGH", "connect", f"Connection error: {e}")
            self._log_action("connect", {"name": self.name}, False, start)
            return False

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

    def move(self, dx: int, dy: int, check_collision: bool = True,
             follow_links: bool = True) -> bool:
        """Move in direction (dx, dy in -1, 0, 1).

        PARITY NOTE: This matches pygame_game.py:_move() which:
        1. Checks collision 1 full tile ahead (x + dx, y + dy)
        2. But only moves 0.25 tiles per call via client.move()

        This "look ahead" approach allows smooth movement near walls
        by checking if the destination is clear, not every micro-step.

        Args:
            dx: X direction (-1, 0, 1)
            dy: Y direction (-1, 0, 1)
            check_collision: If True, check for blocking tiles (parity with pygame)
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
        old_x, old_y = self.client.x, self.client.y

        # PARITY: pygame checks 1 full tile ahead, not 0.25 tile step
        # This matches pygame_game.py line 782-783:
        #   dest_x = self.client.x + dx
        #   dest_y = self.client.y + dy
        dest_x = old_x + dx  # Full tile lookahead
        dest_y = old_y + dy

        # Check collision BEFORE moving (parity with pygame_game.py)
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
                follow_links: bool = True) -> bool:
        """
        Walk to a target position using simple pathfinding.

        target_x/target_y are in the same frame as self.x/self.y: WORLD
        coordinates on a GMAP (local + grid*64, matching client.x/client.y
        and the /state x/y the playtest daemon reports), local (0-63) on a
        plain level. self.client.x/y already track world coords across a
        GMAP without wrapping (client.move() never resets to local - it only
        sends local coords over the wire), so this comparison is safe as
        long as callers pass the same frame - do not pass a local (0-63)
        target while on a GMAP.

        follow_links: forwarded to move() - if True (default) walking into a
        door/link along the way auto-warps through it, same as the real
        client. If that happens mid-walk the target is almost certainly no
        longer reachable in the new level, so this returns False rather than
        continuing to burn the timeout comparing against a stale target.

        Returns True if reached target, False if stuck/timeout/warped away.
        """
        start = time.time()
        tolerance = 0.5
        start_level = self.level

        while time.time() - start < timeout:
            dx = target_x - self.client.x
            dy = target_y - self.client.y

            # Check if arrived
            if abs(dx) < tolerance and abs(dy) < tolerance:
                self._log_action("walk_to", {"x": target_x, "y": target_y}, True, start)
                return True

            # Determine direction
            move_dx = 0 if abs(dx) < tolerance else (1 if dx > 0 else -1)
            move_dy = 0 if abs(dy) < tolerance else (1 if dy > 0 else -1)

            # Try to move
            old_x, old_y = self.client.x, self.client.y
            self.move(move_dx, move_dy, follow_links=follow_links)

            if follow_links and self.level != start_level:
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
                        self.move(0, step_y, follow_links=follow_links)
                        self.move(0, step_y, follow_links=follow_links)
                    if move_dy != 0:
                        step_x = 1 if dx >= 0 else -1
                        self.move(step_x, 0, follow_links=follow_links)
                        self.move(step_x, 0, follow_links=follow_links)
                    self._stuck_count = 0
            else:
                self._stuck_count = 0

        self._add_issue("LOW", "movement", f"walk_to timeout: target=({target_x}, {target_y})")
        self._log_action("walk_to", {"x": target_x, "y": target_y}, False, start)
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
        """Resolve which level owns a world position - robust to
        client._current_level_name being a poor proxy for "the level the
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
        gmap - that's the root cause behind walk_to() reading blocking data
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
        if c.is_gmap and c.gmap_grid:
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
        """Check if a position is blocked by tiles.

        (x, y) here is already the full-tile-ahead destination (see move()'s
        parity note), so this probes the LEADING EDGE of the sprite's
        footprint in the direction of travel, not a fixed point. Duplicated
        inline rather than importing pyreborn/game/collision.py's box-based
        _is_position_blocked (left/right 0.4-1.6, top/bottom 2.0-3.0 from the
        sprite's top-left) to avoid a pygame-dependent import in the headless
        bot; the sprite is 2 tiles wide x 3 tall, top-left anchored.

        The probed points are the leading edge of collision.py's FEET box
        {x+0.4..x+1.6} x {y+2.0..y+3.0} (collision is feet-only, classic
        style: the head/torso may overlap walls). A single feet-center
        point (the previous version) missed walls that clip only one side
        of the box, and probing the head row for upward moves blocked the
        bot where the real client walks.
        """
        box_l, box_r, box_cx = 0.4, 1.6, 1.0
        box_t, box_b = 2.0, 3.0
        check_offsets = []

        if dx < 0:      # Moving left: leading edge is the box's left column
            check_offsets += [(box_l, box_t), (box_l, box_b)]
        elif dx > 0:    # Moving right: the box's right column
            check_offsets += [(box_r, box_t), (box_r, box_b)]

        if dy < 0:      # Moving up: leading edge is the box's top row
            check_offsets += [(box_l, box_t), (box_cx, box_t), (box_r, box_t)]
        elif dy > 0:    # Moving down: the box's bottom (feet) row
            check_offsets += [(box_l, box_b), (box_cx, box_b), (box_r, box_b)]

        # If no direction, just check the feet center (standing still)
        if not check_offsets:
            check_offsets = [(box_cx, box_b)]

        for ox, oy in check_offsets:
            check_x = x + ox
            check_y = y + oy
            tile_id = self._get_tile_at(check_x, check_y)
            if is_blocking(tile_id):
                return True

        return False

    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the position is in water."""
        tile_id = self._get_tile_at(x, y)
        return is_water(tile_id)

    def _update_swimming_state(self):
        """Update swimming state based on current position.

        Matches pygame_game.py:_update_swimming_state() for parity: sample the
        player's FEET (sprite top-left + (1.0, 2.5)), not the top-left corner.
        """
        self.is_swimming = self._check_water_at_position(self.client.x + 1.0,
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

        # Sample the player's body down the centre column - head, mid, feet,
        # bottom-of-feet - and the full horizontal foot span, matching
        # client.check_link_collision()'s box (see that method's docstring
        # for why single-point sampling misses off-centre/edge overlaps).
        px, py = c.x, c.y
        span_left = px % 64
        span_right = span_left + 2.0
        body_ys = [(py + d) % 64 for d in (0.5, 1.5, 2.5, 3.0)]

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

            if span_left < lx + lw and span_right > lx and \
                    any(ly <= by < ly + lh for by in body_ys):
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
        doesn't immediately bounce back, and stays suppressed until the bot
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
        """Shoot arrow."""
        start = time.time()
        result = self.client.shoot(direction)
        self.update(0.2)
        self._log_action("shoot", {"direction": direction}, result, start)
        return result

    def drop_bomb(self, power: int = 1) -> bool:
        """Drop bomb."""
        start = time.time()
        result = self.client.drop_bomb(power)
        self.update(0.5)
        self._log_action("drop_bomb", {"power": power}, result, start)
        return result

    def attack_player(self, player_id: int, damage: float = 0.5) -> bool:
        """Attack another player."""
        start = time.time()
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

    def open_chest(self, x: Optional[float] = None, y: Optional[float] = None) -> bool:
        """Open chest at position."""
        start = time.time()
        result = self.client.open_chest(x, y)
        self.update(0.1)
        self._log_action("open_chest", {"x": x, "y": y}, result, start)
        return result

    def pickup_all_items(self) -> int:
        """Try to pick up all visible items. Returns count picked up."""
        start = time.time()
        count = 0
        for (x, y), item_type in list(self.client.items.items()):
            if self.walk_to(x, y, timeout=5.0):
                if self.pickup_item(x, y):
                    count += 1
        self._log_action("pickup_all_items", {}, count, start)
        return count

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
        return self.client.items

    @property
    def tiles(self) -> List[int]:
        return self.client.tiles

    # ========== Issue Retrieval ==========

    def get_issues(self, severity: Optional[str] = None) -> List[Issue]:
        """Get detected issues, optionally filtered by severity."""
        if severity:
            return [i for i in self.issues if i.severity == severity]
        return self.issues

    def get_action_log(self, action: Optional[str] = None) -> List[ActionLog]:
        """Get action log, optionally filtered by action type."""
        if action:
            return [a for a in self.action_log if a.action == action]
        return self.action_log

    def clear_tracking(self):
        """Clear all tracking data (issues, logs, callbacks)."""
        self.issues.clear()
        self.action_log.clear()
        self.position_history.clear()
        self.chat_received.clear()
        self.hurt_received.clear()
        self.pm_received.clear()
