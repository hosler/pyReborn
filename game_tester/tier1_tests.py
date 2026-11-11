"""
tier1_tests - Board modify / large file protocol-parity test scenarios.

Exercises the pyReborn Tier 1 additions (see the openreborn2 protocol-parity
audit):
  - PLI_BOARDMODIFY / PLO_BOARDMODIFY round-trip between two bots
  - a >32000 byte file download via PLO_LARGEFILESTART/SIZE/...FILE.../END,
    verified byte-exact against the fixture on disk

The large-file fixture is GENERATED, not stored. It used to be an untracked
45000-byte blob that had to exist in two places at once - the server's world
directory to be served, and GServer-v2's tree to be compared against - and was
committed to neither, so on any checkout but the one it was created on the test
failed with "fixture missing" or, worse, "large file never arrived", which reads
as a broken transfer rather than absent test data.

Run: python -m game_tester --tier1
"""

from __future__ import annotations

import atexit
import hashlib
import os
import random
import time
from typing import List, Optional, Tuple

from .fixtures import FixtureFile
from .game_bot import GameBot, Issue
from .reporter import TestResult

BIGFILE_NAME = "qa_bigfile.txt"
# 45000 bytes: over GServer-v2's 32000 large-file threshold (and pygserver's,
# now aligned to it), so this lands on the chunked path rather than a single
# ordinary PLO_FILE. Seeded, so every checkout produces identical bytes.
BIGFILE_SIZE = 45000
_BIGFILE_SEED = 0x9E3779B9

# Where a locally-run server keeps the files it serves. Only used when the
# target is loopback - a remote server's disk is none of our business.
# pygserver serves `levels/` (and `world/` when a checkout has one); the
# reference server serves `world/`. Directories that do not exist are skipped,
# never created: a missing directory means that server is not set up here.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SERVER_WORLD_DIRS = (
    os.path.join(_REPO, "pygserver", "levels"),
    os.path.join(_REPO, "pygserver", "world"),
    os.path.join(_REPO, "GServer-v2", "bin", "servers", "default", "world"),
)
_LOOPBACK = ("localhost", "127.0.0.1", "::1")

# Fixtures this process provisioned and still owes the filesystem a removal for.
_PROVISIONED: List[FixtureFile] = []


def bigfile_bytes() -> bytes:
    """The fixture's content. Deterministic across machines and runs."""
    return random.Random(_BIGFILE_SEED).randbytes(BIGFILE_SIZE)


def _candidate_world_dirs() -> Tuple[str, ...]:
    # `qa_server run` exports the private/served levels directory of the server
    # it started; that is the one a --port run must target.
    override = os.environ.get("PYGSERVER_LEVELS_DIR")
    if override:
        return (override,)
    return _SERVER_WORLD_DIRS


def cleanup_bigfile() -> int:
    """Remove the fixture from every directory this process put it in.

    A copy that already existed with the right bytes was never recorded, so it
    stays. Runs at the end of run_tier1_tests and again at interpreter exit.
    """
    removed = 0
    while _PROVISIONED:
        removed += _PROVISIONED.pop().release()
    return removed


def ensure_bigfile_served(host: str) -> Optional[str]:
    """Put the fixture where a locally-run server will serve it.

    Returns a reason string if it could not be provisioned, else None. Writing
    is skipped entirely for a non-loopback host: we cannot reach that server's
    disk, and the test reports the resulting refusal rather than pretending.
    Whatever this writes is removed by cleanup_bigfile(); an identical copy
    that was already there is left untouched.
    """
    if host not in _LOOPBACK:
        return f"target {host} is not local, cannot place the fixture"
    payload = bigfile_bytes()
    candidates = _candidate_world_dirs()
    served = []
    for world_dir in candidates:
        if not os.path.isdir(world_dir):
            continue
        fixture = FixtureFile(world_dir, BIGFILE_NAME, payload)
        try:
            fixture.install()
        except OSError as e:
            fixture.release()
            return f"could not write {fixture.path}: {e}"
        if fixture.refused:
            return f"{fixture.path} is a symlink; refusing to write through it"
        if fixture.installed:
            if not _PROVISIONED:
                atexit.register(cleanup_bigfile)
            _PROVISIONED.append(fixture)
        served.append(world_dir)
    if not served:
        return ("no server world directory found (looked in "
                + ", ".join(candidates) + ")")
    return None


def _issue(sev: str, cat: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category=cat, description=desc)


def test_large_file_transfer(bot: GameBot) -> TestResult:
    """Download qa_bigfile.txt (45000 bytes, >32000 large-file threshold) and
    verify it arrives byte-exact, proving LARGEFILESTART/SIZE + chunked
    PLO_FILE appends + LARGEFILEEND are wired correctly (no truncation, no
    chunk overwriting a prior chunk)."""
    start = time.time()
    issues: List[Issue] = []

    expected = bigfile_bytes()
    unprovisioned = ensure_bigfile_served(bot.host)
    if unprovisioned:
        issues.append(_issue("HIGH", "file", f"fixture not served: {unprovisioned}"))
        return TestResult("large_file_transfer", False, time.time() - start,
                          f"fixture not served: {unprovisioned}", issues)

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
    """bot0 edits a tile via PLI_BOARDMODIFY. Bot1 (on the same level) must
    receive PLO_BOARDMODIFY and update its cached board. Reverts the tile
    afterward so the shared onlinestartlocal.nw fixture is not left dirty."""
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
        cleanup_bigfile()

    return results
