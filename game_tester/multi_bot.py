"""
MultiBotTest - Coordinate multiple bots for interaction testing.

Tests player visibility, PvP combat, and chat between players.
"""

import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .game_bot import GameBot, Issue
from .bug_detector import BugDetector, CheckResult


@dataclass
class MultiTestResult:
    """Result of a multi-bot test."""
    name: str
    passed: bool
    duration: float
    details: str
    issues: List[Issue]


class MultiBotTest:
    """
    Coordinate multiple bots for interaction testing.

    Usage:
        test = MultiBotTest(3, "localhost", 14900)
        test.connect_all()
        result = test.run_visibility_test()
        test.disconnect_all()
    """

    def __init__(self, num_bots: int, host: str = "localhost", port: int = 14900):
        self.host = host
        self.port = port
        self.bots: List[GameBot] = []

        for i in range(num_bots):
            bot = GameBot(f"testbot{i + 1}", host, port)
            self.bots.append(bot)

    def connect_all(self, timeout: float = 10.0) -> bool:
        """Connect all bots to server."""
        success = True
        for bot in self.bots:
            if not bot.connect(timeout=timeout):
                success = False
        return success

    def disconnect_all(self):
        """Disconnect all bots."""
        for bot in self.bots:
            bot.disconnect()

    def update_all(self, duration: float = 0.1):
        """Update all bots."""
        for bot in self.bots:
            bot.update(duration / len(self.bots))

    def get_all_issues(self) -> List[Issue]:
        """Get all issues from all bots."""
        issues = []
        for bot in self.bots:
            issues.extend(bot.issues)
        return issues

    # ========== Visibility Tests ==========

    def run_visibility_test(self) -> MultiTestResult:
        """
        Test that bots can see each other.

        Move bot 0 to a position, check if bot 1 sees them.
        """
        start = time.time()
        issues = []

        if len(self.bots) < 2:
            return MultiTestResult(
                name="visibility",
                passed=False,
                duration=0,
                details="Need at least 2 bots",
                issues=[]
            )

        bot0, bot1 = self.bots[0], self.bots[1]

        # Move bot0 to known position
        target_x, target_y = 32.0, 32.0
        bot0.walk_to(target_x, target_y, timeout=5.0)
        # Force a position broadcast: the server only relays our position to
        # others when it changes, so if bot0 couldn't move (e.g. spawned against
        # a wall) bot1 would never learn where it is. This makes the test robust
        # regardless of spawn/collision state.
        bot0.client.send_position()
        self.update_all(0.3)

        # Give time for position to sync - retry several times
        found = False
        found_player_data = None

        for attempt in range(5):  # Try 5 times with increasing wait
            self.update_all(0.5)

            # Check if bot1 sees bot0 - check nickname (primary) then account
            # Note: Server sends nickname field, not account field in player props
            for player_id, player_data in bot1.players.items():
                nickname = player_data.get('nickname', '').lower()
                account = player_data.get('account', '').lower()
                bot_name = bot0.name.lower()

                # Primary match is nickname (what server actually sends)
                if nickname == bot_name or account == bot_name:
                    found = True
                    found_player_data = player_data
                    break

            if found:
                break

        if found and found_player_data:
            # Verify position is close
            px = found_player_data.get('x', 0)
            py = found_player_data.get('y', 0)
            result = BugDetector.check_position_sync(
                type('obj', (), {'x': px, 'y': py})(),
                target_x, target_y, tolerance=5.0  # More tolerant for sync delay
            )
            if not result.passed:
                issues.append(Issue(
                    timestamp=time.time(),
                    severity="MEDIUM",
                    category="visibility",
                    description=f"Player position mismatch: {result.message}",
                    context=result.details
                ))

        if not found:
            # Build debug info about what players are visible
            visible_info = []
            for pid, pdata in bot1.players.items():
                visible_info.append({
                    'id': pid,
                    'account': pdata.get('account', ''),
                    'nickname': pdata.get('nickname', '')
                })

            issues.append(Issue(
                timestamp=time.time(),
                severity="HIGH",
                category="visibility",
                description=f"Bot1 cannot see Bot0 in players dict",
                context={
                    "bot0_name": bot0.name,
                    "player_count": len(bot1.players),
                    "visible_players": visible_info
                }
            ))

        duration = time.time() - start
        passed = found and len(issues) == 0

        return MultiTestResult(
            name="visibility",
            passed=passed,
            duration=duration,
            details=f"Bot0 {'visible' if found else 'invisible'} to Bot1 ({len(bot1.players)} players seen)",
            issues=issues
        )

    # ========== PvP Combat Tests ==========

    def run_pvp_test(self, attacker_idx: int = 0, victim_idx: int = 1,
                     expected_damage: float = 0.5) -> MultiTestResult:
        """
        Test PvP combat between two bots.

        Attacker swings sword at victim, verify damage.
        """
        start = time.time()
        issues = []

        if len(self.bots) < 2:
            return MultiTestResult(
                name="pvp_combat",
                passed=False,
                duration=0,
                details="Need at least 2 bots",
                issues=[]
            )

        attacker = self.bots[attacker_idx]
        victim = self.bots[victim_idx]

        # Heal the victim to full first. Hurt damage is persisted server-side in
        # the account, so without this the victim's hearts drain a little every
        # run and eventually hit 0, making the test non-repeatable.
        max_h = victim.client.player.max_hearts or 3.0
        victim.client.send_hearts(max_h)
        for _ in range(5):
            self.update_all(0.1)

        # Record victim's initial hearts
        initial_hearts = victim.hearts
        hurt_time = time.time()

        # Give time for players to sync
        # Use multiple short updates for proper interleaving between bots
        for _ in range(10):
            self.update_all(0.1)

        # Find victim's player ID from attacker's perspective
        # Note: Server sends nickname field, not account field
        victim_id = None
        victim_name = victim.name.lower()
        for pid, pdata in attacker.players.items():
            nickname = pdata.get('nickname', '').lower()
            account = pdata.get('account', '').lower()
            if nickname == victim_name or account == victim_name:
                victim_id = pid
                break

        if victim_id is None:
            # Build debug info
            visible_info = [
                {'id': pid, 'account': pd.get('account', ''), 'nickname': pd.get('nickname', '')}
                for pid, pd in attacker.players.items()
            ]
            issues.append(Issue(
                timestamp=time.time(),
                severity="HIGH",
                category="pvp",
                description="Attacker cannot see victim",
                context={
                    "attacker": attacker.name,
                    "victim": victim.name,
                    "visible_players": visible_info
                }
            ))
            return MultiTestResult(
                name="pvp_combat",
                passed=False,
                duration=time.time() - start,
                details=f"Victim not visible to attacker ({len(attacker.players)} players seen)",
                issues=issues
            )

        # Move bots close together
        target_x, target_y = 32.0, 32.0
        victim.walk_to(target_x, target_y, timeout=3.0)
        attacker.walk_to(target_x - 1, target_y, timeout=3.0)  # Stand to left of victim
        self.update_all(0.5)

        # Attacker swings sword (direction 3 = right, towards victim)
        attacker.sword_attack(direction=3)
        # Use multiple short updates for proper interleaving between bots
        for _ in range(10):
            self.update_all(0.1)

        # Check if victim received hurt callback
        result = BugDetector.check_hurt_callback_fired(victim.hurt_received, hurt_time)
        if not result.passed:
            # Try direct attack packet
            attacker.attack_player(victim_id, expected_damage)
            self.update_all(0.5)
            result = BugDetector.check_hurt_callback_fired(victim.hurt_received, hurt_time)

        if not result.passed:
            issues.append(Issue(
                timestamp=time.time(),
                severity="HIGH",
                category="pvp",
                description="Victim did not receive hurt callback",
                context={"attacker": attacker.name, "victim": victim.name}
            ))

        # Check if damage was applied
        new_hearts = victim.hearts
        damage_result = BugDetector.check_damage_applied(
            initial_hearts, new_hearts, expected_damage, tolerance=0.2
        )

        if not damage_result.passed:
            issues.append(Issue(
                timestamp=time.time(),
                severity="HIGH",
                category="pvp",
                description=damage_result.message,
                context=damage_result.details
            ))

        duration = time.time() - start
        passed = len(issues) == 0

        return MultiTestResult(
            name="pvp_combat",
            passed=passed,
            duration=duration,
            details=f"Hearts: {initial_hearts} -> {new_hearts}",
            issues=issues
        )

    # ========== Chat Tests ==========

    def run_chat_test(self, sender_idx: int = 0, receiver_idx: int = 1) -> MultiTestResult:
        """
        Test chat between two bots.

        Sender says message, receiver should receive it.
        """
        start = time.time()
        issues = []

        if len(self.bots) < 2:
            return MultiTestResult(
                name="chat",
                passed=False,
                duration=0,
                details="Need at least 2 bots",
                issues=[]
            )

        sender = self.bots[sender_idx]
        receiver = self.bots[receiver_idx]

        # Generate unique test message
        import random
        unique_id = random.randint(100000, 999999)
        test_message = f"ChatTest_{unique_id}"
        
        # Clear chat logs completely before test
        sender.chat_received.clear()
        receiver.chat_received.clear()

        # Send message
        sender.client.say(test_message)
        
        # Update to receive message
        for _ in range(20):
            self.update_all(0.1)
        
        # Check if receiver got the message (no timestamp filter - check all messages)
        result = CheckResult(passed=False, message=f"Chat not received: {test_message}")
        for player_id, message, timestamp in receiver.chat_received:
            if test_message in message:
                result = CheckResult(
                    passed=True,
                    message=f"Chat received: {test_message}",
                    details={"message": message}
                )
                break

        if not result.passed:
            # Check if at least some message was received (logs were cleared above).
            new_messages = receiver.chat_received
            if new_messages:
                issues.append(Issue(
                    timestamp=time.time(),
                    severity="LOW",
                    category="chat",
                    description=f"Message received but content didn't match",
                    context={"sent": test_message, "received": [m[1] for m in new_messages]}
                ))
            else:
                issues.append(Issue(
                    timestamp=time.time(),
                    severity="MEDIUM",
                    category="chat",
                    description="No chat message received",
                    context={"sent": test_message}
                ))

        duration = time.time() - start
        passed = result.passed

        return MultiTestResult(
            name="chat",
            passed=passed,
            duration=duration,
            details=result.message,
            issues=issues
        )

    # ========== Composite Tests ==========

    def run_all_multi_tests(self) -> List[MultiTestResult]:
        """Run all multi-bot tests."""
        results = []

        results.append(self.run_visibility_test())
        results.append(self.run_pvp_test())
        results.append(self.run_chat_test())

        return results

    def get_summary(self, results: List[MultiTestResult]) -> Dict[str, Any]:
        """Generate summary from test results."""
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        all_issues = []
        for r in results:
            all_issues.extend(r.issues)

        return {
            "passed": passed,
            "total": total,
            "pass_rate": passed / total if total > 0 else 0,
            "issues": all_issues,
            "results": [
                {"name": r.name, "passed": r.passed, "duration": r.duration}
                for r in results
            ]
        }
