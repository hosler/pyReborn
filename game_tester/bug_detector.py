"""
BugDetector - Utilities to detect anomalies during gameplay.

Provides static methods for checking various game state issues.
"""

from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class CheckResult:
    """Result of a bug detection check."""
    passed: bool
    message: str
    severity: str = "LOW"  # HIGH, MEDIUM, LOW, WARN
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class BugDetector:
    """
    Static utility class for detecting anomalies.

    Usage:
        result = BugDetector.check_level_loaded(bot.client)
        if not result.passed:
            print(f"Issue: {result.message}")
    """

    # ========== Position Checks ==========

    @staticmethod
    def to_world_pos(x: float, y: float, level: Optional[str],
                     gmap_grid: Optional[Dict[Tuple[int, int], str]]) -> Tuple[float, float]:
        """Convert a level-local (0-63) position to gmap world coords.

        Mirrors the `world = local + grid_position * 64` convention used
        throughout this codebase - see pyreborn/client.py's
        `_update_npc_world_coords` and `GameBot._resolve_level_name` for the
        same lookup (level name -> grid cell in gmap_grid). A value that's
        already world (>=64 or negative - only possible from a high-precision
        X2/Y2 prop) is passed through unchanged, so this is safe to call on
        positions that might already be normalized. Returns (x, y) unchanged
        if `level` isn't in `gmap_grid` (non-gmap, or an unknown segment).
        """
        if not gmap_grid or not level:
            return x, y
        for (gx, gy), name in gmap_grid.items():
            if name == level:
                wx = x if (x >= 64 or x < 0) else x + gx * 64
                wy = y if (y >= 64 or y < 0) else y + gy * 64
                return wx, wy
        return x, y

    @staticmethod
    def check_position_sync(client, expected_x: float, expected_y: float,
                            tolerance: float = 0.5) -> CheckResult:
        """Check if client position matches expected position.

        Both `client.x`/`client.y` and `expected_x`/`expected_y` must
        already be in the SAME coordinate frame (both world, or both
        level-local) - this check is a plain delta comparison and has no
        way to detect a frame mismatch on its own. On a gmap, a level-local
        (0-63) other-player position compared against a world position (as
        `pyreborn.Client.x`/`.y` are on a gmap - see PLO_PLAYERWARP2's
        handler) looks like a huge, spurious desync. Callers with a
        level-local value should normalize it first via `to_world_pos()`
        (see multi_bot.py's run_visibility_test for the pattern).
        """
        dx = abs(client.x - expected_x)
        dy = abs(client.y - expected_y)

        if dx > tolerance or dy > tolerance:
            return CheckResult(
                passed=False,
                message=f"Position desync: expected ({expected_x:.1f}, {expected_y:.1f}), "
                       f"got ({client.x:.1f}, {client.y:.1f})",
                severity="MEDIUM",
                details={"expected": (expected_x, expected_y),
                        "actual": (client.x, client.y),
                        "delta": (dx, dy)}
            )

        return CheckResult(passed=True, message="Position in sync")

    @staticmethod
    def check_stuck_detection(positions: List[Tuple[float, float, float]],
                              window: int = 10, tolerance: float = 0.1) -> CheckResult:
        """
        Check if bot is stuck based on position history.

        Args:
            positions: List of (x, y, timestamp) tuples
            window: Number of recent positions to check
            tolerance: Movement threshold to consider "stuck"
        """
        if len(positions) < window:
            return CheckResult(passed=True, message="Not enough position data")

        recent = positions[-window:]
        unique_positions = set()
        for x, y, _ in recent:
            unique_positions.add((round(x / tolerance), round(y / tolerance)))

        if len(unique_positions) <= 1:
            x, y, _ = recent[-1]
            return CheckResult(
                passed=False,
                message=f"Bot stuck at ({x:.1f}, {y:.1f}) for {window} updates",
                severity="WARN",
                details={"position": (x, y), "window": window}
            )

        return CheckResult(passed=True, message="Bot is moving")

    @staticmethod
    def check_out_of_bounds(client, min_val: float = 0.0,
                            max_val: Optional[float] = None) -> CheckResult:
        """Check if player is out of level bounds.

        A standalone level is always local coordinates 0-64. On a GMAP,
        though, world coordinates legitimately span the whole stitched grid
        (gmap_width/gmap_height segments of 64 tiles each) - a hardcoded 0-64
        max here flagged every player past the first segment as "out of
        bounds". Only use client.in_gmap_segment (an actual grid segment, not
        e.g. a standalone house/cave reached via a door while a gmap happens
        to be loaded - see Client.in_gmap_segment) to size the check; an
        explicit max_val always wins.
        """
        x, y = client.x, client.y
        x_min = y_min = min_val

        if max_val is not None:
            x_max = y_max = max_val
        elif getattr(client, "in_gmap_segment", False):
            x_max = client.gmap_width * 64
            y_max = client.gmap_height * 64
        else:
            x_max = y_max = 64.0

        if x < x_min or x > x_max or y < y_min or y > y_max:
            return CheckResult(
                passed=False,
                message=f"Player out of bounds: ({x:.1f}, {y:.1f})",
                severity="HIGH",
                details={"position": (x, y), "bounds": (x_min, x_max, y_min, y_max)}
            )

        return CheckResult(passed=True, message="Position in bounds")

    @staticmethod
    def check_position_discontinuity(positions: List[Tuple[float, float, float]],
                                     max_jump: float = 5.0) -> CheckResult:
        """Check for sudden position jumps (teleportation bugs)."""
        if len(positions) < 2:
            return CheckResult(passed=True, message="Not enough data")

        for i in range(1, len(positions)):
            x1, y1, t1 = positions[i - 1]
            x2, y2, t2 = positions[i]

            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > max_jump:
                return CheckResult(
                    passed=False,
                    message=f"Position jump detected: ({x1:.1f}, {y1:.1f}) -> "
                           f"({x2:.1f}, {y2:.1f}) = {dist:.1f} tiles",
                    severity="WARN",
                    details={"from": (x1, y1), "to": (x2, y2), "distance": dist}
                )

        return CheckResult(passed=True, message="No position jumps")

    # ========== Data Integrity Checks ==========

    @staticmethod
    def check_level_loaded(client) -> CheckResult:
        """Check if level data is loaded."""
        level_name = client._current_level_name
        has_tiles = client.tiles is not None and len(client.tiles) > 0

        if not level_name:
            return CheckResult(
                passed=False,
                message="Level name not received",
                severity="HIGH"
            )

        if not has_tiles:
            return CheckResult(
                passed=False,
                message=f"Level {level_name} has no tile data",
                severity="HIGH",
                details={"level": level_name}
            )

        return CheckResult(
            passed=True,
            message=f"Level {level_name} loaded with {len(client.tiles)} tiles",
            details={"level": level_name, "tile_count": len(client.tiles)}
        )

    @staticmethod
    def check_tiles_valid(client) -> CheckResult:
        """Check if tile data looks valid."""
        if not client.tiles:
            return CheckResult(
                passed=False,
                message="No tile data",
                severity="HIGH"
            )

        expected_count = 64 * 64  # 4096 tiles
        if len(client.tiles) != expected_count:
            return CheckResult(
                passed=False,
                message=f"Unexpected tile count: {len(client.tiles)} != {expected_count}",
                severity="MEDIUM",
                details={"actual": len(client.tiles), "expected": expected_count}
            )

        # Check for reasonable tile values (most should be in valid range)
        invalid_count = sum(1 for t in client.tiles if t < 0 or t > 65535)
        if invalid_count > 0:
            return CheckResult(
                passed=False,
                message=f"{invalid_count} invalid tile values",
                severity="LOW",
                details={"invalid_count": invalid_count}
            )

        return CheckResult(passed=True, message="Tiles valid")

    @staticmethod
    def check_players_visible(client, expected_count: int = 0) -> CheckResult:
        """Check if expected number of other players are visible."""
        actual = len(client.players)

        if expected_count > 0 and actual < expected_count:
            return CheckResult(
                passed=False,
                message=f"Expected {expected_count} players, found {actual}",
                severity="MEDIUM",
                details={"expected": expected_count, "actual": actual}
            )

        return CheckResult(
            passed=True,
            message=f"{actual} players visible",
            details={"count": actual, "players": list(client.players.keys())}
        )

    @staticmethod
    def check_npcs_received(client, expected_min: int = 0) -> CheckResult:
        """Check if NPCs are visible in level."""
        actual = len(client.npcs)

        if expected_min > 0 and actual < expected_min:
            return CheckResult(
                passed=False,
                message=f"Expected at least {expected_min} NPCs, found {actual}",
                severity="LOW",
                details={"expected_min": expected_min, "actual": actual}
            )

        if actual == 0:
            return CheckResult(
                passed=True,
                message="No NPCs in level (may be expected)",
                severity="WARN"
            )

        return CheckResult(
            passed=True,
            message=f"{actual} NPCs visible",
            details={"count": actual}
        )

    @staticmethod
    def check_items_on_ground(client) -> CheckResult:
        """Check items state."""
        count = len(client.items)
        return CheckResult(
            passed=True,
            message=f"{count} items on ground",
            details={"count": count, "items": list(client.items.items())[:10]}
        )

    # ========== Combat Checks ==========

    @staticmethod
    def check_damage_applied(old_hearts: float, new_hearts: float,
                             expected_damage: float, tolerance: float = 0.1) -> CheckResult:
        """Check if expected damage was applied."""
        actual_damage = old_hearts - new_hearts

        if abs(actual_damage - expected_damage) > tolerance:
            return CheckResult(
                passed=False,
                message=f"Damage mismatch: expected {expected_damage}, "
                       f"got {actual_damage} ({old_hearts} -> {new_hearts})",
                severity="HIGH",
                details={"expected": expected_damage, "actual": actual_damage,
                        "old_hearts": old_hearts, "new_hearts": new_hearts}
            )

        return CheckResult(
            passed=True,
            message=f"Damage applied correctly: {actual_damage}",
            details={"damage": actual_damage}
        )

    @staticmethod
    def check_hurt_callback_fired(hurt_log: List[Tuple[int, float, float]],
                                  since_time: float = 0) -> CheckResult:
        """Check if hurt callback was fired since given time."""
        recent = [h for h in hurt_log if h[2] >= since_time]

        if not recent:
            return CheckResult(
                passed=False,
                message="No hurt callback received",
                severity="HIGH"
            )

        attacker_id, damage, timestamp = recent[-1]
        return CheckResult(
            passed=True,
            message=f"Hurt callback: {damage} damage from player {attacker_id}",
            details={"attacker": attacker_id, "damage": damage}
        )

    # ========== Connection Checks ==========

    @staticmethod
    def check_connection(client) -> CheckResult:
        """Check if client is still connected."""
        if not client.connected:
            return CheckResult(
                passed=False,
                message="Client disconnected unexpectedly",
                severity="HIGH"
            )

        return CheckResult(passed=True, message="Connected")
