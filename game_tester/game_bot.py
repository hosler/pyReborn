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

        # Collision settings (match pygame_game.py)
        self._feet_offset_x = 1.0  # Center of 2-tile wide sprite
        self._feet_offset_y = 3.0  # Bottom of 3-tile tall sprite

    def _setup_callbacks(self):
        """Setup client callbacks for tracking."""
        self.client.on_chat = self._on_chat
        self.client.on_hurt = self._on_hurt
        self.client.on_pm = self._on_pm

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

    def move(self, dx: int, dy: int, check_collision: bool = True) -> bool:
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
            # Position is blocked - don't move
            self._log_action("move", {"dx": dx, "dy": dy, "blocked": True}, False, start)
            return False

        # Move only 0.25 tiles (client.move uses step=0.25 by default)
        result = self.client.move(dx, dy)
        self.update(0.05)

        # Update swimming state after move (parity with pygame)
        self._update_swimming_state()

        # Check for door link at new position
        door_link = self.check_link_collision()
        if door_link:
            # Note: Don't auto-warp like pygame does - let test control this
            pass

        # Check if actually moved
        moved = (abs(self.client.x - old_x) > 0.01 or
                 abs(self.client.y - old_y) > 0.01)

        self._log_action("move", {"dx": dx, "dy": dy}, moved, start)
        return moved

    def walk_to(self, target_x: float, target_y: float, timeout: float = 10.0) -> bool:
        """
        Walk to a target position using simple pathfinding.

        Returns True if reached target, False if stuck/timeout.
        """
        start = time.time()
        tolerance = 0.5

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
            self.move(move_dx, move_dy)

            # Check if stuck
            if abs(self.client.x - old_x) < 0.01 and abs(self.client.y - old_y) < 0.01:
                self._stuck_count += 1
                if self._stuck_count > 10:
                    # Try alternate route
                    if move_dx != 0:
                        self.move(0, 1)  # Try going around
                        self.move(0, 1)
                    if move_dy != 0:
                        self.move(1, 0)
                        self.move(1, 0)
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

    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates).

        Matches pygame_game.py:_get_tile_at() for parity.
        """
        # Get the current level's tiles
        if self.client.is_gmap:
            level_name = self.client._current_level_name
            tiles = self.client.levels.get(level_name, self.client.tiles)
        else:
            tiles = self.client.tiles

        if not tiles:
            return 0  # Default to walkable

        # Convert to tile indices
        tx = int(x) % 64
        ty = int(y) % 64

        # Bounds check
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return 0

        tile_idx = ty * 64 + tx
        if tile_idx < 0 or tile_idx >= len(tiles):
            return 0

        return tiles[tile_idx]

    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a position is blocked by tiles.

        Matches pygame_game.py:_is_position_blocked() for parity.

        Player world position (x, y) is TOP-LEFT of sprite.
        Collision happens at feet: +1 tile right, +3 tiles down from position.
        """
        check_offsets = []

        # Check at center (feet position) - same as pygame
        if dx < 0:  # Moving left
            check_offsets.append((self._feet_offset_x, self._feet_offset_y))
        elif dx > 0:  # Moving right
            check_offsets.append((self._feet_offset_x, self._feet_offset_y))

        if dy < 0:  # Moving up
            check_offsets.append((self._feet_offset_x, self._feet_offset_y))
        elif dy > 0:  # Moving down
            check_offsets.append((self._feet_offset_x, self._feet_offset_y))

        # If no direction, just check feet position (standing still)
        if not check_offsets:
            check_offsets = [(self._feet_offset_x, self._feet_offset_y)]

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

        Matches pygame_game.py:_update_swimming_state() for parity.
        """
        self.is_swimming = self._check_water_at_position(self.client.x, self.client.y)

    def check_link_collision(self) -> Optional[dict]:
        """Check if bot is standing on a door/warp link.

        Returns the link dict if on a door link, None otherwise.
        Wraps client.check_link_collision() for convenience.
        """
        return self.client.check_link_collision()

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
        old_level = self.client._current_level_name
        result = self.client.warp_to_level(level_name, x, y)

        # Wait for level to load
        deadline = time.time() + 5.0
        while time.time() < deadline:
            self.update(0.1)
            if self.client._current_level_name == level_name:
                break

        success = self.client._current_level_name == level_name
        if not success:
            self._add_issue("MEDIUM", "warp",
                           f"Warp failed: {old_level} -> {level_name}")

        self._log_action("warp_to", {"level": level_name, "x": x, "y": y}, success, start)
        return success

    def use_nearest_door(self) -> bool:
        """Use the nearest door link."""
        start = time.time()
        link = self.client.check_link_collision()
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
        return self.client._current_level_name

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
