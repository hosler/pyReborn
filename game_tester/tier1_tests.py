"""
tier1_tests - Board modify / large file protocol-parity test scenarios.

Exercises the pyReborn Tier 1 additions (see the openreborn2 protocol-parity
audit):
  - PLI_BOARDMODIFY / PLO_BOARDMODIFY round-trip between two bots
  - a >32000 byte file download via PLO_LARGEFILESTART/SIZE/...FILE.../END,
    verified byte-exact against the fixture on disk

Needs the server-side fixture `world/qa_bigfile.txt` (45000 pseudo-random
bytes) - see GServer-v2/bin/servers/default/world/qa_bigfile.txt.

Run: python -m game_tester --tier1
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import List, Tuple

from .game_bot import GameBot, Issue
from .reporter import TestResult

BIGFILE_NAME = "qa_bigfile.txt"
BIGFILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "GServer-v2", "bin", "servers",
    "default", "world", BIGFILE_NAME)


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def test_large_file_transfer(bot: GameBot) -> TestResult:
    """Download qa_bigfile.txt (45000 bytes, >32000 large-file threshold) and
    verify it arrives byte-exact, proving LARGEFILESTART/SIZE + chunked
    PLO_FILE appends + LARGEFILEEND are wired correctly (no truncation, no
    chunk overwriting a prior chunk)."""
    start = time.time()
    issues: List[Issue] = []

    expected = None
    try:
        with open(BIGFILE_PATH, "rb") as f:
            expected = f.read()
    except OSError as e:
        issues.append(_issue("HIGH", "file", f"fixture missing: {e}"))
        return TestResult("large_file_transfer", False, time.time() - start,
                          f"fixture {BIGFILE_PATH} not found", issues)

    bot.client.request_file(BIGFILE_NAME)
    deadline = time.time() + 15.0
    while time.time() < deadline and not bot.client.has_file(BIGFILE_NAME):
        bot.update(0.1)

    data = bot.client.get_file(BIGFILE_NAME)
    if not data:
        # Distinguish the two ways this fails, because they need opposite
        # fixes: an explicit PLO_FILESENDFAILED means the server does not have
        # the fixture (put a copy in the server's own world/ - GServer-v2 ships
        # one, pygserver does not), whereas silence means the transfer itself
        # is broken. Reporting only did_file_fail() conflated them, and that
        # sent one debugging session after the framing code when the file was
        # simply absent.
        refused = bot.client.server_refused(BIGFILE_NAME)
        why = ("server refused it (PLO_FILESENDFAILED) - is the fixture in the "
               "server's world/ directory?" if refused
               else "no answer from the server - transfer path is broken")
        issues.append(_issue("HIGH", "file", f"large file never arrived: {why}"))
        return TestResult("large_file_transfer", False, time.time() - start,
                          f"{BIGFILE_NAME}: no data ({why})", issues)

    exact = data == expected
    if not exact:
        issues.append(_issue("HIGH", "file",
            f"byte mismatch: got {len(data)}B md5={hashlib.md5(data).hexdigest()}, "
            f"expected {len(expected)}B md5={hashlib.md5(expected).hexdigest()}"))

    details = f"{BIGFILE_NAME}: {len(data)}/{len(expected)} bytes, exact={exact}"
    return TestResult("large_file_transfer", exact, time.time() - start, details, issues)


def test_board_modify(bot0: GameBot, bot1: GameBot) -> TestResult:
    """bot0 edits a tile via PLI_BOARDMODIFY; bot1 (on the same level) must
    receive PLO_BOARDMODIFY and update its cached board. Reverts the tile
    afterward so the shared onlinestartlocal.nw fixture isn't left dirty."""
    start = time.time()
    issues: List[Issue] = []

    tx, ty = 5, 5
    received = {}
    bot1.client.on_board_modify = lambda info: received.setdefault("info", info)

    original = bot0.client.get_tile(tx, ty)
    new_tile = 0x0002 if original != 0x0002 else 0x0003

    sent = bot0.client.modify_board(tx, ty, 1, 1, [new_tile])
    if not sent:
        issues.append(_issue("HIGH", "board", "modify_board() send failed"))

    deadline = time.time() + 5.0
    while time.time() < deadline and "info" not in received:
        bot0.update(0.1)
        bot1.update(0.1)

    bot0_tile = bot0.client.get_tile(tx, ty)
    bot1_tile = bot1.client.get_tile(tx, ty)
    delta_seen = "info" in received

    passed = sent and delta_seen and bot0_tile == new_tile and bot1_tile == new_tile
    if not delta_seen:
        issues.append(_issue("HIGH", "board", "bot1 never received on_board_modify"))
    if bot0_tile != new_tile:
        issues.append(_issue("MEDIUM", "board", "sender's own board not updated optimistically"))
    if bot1_tile != new_tile:
        issues.append(_issue("HIGH", "board", "receiver's cached board not patched"))

    # Revert so the shared level isn't left dirty for other tests/sessions.
    bot0.client.modify_board(tx, ty, 1, 1, [original])
    deadline = time.time() + 3.0
    while time.time() < deadline and bot1.client.get_tile(tx, ty) != original:
        bot0.update(0.1)
        bot1.update(0.1)
    bot1.client.on_board_modify = None

    details = (f"tile({tx},{ty}) {original}->{new_tile}: "
              f"bot0={bot0_tile} bot1={bot1_tile} delta_seen={delta_seen}")
    return TestResult("board_modify", passed, time.time() - start, details, issues)


def run_tier1_tests(host: str = "localhost", port: int = 14900,
                    accounts: Tuple[str, str] = ("testbot1", "testbot2")
                    ) -> List[TestResult]:
    """Connect bots and run the tier 1 (board modify / large file) suite."""
    results: List[TestResult] = []
    a, b = accounts

    bot0 = GameBot(a, host, port)
    bot1 = GameBot(b, host, port)
    try:
        if not bot0.connect():
            return [TestResult("tier1_connect", False, 0.0,
                               f"{a} failed to connect", [])]
        try:
            results.append(test_large_file_transfer(bot0))
        except Exception as e:  # noqa: BLE001
            results.append(TestResult("large_file_transfer", False, 0.0, f"Exception: {e}", []))

        if not bot1.connect():
            results.append(TestResult("tier1_multi_connect", False, 0.0,
                                      f"{b} failed to connect", []))
        else:
            try:
                results.append(test_board_modify(bot0, bot1))
            except Exception as e:  # noqa: BLE001
                results.append(TestResult("board_modify", False, 0.0, f"Exception: {e}", []))
    finally:
        bot0.disconnect()
        bot1.disconnect()

    return results
