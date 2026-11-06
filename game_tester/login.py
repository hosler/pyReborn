"""One transactional "connect, log in, settle, tear down" for the QA harnesses.

Every harness in here (GameBot, version_probe, behaviour_fingerprint,
render_smoke, the playtest daemon, ...) grew its own copy of the same
sequence, and the failure paths are the part that kept getting forgotten: a
refused login used to leave the socket open and the account half-logged-in on
the server, so the next run of the same suite met a contaminated account (see
GameBot.connect's history).

Two entry points:

- `login_client(client, ...)` runs the sequence against a client the CALLER
  owns and reports a structured `LoginOutcome` instead of a bare bool - a
  connect failure, a rejection (with the server's reason) and "logged in but
  the board never arrived" are three different things and callers classify
  them differently.
- `login_session(...)` owns the client for the duration of a `with` block and
  guarantees the teardown, including when the body raises.

The settle poll is parameterised (`ready`, `settle_timeout`, `poll`, `sleep`)
because the existing call sites disagree on what "in-game" means and on their
poll cadence, and those timings are part of their reported output.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional


@dataclass
class LoginOutcome:
    """What happened while getting one client in-game."""

    client: Any
    #: Version string the client ended up using (`Client.version`), which a
    #: client that renegotiates on its own may have changed.
    version: str = ""
    #: Version this attempt asked for, before any renegotiation.
    requested_version: str = ""
    connected: bool = False
    accepted: bool = False
    #: True once `ready(client)` held; False if the settle poll timed out or
    #: was skipped (`settle=False`).
    settled: bool = False
    #: Server's rejection text (PLO_DISCMESSAGE), "" when it gave none.
    rejection: str = ""

    @property
    def ok(self) -> bool:
        """Connected AND logged in. Says nothing about the board arriving."""
        return self.connected and self.accepted


def level_ready(client: Any) -> bool:
    """True once the level we logged into has both a name and a board.

    On a gmap spawn the board arrives long before the login stream is over:
    the server still has the segment's chests/signs/baddies, the props of
    every player already in the world and the adjacent segments queued, and
    the .gmap file (which the client requests on PLO_LEVELNAME) is served
    after all of that. A caller that warps as soon as connect() returns then
    files those in-flight packets under the warp target (chest (60,46) of
    chicken1.nw showing up in onlinestartlocal.nw) and the late grid flips
    its coordinate frame. So on a gmap spawn also wait for the grid: its
    arrival proves the login stream has been drained. `is_gmap` already
    holds when the board lands - PLO_PLAYERWARP2 (grid offsets) travels in
    the same write as the board (pygserver player.py _send_level) and the
    .gmap PLO_LEVELNAME follows right behind - so this does not depend on
    the announcement having been processed yet. A failed map download or a
    three-second grace after name+board lets servers with missing map files
    settle too.
    """
    if not (getattr(client, "_current_level_name", "") and
            getattr(client, "tiles", None)):
        client._level_ready_gmap_wait = None
        return False
    if not getattr(client, "is_gmap", False) or getattr(client, "gmap_grid", None):
        client._level_ready_gmap_wait = None
        return True
    map_name = (getattr(client, "_requested_gmap", "") or
                getattr(client, "gmap_name", ""))
    if not map_name:
        level_name = client._current_level_name
        map_name = level_name if level_name.endswith(".gmap") else ""
    if map_name and map_name in (getattr(client, "_failed_files", None) or ()):
        client._level_ready_gmap_wait = None
        return True
    now = time.monotonic()
    waiting = getattr(client, "_level_ready_gmap_wait", None)
    if waiting is None or (waiting[0] and map_name and waiting[0] != map_name):
        waiting = client._level_ready_gmap_wait = (map_name, now)
    elif map_name and not waiting[0]:
        # Learning the map name later must not restart the name+board grace.
        waiting = client._level_ready_gmap_wait = (map_name, waiting[1])
    return now - waiting[1] >= 3.0


def wait_for_level(client: Any, timeout: float, *, poll: float = 0.1,
                   sleep: float = 0.05,
                   ready: Callable[[Any], bool] = level_ready) -> bool:
    """Pump the client until `ready(client)` or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        client.update(timeout=poll)
        if ready(client):
            return True
        if sleep:
            time.sleep(sleep)
    return ready(client)


def login_client(client: Any, account: str, password: str, *,
                 timeout: float = 10.0, settle: bool = True,
                 settle_timeout: Optional[float] = None,
                 poll: float = 0.1, sleep: float = 0.05,
                 source_address: Optional[str] = None,
                 ready: Callable[[Any], bool] = level_ready) -> LoginOutcome:
    """Connect + log in `client`, optionally waiting for the level to arrive.

    Never disconnects: the caller owns the client either way (GameBot keeps
    its client across reconnects). Use `login_session` when you want the
    teardown handled too.

    `source_address` overrides the native transport's local IP before connect;
    None preserves the bind configured on the supplied client.
    """
    if source_address is not None:
        client._protocol.source_address = source_address
    client._level_ready_gmap_wait = None  # A reconnect starts a fresh grace.
    requested = str(getattr(client, "version", "") or "")
    outcome = LoginOutcome(client=client, version=requested,
                           requested_version=requested)
    if not client.connect():
        return outcome
    outcome.connected = True
    if not client.login(account, password, timeout=timeout):
        outcome.rejection = getattr(client, "disconnect_reason", "") or ""
        return outcome
    outcome.accepted = True
    outcome.version = str(getattr(client, "version", "") or requested)
    if settle:
        outcome.settled = wait_for_level(
            client, timeout if settle_timeout is None else settle_timeout,
            poll=poll, sleep=sleep, ready=ready)
    return outcome


@contextmanager
def login_session(host: str, port: int, account: str, password: str, *,
                  version: str = "6.037",
                  source_address: Optional[str] = None,
                  client_factory: Optional[Callable[..., Any]] = None,
                  **kwargs: Any) -> Iterator[LoginOutcome]:
    """Own a client for one login, guaranteeing the disconnect.

    Yields the `LoginOutcome` - including failed ones, so the body decides
    whether a rejection is fatal - and disconnects on the way out however the
    block ends. Teardown swallows exceptions: a client whose socket already
    died raises from disconnect(), and that must not mask the body's own
    error (or its result).

    `kwargs` are forwarded to `login_client`.
    """
    if client_factory is None:
        from pyreborn.client import Client
        client_factory = Client
    options = {} if source_address is None else {"source_address": source_address}
    client = client_factory(host, port, version=version, **options)
    try:
        yield login_client(client, account, password, **kwargs)
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
