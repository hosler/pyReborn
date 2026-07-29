"""
TestScenarios - Predefined scripted test cases.

Collection of automated test scenarios for various game features.
"""

import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from dataclasses import dataclass

from .game_bot import GameBot, Issue
from .bug_detector import BugDetector
from .reporter import TestResult


# Sibling server checkouts, derived from THIS checkout rather than one
# developer's absolute paths: game_tester/ -> pyReborn/ -> opengraal2/.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ACCOUNTS_DIR = (_CHECKOUT_ROOT / "GServer-v2" / "bin" / "servers" /
                         "default" / "accounts")
# pygserver's JSON account store. Override with PYGSERVER_ACCOUNTS_DIR.
_DEFAULT_PYGSERVER_ACCOUNTS_DIR = _CHECKOUT_ROOT / "pygserver" / "accounts"


def _resolve_accounts_dir(env_var: str, default: Path) -> Optional[str]:
    """Resolve an account-store directory, or None to skip the fixture.

    The helpers below REWRITE persisted account files, so a path that isn't
    an account store must make them no-op rather than guess: returns None when
    the resolved directory doesn't exist. An explicit override that points
    nowhere is a misconfiguration worth saying out loud - it silently produced
    "the fixture didn't take" runs whose failures then looked like renderer or
    protocol regressions (see render_smoke's [ENV WARNING] block).
    """
    override = os.environ.get(env_var)
    if override:
        if not os.path.isdir(override):
            print(f"[QA WARNING] {env_var}={override!r} is not a directory; "
                  f"account fixture skipped", file=sys.stderr)
            return None
        return override
    return str(default) if default.is_dir() else None


def reset_account_chests(account_name: str) -> bool:
    """Strip persisted 'CHEST ...' loot lines from a local account file so a
    chest test can re-open chests. Best-effort: returns False (no-op) when the
    account file can't be found (e.g. testing a remote server). The caller must
    be logged out when this runs, otherwise the server re-saves the looted state.
    """
    accounts_dir = _resolve_accounts_dir("GSERVER_ACCOUNTS_DIR",
                                         _DEFAULT_ACCOUNTS_DIR)
    if accounts_dir is None:
        return False
    path = os.path.join(accounts_dir, f"{account_name}.txt")
    try:
        with open(path) as f:
            lines = f.readlines()
        kept = [l for l in lines if not l.startswith("CHEST ")]
        if len(kept) != len(lines):
            with open(path, "w") as f:
                f.writelines(kept)
        return True
    except OSError:
        return False


def _reset_pygserver_account(account_name: str, level: str,
                             x: float, y: float, mp: "int | None") -> bool:
    import json
    accounts_dir = _resolve_accounts_dir("PYGSERVER_ACCOUNTS_DIR",
                                         _DEFAULT_PYGSERVER_ACCOUNTS_DIR)
    if accounts_dir is None:
        return False
    path = os.path.join(accounts_dir, f"{account_name}.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        # Missing keys fall back to Account dataclass defaults on load.
        data = {"account_name": account_name}
    data.update({"level_name": level, "x": x, "y": y})
    # Restock ammo. The server DEDUCTS on fire and persists the result, so a
    # suite that shoots leaves the account at 0 and the next run's projectile
    # checks fail with no PLO_ARROWADD ever sent -- looking exactly like a
    # renderer regression. Values are the Account dataclass defaults
    # (pygserver/pygserver/account.py:63), i.e. GServer's own starting stock.
    data.setdefault("arrows", 5)
    data.setdefault("bombs", 10)
    data["arrows"] = max(int(data.get("arrows") or 0), 5)
    data["bombs"] = max(int(data.get("bombs") or 0), 10)
    if mp is not None:
        data["mp"] = mp
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


def reset_account_position(account_name: str,
                           level: str = "onlinestartlocal.nw",
                           x: float = 30.0, y: float = 30.0,
                           mp: "int | None" = None) -> bool:
    """Reset a local account's persisted LEVEL/X/Y to a known non-gmap start.

    The server persists the player's last level + position; a gmap test that
    leaves the bot on the .gmap world would otherwise make the next run start
    there and break position-sensitive tests. Best-effort; caller must be
    logged out (else the server re-saves the live position on disconnect).

    `mp` optionally pins the account's PLPROP_MAGICPOINTS (FlatFileAccountLoader
    "MP" key) to a specific non-default value. render_smoke's HUD check uses
    this so a correctly-parsed self.mp can be told apart from the Player
    dataclass's default of 0 - a fresh account with no MP line would parse to
    0 either way, which wouldn't prove the wire delivery actually happened.
    """
    # pygserver keeps accounts as JSON in its own dir; patch (or create — QA
    # wipes that dir, and pygserver loads a pre-existing file on login) the
    # JSON twin so the same fixture pins work against either server.
    _reset_pygserver_account(account_name, level, x, y, mp)

    accounts_dir = _resolve_accounts_dir("GSERVER_ACCOUNTS_DIR",
                                         _DEFAULT_ACCOUNTS_DIR)
    if accounts_dir is None:
        return False
    path = os.path.join(accounts_dir, f"{account_name}.txt")
    # NICK must equal the account name or the multi-bot visibility test can't
    # identify players; the scripted gmap world (setnick/setcharprop NPCs) can
    # mutate it, so restore it here too. Preserve the file's CRLF line ending.
    repl = {"LEVEL": f"LEVEL {level}", "X": f"X {x:g}", "Y": f"Y {y:g}",
            "NICK": f"NICK {account_name}"}
    if mp is not None:
        repl["MP"] = f"MP {mp:g}"
    try:
        with open(path, newline="") as f:
            text = f.read()
        eol = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(eol)
        seen = {k: False for k in repl}
        out = []
        for line in lines:
            key = line.split(" ", 1)[0]
            if key in repl:
                out.append(repl[key])
                seen[key] = True
            else:
                out.append(line)
        # Insert any missing keys after the GRACC001 header (line 0).
        missing = [repl[k] for k, was in seen.items() if not was]
        if missing:
            out[1:1] = missing
        with open(path, "w", newline="") as f:
            f.write(eol.join(out))
        return True
    except OSError:
        return False


#: (order, function) pairs filled in by @single_bot_scenario. THE single
#: source for which scenarios make up the single-bot suite: both
#: run_all_single_bot_tests() below and tests/test_qa_pytest.py read it, where
#: each used to keep its own hand-written copy of the list - a scenario added
#: to one and forgotten in the other silently lost that coverage.
_SINGLE_BOT_REGISTRY: List[Tuple[int, Callable]] = []


def single_bot_scenario(order: int) -> Callable[[Callable], Callable]:
    """Register a scenario in the single-bot suite at position `order`.

    Apply it BELOW @staticmethod so it registers the plain function (that is
    also what `TestScenarios.<name>` hands back, so registry entries and
    attribute access are the same object).

    Position is explicit rather than definition order: the suite deliberately
    interleaves categories (level_data runs 2nd but is defined down in the
    data-integrity section), and the run order is what `python -m game_tester`
    reports. Gaps of 10 leave room to insert.
    """
    def register(fn: Callable) -> Callable:
        clash = next((f for taken, f in _SINGLE_BOT_REGISTRY if taken == order),
                     None)
        if clash is not None:
            raise ValueError(f"single-bot scenario order {order} is already "
                             f"used by {clash.__name__}")
        _SINGLE_BOT_REGISTRY.append((order, fn))
        return fn
    return register


def single_bot_scenarios() -> List[Callable]:
    """The registered single-bot scenarios, in suite order."""
    return [fn for _, fn in sorted(_SINGLE_BOT_REGISTRY, key=lambda e: e[0])]


class TestScenarios:
    """
    Collection of automated test scenarios.

    Each test method takes a GameBot and returns a TestResult.

    Usage:
        bot = GameBot("testbot1", "localhost", 14900)
        bot.connect()
        result = TestScenarios.test_movement_all_directions(bot)
        print(result.passed, result.details)
    """

    # ========== Connection Tests ==========

    @staticmethod
    @single_bot_scenario(10)
    def test_connection(bot: GameBot, duration: float = 5.0) -> TestResult:
        """Test connection stability for duration seconds."""
        start = time.time()
        issues = []

        deadline = time.time() + duration
        disconnect_count = 0

        while time.time() < deadline:
            bot.update(0.1)

            if not bot.connected:
                disconnect_count += 1
                if not bot.connect():
                    issues.extend(bot.issues)
                    break

        passed = disconnect_count == 0 and bot.connected
        return TestResult(
            name="connection_stability",
            passed=passed,
            duration=time.time() - start,
            details=f"Disconnects: {disconnect_count}",
            issues=issues
        )

    # ========== Movement Tests ==========

    @staticmethod
    @single_bot_scenario(30)
    def test_movement_all_directions(bot: GameBot) -> TestResult:
        """Test movement in all 4 directions.

        A previous version of this test never required any move to actually
        succeed - it passed as long as any *blocked* move wasn't an
        out-of-bounds bug, so it passed unconditionally even if move()
        always returned False (0/4 moves). The QA fixture level's spawn
        area (onlinestartlocal.nw around 30,30) is open ground in all 4
        directions, so require most moves to actually change position while
        still tolerating an occasional legitimate wall/edge block.
        """
        start = time.time()
        issues = []
        directions = [(1, 0, "right"), (-1, 0, "left"), (0, 1, "down"), (0, -1, "up")]
        succeeded = 0

        for dx, dy, name in directions:
            old_x, old_y = bot.x, bot.y
            moved = bot.move(dx, dy)

            if moved:
                succeeded += 1
            else:
                # Check if blocked by wall
                result = BugDetector.check_out_of_bounds(bot.client)
                if not result.passed:
                    issues.append(bot.issues[-1] if bot.issues else None)

        issues = [i for i in issues if i]
        passed = succeeded >= 3 and len(issues) == 0
        return TestResult(
            name="movement_all_directions",
            passed=passed,
            duration=time.time() - start,
            details=f"{succeeded}/{len(directions)} directions moved successfully",
            issues=issues
        )

    @staticmethod
    @single_bot_scenario(60)
    def test_walk_to_target(bot: GameBot, target_x: float = 35.0,
                            target_y: float = 35.0) -> TestResult:
        """Test walk_to pathfinding.

        Note: With proper collision detection, the bot may not reach the
        exact target if there are walls in the way. We consider success
        if the bot gets within tolerance OR makes significant progress.
        """
        start = time.time()
        start_x, start_y = bot.x, bot.y

        success = bot.walk_to(target_x, target_y, timeout=10.0)

        # Check if arrived (within tolerance)
        # Use tolerance of 1.5 to account for walls/obstacles
        result = BugDetector.check_position_sync(
            bot.client, target_x, target_y, tolerance=1.5
        )

        # Also consider it a pass if we made significant progress toward target
        # (moved more than 2 tiles closer to target)
        start_dist = abs(start_x - target_x) + abs(start_y - target_y)
        end_dist = abs(bot.x - target_x) + abs(bot.y - target_y)
        made_progress = (start_dist - end_dist) > 2.0

        passed = result.passed or made_progress

        return TestResult(
            name="walk_to_target",
            passed=passed,
            duration=time.time() - start,
            details=f"Target: ({target_x}, {target_y}), Final: ({bot.x:.1f}, {bot.y:.1f}), "
                   f"Dist: {start_dist:.1f} -> {end_dist:.1f}",
            issues=bot.get_issues() if not passed else []
        )

    @staticmethod
    @single_bot_scenario(40)
    def test_collision_detection(bot: GameBot) -> TestResult:
        """Test that collision detection works (parity with pygame client).

        A previous version of this test accepted ANY outcome ("either we hit
        a wall or moved successfully - both are valid") for every sub-check,
        so it passed even with collision detection completely disabled. This
        version pins down two concrete facts about the shared QA fixture
        level (onlinestartlocal.nw, probed live against the running server):
        the default spawn (30, 30) is open ground, and there's a wall
        spanning row 17 a few tiles north of it (tile id 18 at column 30,
        row 17 is TileType-blocking). A real player can walk south from
        spawn but is stopped before crossing north past row 17.
        """
        start = time.time()
        issues = []

        # Known-good starting position so the test is deterministic
        # regardless of what earlier tests left the bot doing.
        bot.warp_to("onlinestartlocal.nw", 30.0, 30.0)

        # 1) A known floor tile must allow movement.
        floor_ok = bot.move(0, 1)  # open field south of spawn
        if not floor_ok:
            issues.append(
                f"Known floor tile blocked movement at ({bot.x:.1f}, {bot.y:.1f})")

        # 2) A known wall (row 17) must actually block movement - walk north
        # into it and confirm the bot stops before tunnelling through.
        # Collision is the classic-engine spec's 2x2-tile box centred on
        # (x+1.5, y+2.5) - box top edge at y+1.5 (the head/sprite above that
        # may still overlap walls) - so walking north the bot may legally
        # stand as high as the box top would land on row 18 (y=16.5); it
        # must be blocked once the box top would land on row 17, i.e. it can
        # never get below y=15.5. (Live-verified: real stop is ~y=17.2, well
        # inside this bound with room for the bot's 0.25-tile step
        # granularity and the one-tile lookahead check.)
        hit_wall = False
        for _ in range(60):
            moved = bot.move(0, -1)
            if not moved:
                hit_wall = True
                break
            if bot.y <= 13.0:
                break  # safety net: feet fully past the known wall row

        if not hit_wall:
            issues.append(
                f"Expected the collision box to be blocked by the wall at "
                f"row 17, but reached ({bot.x:.1f}, {bot.y:.1f}) unobstructed")
        elif bot.y < 15.5:
            issues.append(
                f"Walked through the wall: stopped at y={bot.y:.1f} "
                f"(wall row 17 = box-top-blocked at y>=15.5)")

        passed = floor_ok and hit_wall and bot.y >= 15.5

        return TestResult(
            name="collision_detection",
            passed=passed,
            duration=time.time() - start,
            details=(f"floor_move={floor_ok} hit_wall={hit_wall} "
                     f"final=({bot.x:.1f}, {bot.y:.1f})"),
            issues=issues
        )

    @staticmethod
    @single_bot_scenario(50)
    def test_swimming_detection(bot: GameBot) -> TestResult:
        """Test that swimming/water detection works (parity with pygame client).

        This test verifies that the GameBot can detect water tiles
        the same way the pygame client does.
        """
        start = time.time()

        # Check current swimming state
        bot._update_swimming_state()
        was_swimming = bot.is_swimming

        # Test that swimming state can be checked without error
        try:
            bot._check_water_at_position(bot.x + 1.5, bot.y + 2.5)
            check_works = True
        except Exception as e:
            check_works = False

        # Note: Whether we're actually in water depends on level
        return TestResult(
            name="swimming_detection",
            passed=check_works,
            duration=time.time() - start,
            details=f"Swimming: {bot.is_swimming}, Water check method: {'OK' if check_works else 'FAIL'}",
            issues=[]
        )

    # ========== Combat Tests ==========

    @staticmethod
    @single_bot_scenario(80)
    def test_sword_attack(bot: GameBot) -> TestResult:
        """Test sword attack in all directions."""
        start = time.time()
        success = True

        for direction in [0, 1, 2, 3]:  # up, left, down, right
            if not bot.sword_attack(direction):
                success = False

        return TestResult(
            name="sword_attack",
            passed=success,
            duration=time.time() - start,
            details="Attacked in all 4 directions",
            issues=[]
        )

    @staticmethod
    def test_shoot_arrow(bot: GameBot) -> TestResult:
        """Test arrow shooting."""
        start = time.time()

        # Give bot some arrows (via flag)
        bot.set_flag("arrows", "10")
        bot.update(0.2)

        success = bot.shoot(direction=2)  # Shoot down

        return TestResult(
            name="shoot_arrow",
            passed=success,
            duration=time.time() - start,
            details="Shot arrow down",
            issues=[]
        )

    @staticmethod
    def test_drop_bomb(bot: GameBot) -> TestResult:
        """Test bomb dropping."""
        start = time.time()

        # Give bot some bombs
        bot.set_flag("bombs", "5")
        bot.update(0.2)

        success = bot.drop_bomb(power=1)
        bot.update(1.0)  # Wait for explosion

        return TestResult(
            name="drop_bomb",
            passed=success,
            duration=time.time() - start,
            details="Dropped bomb",
            issues=[]
        )

    # ========== Chat Tests ==========

    @staticmethod
    @single_bot_scenario(70)
    def test_chat_roundtrip(bot: GameBot) -> TestResult:
        """Test that a chat message actually reaches the server and gets relayed.

        A previous version of this test only asserted on
        client.player.chat, which client.say() sets *optimistically* before
        the packet is even written to the socket (the server never echoes
        your own message back to you - toall skips the sender - so that
        local field proves nothing about the network round trip and the
        test passed even with a completely broken connection). Verify the
        real server-relay path with a second, disposable connection that
        should see the message via PLO_TOALL/on_chat.
        """
        start = time.time()
        issues = []
        success = False
        test_msg = f"Test_{int(time.time())}"

        listener = GameBot(f"{bot.name}_chatlistener", bot.host, bot.port, bot.password)
        try:
            if not listener.connect(timeout=8.0):
                issues.extend(listener.get_issues())
            else:
                listener.chat_received.clear()
                sent = bot.say(test_msg)

                deadline = time.time() + 5.0
                while time.time() < deadline and not success:
                    listener.update(0.1)
                    bot.update(0.1)
                    success = bool(sent) and any(
                        test_msg in msg for _, msg, _ in listener.chat_received)

                if not success:
                    issues.append(
                        f"Chat message not relayed to a second connection: "
                        f"sent={sent} msg={test_msg!r} received={listener.chat_received!r}")
        finally:
            listener.disconnect()

        return TestResult(
            name="chat_roundtrip",
            passed=success,
            duration=time.time() - start,
            details=f"Message: {test_msg}; relayed={success}",
            issues=issues
        )

    # ========== Item Tests ==========

    @staticmethod
    @single_bot_scenario(90)
    def test_item_detection(bot: GameBot) -> TestResult:
        """Test that items on ground are detected."""
        start = time.time()

        result = BugDetector.check_items_on_ground(bot.client)
        return TestResult(
            name="item_detection",
            passed=True,  # Just informational
            duration=time.time() - start,
            details=f"{len(bot.items)} items on ground",
            issues=[]
        )

    @staticmethod
    def test_item_pickup(bot: GameBot) -> TestResult:
        """Test picking up an item if any are present."""
        start = time.time()

        if not bot.items:
            return TestResult(
                name="item_pickup",
                passed=True,
                duration=time.time() - start,
                details="No items to pickup (skipped)",
                issues=[]
            )

        # Get first item position
        pos = list(bot.items.keys())[0]
        x, y = pos

        # Walk to item
        bot.walk_to(x, y, timeout=5.0)

        # Try to pickup
        success = bot.pickup_item(x, y)

        return TestResult(
            name="item_pickup",
            passed=success,
            duration=time.time() - start,
            details=f"Picked up item at ({x:.1f}, {y:.1f})",
            issues=[]
        )

    # ========== Warp Tests ==========

    @staticmethod
    def test_door_warp(bot: GameBot) -> TestResult:
        """Test using a door if one exists."""
        start = time.time()

        # Check for door at current position
        link = bot.client.check_link_collision()

        if not link:
            return TestResult(
                name="door_warp",
                passed=True,
                duration=time.time() - start,
                details="No door at current position (skipped)",
                issues=[]
            )

        old_level = bot.level
        success = bot.use_nearest_door()

        return TestResult(
            name="door_warp",
            passed=success,
            duration=time.time() - start,
            details=f"Warped from {old_level} to {bot.level}",
            issues=[]
        )

    # ========== NPC Tests ==========

    @staticmethod
    @single_bot_scenario(100)
    def test_npc_visibility(bot: GameBot) -> TestResult:
        """Check if NPCs are visible in level (informational - 0 NPCs is valid)."""
        start = time.time()

        result = BugDetector.check_npcs_received(bot.client)
        npc_count = len(bot.npcs)

        # This is informational - 0 NPCs is valid for many levels
        return TestResult(
            name="npc_visibility",
            passed=True,  # Always pass - just informational
            duration=time.time() - start,
            details=f"{npc_count} NPCs visible" if npc_count > 0 else "No NPCs in level (normal)",
            issues=[]
        )

    # ========== Data Integrity Tests ==========

    @staticmethod
    @single_bot_scenario(20)
    def test_level_data(bot: GameBot) -> TestResult:
        """Test that level data is properly loaded."""
        start = time.time()

        results = [
            BugDetector.check_level_loaded(bot.client),
            BugDetector.check_tiles_valid(bot.client),
        ]

        passed = all(r.passed for r in results)
        details = "; ".join(r.message for r in results)

        return TestResult(
            name="level_data",
            passed=passed,
            duration=time.time() - start,
            details=details,
            issues=[]
        )

    # ========== File / Chest / Level Parsing Tests ==========

    @staticmethod
    @single_bot_scenario(110)
    def test_file_download(bot: GameBot) -> TestResult:
        """Request a known file from the server and verify it downloads intact.

        Exercises PLI_WANTFILE -> PLO_RAWDATA -> PLO_FILE assembly. The level
        file is served by the default world (onlinestartlocal.nw) and must come
        back byte-for-byte (a double trailing-newline strip used to drop a byte).
        """
        start = time.time()
        issues = []

        filename = "onlinestartlocal.nw"
        bot.client.request_file(filename)
        deadline = time.time() + 8.0
        while time.time() < deadline and not bot.client.has_file(filename):
            bot.update(0.1)

        data = bot.client.get_file(filename)
        if not data:
            issues.append(Issue(timestamp=time.time(), severity="HIGH", category="file",
                                description=f"File {filename} did not download",
                                context={"failed": bot.client.did_file_fail(filename)}))
            passed = False
            details = f"{filename}: no data"
        else:
            # A .nw level must start with the GLEVNW01 magic and be non-trivial.
            valid_header = data[:8] == b"GLEVNW01"
            passed = valid_header and len(data) > 1000
            if not valid_header:
                issues.append(Issue(timestamp=time.time(), severity="HIGH", category="file",
                                    description="Downloaded file has wrong header",
                                    context={"head": data[:16].hex()}))
            details = f"{filename}: {len(data)} bytes, header={'ok' if valid_header else 'BAD'}"

        return TestResult(name="file_download", passed=passed,
                          duration=time.time() - start, details=details, issues=issues)

    @staticmethod
    @single_bot_scenario(120)
    def test_chest_interaction(bot: GameBot) -> TestResult:
        """Open a chest and verify the item is delivered.

        Exercises PLI_OPENCHEST -> PLO_LEVELCHEST and the item grant. Chest loot
        is persisted per-account, so for repeatability we reset the account's
        saved chests first (best-effort; only possible against a local server).
        """
        start = time.time()
        issues = []

        # Use a dedicated account (testbot2) on its own connection so we can wipe
        # its persisted chest loot without disturbing the main suite bot. Loot is
        # only resettable while that account is logged out, which it is here
        # (testbot2 is otherwise used only by the later multi-bot tests).
        chest_account = "testbot2"
        reset_account_chests(chest_account)

        cb = GameBot(chest_account, bot.host, bot.port)
        if not cb.connect():
            return TestResult(name="chest_interaction", passed=False,
                              duration=time.time() - start,
                              details=f"Could not connect {chest_account}",
                              issues=[Issue(timestamp=time.time(), severity="HIGH",
                                            category="chest",
                                            description="Chest-test bot failed to connect",
                                            context={})])
        try:
            if cb.client._current_level_name != "onlinestartlocal.nw":
                cb.client.warp_to_level("onlinestartlocal.nw", 30, 30)
                cb.update(1.0)
            cb.update(0.5)

            level_name = cb.client.get_current_level_from_position()
            chests = dict(cb.client.chests_in_level(level_name))
            items = dict(cb.client.chest_items.get(level_name, {}))
            if not chests:
                return TestResult(name="chest_interaction", passed=False,
                                  duration=time.time() - start,
                                  details="No chests announced in level",
                                  issues=[Issue(timestamp=time.time(), severity="HIGH",
                                                category="chest",
                                                description="No chests in level", context={})])

            # A rupee chest lets us verify item delivery via the rupee counter.
            rupee_pos = next((pos for pos, it in items.items() if "rupee" in it), None)
            target = rupee_pos or next((p for p, o in chests.items() if not o), None)

            details = f"{len(chests)} chests, items={list(items.values())}"
            passed = True

            if target is None:
                issues.append(Issue(timestamp=time.time(), severity="LOW", category="chest",
                                    description="All chests already opened (no reset)", context={}))
            else:
                rupees_before = cb.client.player.rupees
                # Walk up to the chest before opening it — the server only
                # grants loot to a player standing next to the chest (a chest
                # is opened in melee range, not from across the level).
                cb.walk_to(target[0], target[1], timeout=8.0)
                cb.update(0.5)
                cb.client.open_chest(target[0], target[1])
                cb.update(1.0)
                if not cb.client.get_chest_opened(level_name, *target):
                    passed = False
                    issues.append(Issue(timestamp=time.time(), severity="HIGH", category="chest",
                                        description=f"Chest {target} did not open", context={}))
                if rupee_pos is not None:
                    gained = cb.client.player.rupees - rupees_before
                    if gained <= 0:
                        passed = False
                        issues.append(Issue(timestamp=time.time(), severity="HIGH", category="chest",
                                            description="Rupee chest gave no rupees",
                                            context={"before": rupees_before,
                                                     "after": cb.client.player.rupees}))
                    details += f"; opened {items.get(target, '?')} (+{gained} rupees)"
        finally:
            cb.disconnect()

        return TestResult(name="chest_interaction", passed=passed,
                          duration=time.time() - start, details=details, issues=issues)

    @staticmethod
    @single_bot_scenario(130)
    def test_level_parsing(bot: GameBot) -> TestResult:
        """Warp to the QA fixture level and verify sign/link/baddy/chest parsing.

        Requires the server-side fixture level 'qa_testlevel.nw' (a sign, a link,
        a graysoldier baddy and a bluerupee chest). Validates the decoders for
        each feature, then warps back to the start level.
        """
        start = time.time()
        issues = []

        bot.client.warp_to_level("qa_testlevel.nw", 30, 30)
        deadline = time.time() + 5.0
        while time.time() < deadline and bot.client._current_level_name != "qa_testlevel.nw":
            bot.update(0.1)
        bot.update(0.8)

        checks = {}

        # Sign: text must decode to readable characters (not raw cipher bytes).
        # signs is keyed per-level: {level: {(x,y): text}}.
        sign_texts = [t for lvl in bot.client.signs.values() for t in lvl.values()]
        checks["sign"] = any("QA test sign" in t for t in sign_texts)

        # Link: a warp link back to the start level.
        links = bot.client.links.get("qa_testlevel.nw", [])
        checks["link"] = any(l.get("dest_level") == "onlinestartlocal.nw" for l in links)

        # Baddy: a graysoldier (type 0) should be present.
        checks["baddy"] = any(b.get("type") == 0 for b in bot.client.baddies.values())

        # Chest: a bluerupee chest announced with its item name.
        chest_item_levels = bot.client.chest_items.values()
        checks["chest"] = any(
            it == "bluerupee" for items in chest_item_levels for it in items.values())

        for name, ok in checks.items():
            if not ok:
                issues.append(Issue(timestamp=time.time(), severity="MEDIUM", category="level",
                                    description=f"Level feature not parsed: {name}",
                                    context={"signs": sign_texts, "links": links,
                                             "baddies": list(bot.client.baddies.values()),
                                             "chest_items": [it for items in
                                                             bot.client.chest_items.values()
                                                             for it in items.values()]}))

        # Return to the start level so account state stays consistent.
        bot.client.warp_to_level("onlinestartlocal.nw", 30, 30)
        bot.update(0.8)

        passed = all(checks.values())
        details = "parsed " + ", ".join(k for k, v in checks.items() if v) + \
                  ("" if passed else "; MISSING " + ", ".join(k for k, v in checks.items() if not v))
        return TestResult(name="level_parsing", passed=passed,
                          duration=time.time() - start, details=details, issues=issues)

    # ========== Run All ==========

    @staticmethod
    def run_all_single_bot_tests(bot: GameBot) -> list:
        """Run all single-bot tests, in registry order."""
        results = []
        for test in single_bot_scenarios():
            try:
                result = test(bot)
                results.append(result)
            except Exception as e:
                results.append(TestResult(
                    name=test.__name__,
                    passed=False,
                    duration=0,
                    details=f"Exception: {e}",
                    issues=[]
                ))

        return results
