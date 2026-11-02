"""
Pytest controls the pygserver lifecycle for the game_tester QA integration suite.

This module provides:
- `pygserver` (session-scoped): The fixture starts a real pygserver subprocess
  that uses a temporary server directory. Each session gets a fresh accounts/
  directory. Thus, integration tests do not need a manually started server or
  the repository's shared, mutable pygserver/accounts directory.
- `bots` (function-scoped factory): The factory connects
  game_tester.game_bot.GameBot instances to that server. The factory
  disconnects the instances during teardown.

See game_tester/CLAUDE.md / pyReborn/CLAUDE.md for the QA framework this
wraps, and pyReborn/tests/test_qa_pytest.py for the tests that use these
fixtures.
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional

import pytest

from game_tester.local_world import LocalWorld

# Sibling checkout by default; PYGSERVER_DIR env overrides (CI checks the
# repo out inside the workspace rather than as a sibling).
PYGSERVER_DIR = Path(os.environ.get(
    "PYGSERVER_DIR", Path(__file__).parent.parent / "pygserver"))
PYGSERVER_LEVELS_DIR = PYGSERVER_DIR / "levels"
RUN_SERVER = PYGSERVER_DIR / "run_server.py"

# The QA fixture levels the game_tester scenarios warp between (see
# game_tester/test_scenarios.py). Copied from pygserver's own levels/ dir
# rather than the shared funtimes/ world so the fixture is self-contained.
FIXTURE_LEVELS = ["onlinestartlocal.nw", "qa_testlevel.nw", "qa_tier3.nw"]

# Keep the public fixture handle name and its connection/log attributes.
PygserverHandle = LocalWorld


@pytest.fixture(scope="session")
def pygserver(tmp_path_factory):
    """Start the same three QA levels with fresh accounts on a free port."""
    if not RUN_SERVER.exists():
        pytest.skip(f"pygserver checkout not found at {PYGSERVER_DIR}")
    world_dir = tmp_path_factory.mktemp("pygserver_qa_levels")
    for name in FIXTURE_LEVELS:
        src = PYGSERVER_LEVELS_DIR / name
        if src.exists():
            shutil.copy(src, world_dir / name)
    world = LocalWorld(world_dir, start_level="onlinestartlocal.nw",
                       start_xy=(30, 30.5), accounts=())
    try:
        try:
            world.start()
        except PermissionError as exc:
            pytest.skip(f"loopback sockets unavailable: {exc}")
        yield world
    finally:
        world.close()


# Standard recipe for exposing the pass/fail outcome of the running test to
# fixture teardown code (used below to dump the server log tail only when a
# test actually failed).
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def _test_failed(request) -> bool:
    return any(
        getattr(request.node, f"rep_{phase}", None) is not None
        and getattr(request.node, f"rep_{phase}").failed
        for phase in ("setup", "call")
    )


@pytest.fixture
def bots(pygserver: PygserverHandle, request):
    """Create a connected GameBot list with bots(n=1, names=None).

    The fixture disconnects each bot that it created during teardown. If a test
    fails, the fixture also prints the end of the server log to help debugging.
    """
    from game_tester.game_bot import GameBot

    created: List[GameBot] = []

    def _make(n: int = 1, names: Optional[List[str]] = None) -> List[GameBot]:
        names = names or [f"testbot{i + 1}" for i in range(n)]
        made = []
        for name in names:
            bot = GameBot(name, pygserver.host, pygserver.port)
            connected = bot.connect(timeout=15.0)
            created.append(bot)
            made.append(bot)
            if not connected:
                pytest.fail(
                    f"bot {name!r} failed to connect to "
                    f"{pygserver.host}:{pygserver.port}: {bot.get_issues()}"
                )
        return made

    yield _make

    for bot in created:
        bot.disconnect()

    if _test_failed(request):
        print(f"\n----- pygserver log tail ({pygserver.log_path}) -----\n"
              f"{pygserver.log_tail()}\n----- end log tail -----")
