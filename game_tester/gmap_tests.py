"""
gmap_tests - GMAP (multi-level world) test scenarios.

Exercises pyReborn against a gmap-enabled server (the imported chicken.gmap:
a 3x3 overworld of chicken1-9.nw with interior levels). Validates:

  - entering a gmap (grid download/parse, world coords, bigmap config)
  - adjacent-segment streaming
  - walking across a segment boundary (segment tracking)
  - warping from the gmap into a standalone interior and back
  - cross-segment player visibility and chat relay

These need the chicken gmap world loaded (gmaps = chicken.gmap) and the bots
warped around the scripted world, which persists their LEVEL/X/Y and can mutate
NICK; the runner resets both accounts on teardown via reset_account_position.

Run: python -m game_tester --gmap
"""

from __future__ import annotations

import time
from typing import List, Tuple

from .game_bot import GameBot, Issue
from .reporter import TestResult
from .test_scenarios import reset_account_position

# chicken.gmap layout (col,row) -> level. Center segment is (1,1)=chicken1.nw;
# its east neighbour is (2,1)=chicken7.nw.
GMAP_NAME = "chicken.gmap"
CENTER_SEG = "chicken1.nw"
EAST_SEG = "chicken7.nw"
INTERIOR = "chicken_cave_1.nw"
GMAP_W, GMAP_H = 3, 3


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def _pump(bot: GameBot, seconds: float):
    deadline = time.time() + seconds
    while time.time() < deadline:
        bot.update(0.1)


NON_GMAP = "onlinestartlocal.nw"


def _enter_gmap(bot: GameBot, segment: str = CENTER_SEG,
                x: float = 32.0, y: float = 32.0, settle: float = 2.0):
    """Warp onto a gmap segment fresh and wait for the grid to download/parse.

    Always enters from a non-gmap level first: the server only supplies correct
    world coordinates on a fresh gmap entry, not on a re-warp between already-
    loaded segments, so this guarantees consistent world-coord placement.
    """
    if bot.client.is_gmap:
        bot.client.warp_to_level(NON_GMAP, 30, 30)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            bot.update(0.1)
            if not bot.client.is_gmap:
                break
    bot.client.warp_to_level(segment, x, y)
    deadline = time.time() + settle
    while time.time() < deadline:
        bot.update(0.1)
        if bot.client.is_gmap and bot.client.gmap_width > 0:
            break


# =============================================================================
# Single-bot tests
# =============================================================================

def test_gmap_entry(bot: GameBot) -> TestResult:
    """Enter the gmap and validate grid download, dimensions and bigmap config."""
    start = time.time()
    issues: List[Issue] = []
    _enter_gmap(bot)
    c = bot.client

    if not c.is_gmap:
        issues.append(_issue("HIGH", "gmap", "is_gmap False after warping onto gmap"))
    if c.gmap_name != GMAP_NAME:
        issues.append(_issue("HIGH", "gmap",
                             f"gmap_name={c.gmap_name!r}, expected {GMAP_NAME!r}"))
    if (c.gmap_width, c.gmap_height) != (GMAP_W, GMAP_H):
        issues.append(_issue("HIGH", "gmap",
                             f"grid {c.gmap_width}x{c.gmap_height}, expected 3x3"))
    if len(c.gmap_grid) != GMAP_W * GMAP_H:
        issues.append(_issue("HIGH", "gmap",
                             f"grid has {len(c.gmap_grid)} cells, expected 9"))
    if c.gmap_grid.get((1, 1)) != CENTER_SEG:
        issues.append(_issue("MEDIUM", "gmap",
                             f"center cell (1,1)={c.gmap_grid.get((1,1))!r}, "
                             f"expected {CENTER_SEG!r}"))
    if not c.bigmap_info:
        issues.append(_issue("LOW", "gmap", "no PLO_BIGMAP config received"))

    passed = not any(i.severity in ("HIGH", "MEDIUM") for i in issues)
    details = (f"is_gmap={c.is_gmap} grid={c.gmap_width}x{c.gmap_height} "
               f"cells={len(c.gmap_grid)} bigmap={bool(c.bigmap_info)}")
    return TestResult("gmap_entry", passed, time.time() - start, details, issues)


def test_gmap_adjacent_streaming(bot: GameBot) -> TestResult:
    """Request the 8 surrounding segments and confirm their boards stream in."""
    start = time.time()
    issues: List[Issue] = []
    _enter_gmap(bot)
    bot.client.request_adjacent_levels()
    _pump(bot, 2.5)

    segments = set(bot.client.gmap_grid.values())
    held = segments & set(bot.client.levels.keys())
    missing = segments - held
    if missing:
        issues.append(_issue("MEDIUM", "gmap",
                             f"adjacent boards missing: {sorted(missing)}"))

    passed = not missing
    details = f"{len(held)}/{len(segments)} segment boards held"
    return TestResult("gmap_adjacent_streaming", passed, time.time() - start,
                      details, issues)


def test_gmap_segment_crossing(bot: GameBot) -> TestResult:
    """Walk east out of the center segment and confirm we cross into the east one."""
    start = time.time()
    issues: List[Issue] = []
    # Start near the east edge of the center segment.
    _enter_gmap(bot, CENTER_SEG, x=60.0, y=32.0)
    if not bot.client.is_gmap:
        issues.append(_issue("HIGH", "gmap", "not on gmap before crossing"))

    crossed = False
    for _ in range(20):
        bot.client.move(1, 0, step=0.5)
        _pump(bot, 0.2)
        if bot.client._current_level_name == EAST_SEG:
            crossed = True
            break

    if not crossed:
        issues.append(_issue("HIGH", "gmap",
                             f"did not cross into {EAST_SEG}; still on "
                             f"{bot.client._current_level_name!r}"))

    passed = crossed
    details = (f"crossed {CENTER_SEG} -> {bot.client._current_level_name} "
               f"(expected {EAST_SEG})")
    return TestResult("gmap_segment_crossing", passed, time.time() - start,
                      details, issues)


def test_gmap_interior_warp(bot: GameBot) -> TestResult:
    """Warp gmap -> interior (exits gmap mode) and back (re-enters)."""
    start = time.time()
    issues: List[Issue] = []
    _enter_gmap(bot)

    # Into the interior - should drop out of gmap mode.
    bot.client.warp_to_level(INTERIOR, 30, 30)
    _pump(bot, 2.0)
    if bot.client.is_gmap:
        issues.append(_issue("HIGH", "gmap",
                             f"still is_gmap on interior {INTERIOR}"))
    if bot.client._current_level_name != INTERIOR:
        issues.append(_issue("MEDIUM", "gmap",
                             f"interior level={bot.client._current_level_name!r}, "
                             f"expected {INTERIOR!r}"))
    if len(bot.client.tiles) != 4096:
        issues.append(_issue("MEDIUM", "data",
                             f"interior tiles={len(bot.client.tiles)}, expected 4096"))

    # Back onto the gmap - should re-enter gmap mode and reload the grid.
    _enter_gmap(bot)
    if not bot.client.is_gmap:
        issues.append(_issue("HIGH", "gmap", "did not re-enter gmap after interior"))
    if len(bot.client.gmap_grid) != GMAP_W * GMAP_H:
        issues.append(_issue("MEDIUM", "gmap",
                             "grid not reloaded on gmap re-entry"))

    passed = not any(i.severity in ("HIGH", "MEDIUM") for i in issues)
    details = f"interior is_gmap dropped, re-entry grid={len(bot.client.gmap_grid)}"
    return TestResult("gmap_interior_warp", passed, time.time() - start,
                      details, issues)


# =============================================================================
# Multi-bot tests (two bots on adjacent segments)
# =============================================================================

def _place_adjacent(bot0: GameBot, bot1: GameBot):
    """Put bot0 on the center segment and bot1 on the east neighbour."""
    bot0.client.warp_to_level(CENTER_SEG, 60, 32)
    bot1.client.warp_to_level(EAST_SEG, 4, 32)
    for _ in range(20):
        bot0.update(0.05); bot1.update(0.05)
    bot0.client.request_adjacent_levels()
    bot1.client.request_adjacent_levels()
    for _ in range(20):
        bot0.update(0.05); bot1.update(0.05)
    bot0.client.send_position(); bot1.client.send_position()
    for _ in range(30):
        bot0.update(0.05); bot1.update(0.05)


def _sees(viewer: GameBot, target_name: str) -> bool:
    for _pid, pdata in viewer.client.players.items():
        if pdata.get('nickname', '').lower() == target_name.lower():
            return True
    return False


def test_gmap_cross_segment_visibility(bot0: GameBot, bot1: GameBot) -> TestResult:
    """Two bots on adjacent gmap segments should see each other."""
    start = time.time()
    issues: List[Issue] = []
    _place_adjacent(bot0, bot1)

    b0_sees_b1 = _sees(bot0, bot1.name)
    b1_sees_b0 = _sees(bot1, bot0.name)
    if not b0_sees_b1:
        issues.append(_issue("HIGH", "gmap",
                             f"{bot0.name} cannot see {bot1.name} across segments"))
    if not b1_sees_b0:
        issues.append(_issue("HIGH", "gmap",
                             f"{bot1.name} cannot see {bot0.name} across segments"))

    passed = b0_sees_b1 and b1_sees_b0
    details = f"{bot0.name}<->{bot1.name} cross-segment visible: {passed}"
    return TestResult("gmap_cross_segment_visibility", passed, time.time() - start,
                      details, issues)


def test_gmap_cross_segment_chat(bot0: GameBot, bot1: GameBot) -> TestResult:
    """Chat from a bot on one segment should reach a bot on the adjacent one."""
    start = time.time()
    issues: List[Issue] = []
    _place_adjacent(bot0, bot1)

    msg = f"gmapchat_{int((time.time() % 100000))}"
    before = len(bot1.chat_received)
    bot0.say(msg)
    deadline = time.time() + 2.5
    received = False
    while time.time() < deadline:
        bot0.update(0.05); bot1.update(0.05)
        if any(m == msg for _pid, m, _ts in bot1.chat_received[before:]):
            received = True
            break

    if not received:
        issues.append(_issue("HIGH", "gmap",
                             f"{bot1.name} did not receive cross-segment chat"))

    passed = received
    details = f"cross-segment chat {bot0.name}->{bot1.name}: {received}"
    return TestResult("gmap_cross_segment_chat", passed, time.time() - start,
                      details, issues)


# =============================================================================
# Runner
# =============================================================================

def run_gmap_tests(host: str = "localhost", port: int = 14900,
                   accounts: Tuple[str, str] = ("testbot1", "testbot2")
                   ) -> List[TestResult]:
    """Connect bots, run the gmap suite, and reset account positions on teardown.

    Resetting is essential: the scripted chicken world persists each bot's
    LEVEL/X/Y on the gmap and can mutate NICK, which would break the base QA
    suite on the next run.
    """
    results: List[TestResult] = []
    a, b = accounts

    bot0 = GameBot(a, host, port)
    bot1 = GameBot(b, host, port)
    try:
        if not bot0.connect():
            return [TestResult("gmap_connect", False, 0.0,
                               f"{a} failed to connect", [])]
        for test in (test_gmap_entry, test_gmap_adjacent_streaming,
                     test_gmap_segment_crossing, test_gmap_interior_warp):
            try:
                results.append(test(bot0))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult(test.__name__, False, 0.0,
                                          f"Exception: {e}", []))

        if not bot1.connect():
            results.append(TestResult("gmap_multi_connect", False, 0.0,
                                      f"{b} failed to connect", []))
        else:
            for test in (test_gmap_cross_segment_visibility,
                         test_gmap_cross_segment_chat):
                try:
                    results.append(test(bot0, bot1))
                except Exception as e:  # noqa: BLE001
                    results.append(TestResult(test.__name__, False, 0.0,
                                              f"Exception: {e}", []))
    finally:
        bot0.disconnect()
        bot1.disconnect()
        # Teardown: clear gmap state persisted to the accounts.
        time.sleep(0.5)
        for acct in accounts:
            reset_account_position(acct)

    return results
