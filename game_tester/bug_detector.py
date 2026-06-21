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
    def check_position_sync(client, expected_x: float, expected_y: float,
                            tolerance: float = 0.5) -> CheckResult:
        """Check if client position matches expected position."""
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
                            max_val: float = 64.0) -> CheckResult:
        """Check if player is out of level bounds."""
        x, y = client.x, client.y

        if x < min_val or x > max_val or y < min_val or y > max_val:
            return CheckResult(
                passed=False,
                message=f"Player out of bounds: ({x:.1f}, {y:.1f})",
                severity="HIGH",
                details={"position": (x, y), "bounds": (min_val, max_val)}
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

    # ========== Communication Checks ==========

    @staticmethod
    def check_chat_echo(sent_message: str,
                        received: List[Tuple[int, str, float]],
                        since_time: float = 0) -> CheckResult:
        """Check if sent chat message was echoed back."""
        recent = [r for r in received if r[2] >= since_time]

        for player_id, message, timestamp in recent:
            if sent_message in message:
                return CheckResult(
                    passed=True,
                    message=f"Chat echo received from player {player_id}",
                    details={"player_id": player_id, "message": message}
                )

        return CheckResult(
            passed=False,
            message=f"Chat not echoed: '{sent_message}'",
            severity="MEDIUM"
        )

    @staticmethod
    def check_pm_delivery(pm_log: List[Tuple[int, str, float]],
                          expected_from: int,
                          expected_message: str,
                          since_time: float = 0) -> CheckResult:
        """Check if PM was received from expected player."""
        recent = [p for p in pm_log if p[2] >= since_time]

        for from_id, message, timestamp in recent:
            if from_id == expected_from and expected_message in message:
                return CheckResult(
                    passed=True,
                    message=f"PM received from player {from_id}",
                    details={"from": from_id, "message": message}
                )

        return CheckResult(
            passed=False,
            message=f"PM not received from player {expected_from}",
            severity="MEDIUM"
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

    @staticmethod
    def check_authenticated(client) -> CheckResult:
        """Check if client is authenticated."""
        if not client.authenticated:
            return CheckResult(
                passed=False,
                message="Client not authenticated",
                severity="HIGH"
            )

        return CheckResult(
            passed=True,
            message=f"Authenticated as {client.player.account}",
            details={"account": client.player.account}
        )

    # ========== Composite Checks ==========

    @staticmethod
    def run_all_checks(client, positions: List[Tuple[float, float, float]] = None,
                       hurt_log: List = None, chat_log: List = None) -> List[CheckResult]:
        """Run all applicable checks and return results."""
        results = []

        # Connection
        results.append(BugDetector.check_connection(client))

        # Data
        results.append(BugDetector.check_level_loaded(client))
        results.append(BugDetector.check_tiles_valid(client))
        results.append(BugDetector.check_out_of_bounds(client))
        results.append(BugDetector.check_players_visible(client))
        results.append(BugDetector.check_npcs_received(client))
        results.append(BugDetector.check_items_on_ground(client))

        # Position history checks
        if positions and len(positions) >= 10:
            results.append(BugDetector.check_stuck_detection(positions))
            results.append(BugDetector.check_position_discontinuity(positions))

        return results
