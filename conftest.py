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
import sys
from pathlib import Path
from typing import List, Optional

import pytest

from game_tester.local_world import LocalWorld

# tests/ is not a package; the offline game factory lives there as a plain module.
sys.path.insert(0, str(Path(__file__).parent / "tests"))

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

#: Every environment variable pyreborn/ and game_tester/ read a per-user path
#: from (asset_paths, prefs, rc_link, gs2_server_crawl, gs2_ui_explorer
#: capture). Unset, each falls back to a directory under $HOME.
HERMETIC_DIRS = {
    "PYREBORN_CACHE_DIR": "cache",
    "XDG_CACHE_HOME": "xdg-cache",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    # An empty content tier for the session: only make_game/make_client
    # point it at the synthetic art, so no other test sees that art.
    "PYREBORN_CONTENT_DIR": "content-empty",
    "PYREBORN_RC_DOWNLOAD_DIR": "rc-downloads",
    "PYREBORN_DATA": "pyreborn-data",
}


def pytest_addoption(parser):
    group = parser.getgroup("frame baseline")
    group.addoption("--frame-baseline-record", metavar="DIR", default=None,
                    help="offline render suite: hash every captured frame "
                         "into DIR (tests/frame_baseline.py); machine-local")
    group.addoption("--frame-baseline-check", metavar="DIR", default=None,
                    help="offline render suite: fail on any captured frame "
                         "that differs from the one recorded in DIR")


def pytest_configure(config):
    from frame_baseline import BASELINE
    try:
        BASELINE.configure(config.getoption("--frame-baseline-record"),
                           config.getoption("--frame-baseline-check"))
    except ValueError as exc:
        raise pytest.UsageError(str(exc))


def pytest_sessionfinish(session):
    from frame_baseline import BASELINE
    BASELINE.summary = BASELINE.finish()


def pytest_terminal_summary(terminalreporter):
    from frame_baseline import BASELINE
    if getattr(BASELINE, "summary", ""):
        terminalreporter.write_line(BASELINE.summary)


@pytest.fixture(autouse=True)
def _frame_baseline_test(request):
    """Name the running test for the frame baseline's capture keys."""
    from frame_baseline import BASELINE
    if BASELINE.active:
        BASELINE.current_test = request.node.nodeid.split("/")[-1]
    yield


@pytest.fixture(autouse=True, scope="session")
def _hermetic_user_dirs(tmp_path_factory):
    """Keep the whole run off the developer's real download cache, prefs,
    content directories and download folders.

    Every location is resolved per call from the environment, so setting it
    once for the session is enough."""
    root = tmp_path_factory.mktemp("user-dirs")
    mp = pytest.MonkeyPatch()
    for name, sub in HERMETIC_DIRS.items():
        (root / sub).mkdir()
        mp.setenv(name, str(root / sub))
    yield root
    mp.undo()


@pytest.fixture(autouse=True)
def _private_qa_state(tmp_path, monkeypatch):
    """Fixture ownership markers and backups live in the QA state directory;
    keep every test out of the user's real one."""
    monkeypatch.setenv("PYREBORN_QA_SERVERS_DIR", str(tmp_path / "qa-state"))


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


@pytest.fixture
def sim_time(monkeypatch):
    """Pin simulation time for every Clock: ``sim_time(100.0)`` makes
    ``Clock.sim_now()`` answer 100.0 (``sim_time(fn)`` answers ``fn()``).

    For unit tests of one simulation function at chosen time points. Frame
    time (``frame_now``) is untouched. Tests of tick counts drive real ticks
    instead (``game.ticks(n)`` / ``clock.begin_tick()``)."""
    from pyreborn.clock import Clock

    def pin(value):
        read = value if callable(value) else (lambda: value)
        monkeypatch.setattr(Clock, "sim_now", lambda self: read())
    return pin


@pytest.fixture(scope="session")
def _offline_asset_root(tmp_path_factory):
    """Synthetic art and the pinned bundled tier, generated once per session."""
    return tmp_path_factory.mktemp("offline-assets")


@pytest.fixture
def _offline_env(monkeypatch, _offline_asset_root):
    """The fixture clock, the synthetic content tier and the pinned bundled
    tier, for the duration of one test."""
    from offline_game import install_determinism, pin_assets
    install_determinism(monkeypatch)
    pin_assets(monkeypatch, _offline_asset_root)


@pytest.fixture
def make_client(_offline_env, tmp_path):
    """Library-only twin of make_game: ``client = make_client(npcs=[...])``
    returns the populated Client with no GameClient, window or sound."""
    from offline_game import build_client

    made = []

    def _make(**knobs):
        client = build_client(root=tmp_path / f"world{len(made)}", **knobs)
        made.append(client)
        return client

    yield _make
    for client in made:
        client.server.close()


@pytest.fixture
def make_game(_offline_env, tmp_path):
    """Factory for offline pygame games: ``game = make_game(npcs=[...], ...)``.

    Returns a real GameClient over a real Client with no socket, in dummy SDL,
    populated by an in-process pygserver. Every game it built is shut down at
    teardown (the window size is not written to prefs), including one whose
    start() raised. Knobs and the ``game.frames(n)`` / ``game.feed(id, data)``
    / ``game.server`` helpers are documented on tests/offline_game.py and in
    CLAUDE.md "Offline game fixture"."""
    from offline_game import build_game

    built = []
    count = [0]

    def _make(**knobs):
        count[0] += 1
        return build_game(root=tmp_path / f"world{count[0]}",
                          register=built.append, **knobs)

    yield _make
    from offline_game import shutdown_games
    shutdown_games(built)
