"""Where does a level-link warp's wall time actually go?

Run the REAL pygame client with this wrapper and walk through doors. Every
level transition prints one line splitting the delay into the parts we can act
on and the parts we cannot:

    warp->name  the server's round trip: our PLI_LEVELWARP to its PLO_LEVELNAME
    name->board the server building/streaming the 8 KB board after announcing
    board->live our own cost: board received to it becoming the ACTIVE board
    live->show  the transition hold: active board to the frozen frame lifting
    total       warp sent to the screen moving again
    held        frames spent showing the frozen pre-warp frame
    slowest     worst single frame in the window (client-side stall)
    net         packets/bytes received during the window
    files       assets requested during the window, and how many were pending
                at the end (an asset stampede competing with the board)

The point of the split: `warp->name` and `name->board` are the server and the
link; `board->live` and `live->show` are ours. Optimising the wrong half was
how this investigation went wrong before, so measure first.

    python -m game_tester.warp_trace <account> <password> [host] [port]

Purely observational: it wraps methods to take timestamps and never changes
what the client does.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

# A transition that never completes (rejected warp, dropped board) must not
# hold a half-finished row forever; print what we got and move on.
_STALE_AFTER_S = 10.0


class _Trace:
    def __init__(self, client):
        self.client = client
        self.reset()

    def reset(self):
        self.target: Optional[str] = None
        self.t_warp = 0.0
        self.t_name = 0.0
        self.t_board = 0.0
        self.t_live = 0.0
        self.frames = 0
        self.worst = 0.0
        self.packets = 0
        self.bytes = 0
        self.files_before = 0
        self.files_requested = 0

    @property
    def active(self) -> bool:
        return self.target is not None

    def start(self, level_name: str):
        if self.active:
            self.finish(note="superseded")
        self.reset()
        self.target = level_name
        self.t_warp = time.monotonic()
        self.files_before = len(getattr(self.client, '_requested_assets', ()) or ())

    def _ms(self, a: float, b: float) -> str:
        if not a or not b or b < a:
            return "    -"
        return f"{(b - a) * 1000:5.0f}"

    def finish(self, note: str = ""):
        if not self.active:
            return
        now = time.monotonic()
        pending = len(getattr(self.client, '_pending_files', ()) or ())
        total = (now - self.t_warp) * 1000
        print(
            f"[warp] {self.target:<28} "
            f"warp->name {self._ms(self.t_warp, self.t_name)}ms  "
            f"name->board {self._ms(self.t_name, self.t_board)}ms  "
            f"board->live {self._ms(self.t_board, self.t_live)}ms  "
            f"live->show {self._ms(self.t_live, now)}ms  "
            f"total {total:5.0f}ms  "
            f"held {self.frames:3d}f  slowest {self.worst * 1000:4.0f}ms  "
            f"net {self.packets:4d}p/{self.bytes // 1024:4d}KB  "
            f"files +{self.files_requested}/{pending} pending"
            + (f"  [{note}]" if note else ""),
            flush=True,
        )
        self.reset()


def install(game) -> _Trace:
    """Wrap the timing points on a live GameClient. Observational only."""
    client = game.client
    tr = _Trace(client)

    # 1. our PLI_LEVELWARP goes out
    orig_warp = client.warp_to_level

    def warp_to_level(level_name, x=None, y=None, *a, **kw):
        tr.start(level_name)
        return orig_warp(level_name, x, y, *a, **kw)

    client.warp_to_level = warp_to_level

    # 2/3. the server answers: PLO_LEVELNAME, then the board. Counted from the
    # packet stream so a board arriving via PLO_RAWDATA is seen too.
    from pyreborn.packets import PacketID
    orig_handle = client._handle_packet

    def _handle_packet(pid, data):
        if tr.active:
            tr.packets += 1
            tr.bytes += len(data)
            if pid == PacketID.PLO_LEVELNAME and not tr.t_name:
                tr.t_name = time.monotonic()
            elif pid in (PacketID.PLO_BOARDPACKET, 101) and not tr.t_board:
                tr.t_board = time.monotonic()
        return orig_handle(pid, data)

    client._handle_packet = _handle_packet

    # 4. the destination becomes the ACTIVE render board, and 5. the frozen
    # frame lifts. Sampled per frame rather than hooked, because the release
    # can come from any of several packet handlers.
    orig_render = game._render

    def _render():
        t0 = time.monotonic()
        orig_render()
        dt = time.monotonic() - t0
        if tr.active:
            tr.worst = max(tr.worst, dt)
            if not tr.t_live and client._tiles_level_name == tr.target:
                tr.t_live = time.monotonic()
            if getattr(client, '_local_level_transition', ''):
                tr.frames += 1
            elif tr.t_live:
                tr.finish()
            elif time.monotonic() - tr.t_warp > _STALE_AFTER_S:
                tr.finish(note="never became active")
            tr.files_requested = (
                len(getattr(client, '_requested_assets', ()) or ())
                - tr.files_before)

    game._render = _render
    return tr


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    account, password = argv[0], argv[1]
    host = argv[2] if len(argv) > 2 else "localhost"
    port = int(argv[3]) if len(argv) > 3 else 14900

    from pyreborn import Client
    from pyreborn.pygame_game import GameClient
    from .login import login_client, level_ready

    client = Client(host, port, version="6.037")
    outcome = login_client(client, account, password, timeout=10.0, settle=False)
    if not outcome.ok:
        print(f"login failed: connected={outcome.connected} "
              f"accepted={outcome.accepted} {outcome.rejection}")
        return 1
    for _ in range(80):
        client.update(timeout=0.05)
        if level_ready(client):
            break

    game = GameClient(client)
    install(game)
    print("[warp] tracing installed - walk through doors; Ctrl-C to stop\n",
          flush=True)
    try:
        game.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
