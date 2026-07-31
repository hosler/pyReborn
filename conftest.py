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
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import pytest

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

READY_MARKER = "Server listening on"
STARTUP_TIMEOUT = 20.0
SHUTDOWN_TIMEOUT = 10.0


def _free_port() -> int:
    """Get an OS-assigned free TCP port (a small bind/release race is
    acceptable for a test fixture)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class PygserverHandle:
    """Store connection information and provide log access for the temporary
    QA server."""
    host: str
    port: int
    server_dir: Path
    log_path: Path

    def log_tail(self, chars: int = 4000) -> str:
        try:
            text = self.log_path.read_text(errors="replace")
        except OSError:
            return "(no server log available)"
        return text[-chars:]


@pytest.fixture(scope="session")
def pygserver(tmp_path_factory):
    """Start a real pygserver on a free port against a throwaway server dir.

    The fixture prevents account-state drift. The accounts/ directory is empty
    at the start of every pytest session. Thus, QA scenarios always use fresh
    accounts instead of the repository's shared pygserver/accounts directory.
    """
    if not RUN_SERVER.exists():
        pytest.skip(f"pygserver checkout not found at {PYGSERVER_DIR}")

    server_dir = tmp_path_factory.mktemp("pygserver_qa")
    (server_dir / "accounts").mkdir()
    (server_dir / "npcs").mkdir()
    world_dir = server_dir / "world"
    world_dir.mkdir()
    (server_dir / "config").mkdir()

    for name in FIXTURE_LEVELS:
        src = PYGSERVER_LEVELS_DIR / name
        if src.exists():
            shutil.copy(src, world_dir / name)

    port = _free_port()
    (server_dir / "config" / "serveroptions.txt").write_text(
        f"serverport = {port}\n"
        "noverifylogin = true\n"
        "startlevel = onlinestartlocal.nw\n"
        "startx = 30\n"
        "starty = 30.5\n"
    )

    log_path = server_dir / "server.log"
    handle = PygserverHandle(host="127.0.0.1", port=port,
                             server_dir=server_dir, log_path=log_path)

    env = dict(os.environ)
    # Tell run_server.py this is the offline QA harness (skips forcing
    # enable_listserver/listserver.graal.in - see run_server.py).
    env["PYGSERVER_QA"] = "1"
    # Point the game_tester account-reset helpers (test_scenarios.py) at
    # *this* ephemeral accounts dir instead of the real repo's, in case any
    # wrapped scenario calls them.
    env["PYGSERVER_ACCOUNTS_DIR"] = str(server_dir / "accounts")

    with open(log_path, "wb") as logf:
        proc = subprocess.Popen(
            [sys.executable, str(RUN_SERVER), str(server_dir)],
            cwd=str(PYGSERVER_DIR),
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
        )

    try:
        _wait_for_ready(proc, log_path, handle)
        yield handle
    finally:
        _terminate(proc)


def _wait_for_ready(proc: subprocess.Popen, log_path: Path,
                    handle: PygserverHandle) -> None:
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(
                f"pygserver exited early (code={proc.returncode}) "
                f"before listening:\n{handle.log_tail()}"
            )
        if log_path.exists() and READY_MARKER in log_path.read_text(errors="replace"):
            return
        time.sleep(0.1)

    _terminate(proc)
    pytest.fail(
        f"pygserver did not report '{READY_MARKER}' within "
        f"{STARTUP_TIMEOUT}s:\n{handle.log_tail()}"
    )


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=SHUTDOWN_TIMEOUT)


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
