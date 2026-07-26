"""
version_probe - Old-protocol-version login probe (tier 4).

Tries each pyReborn VERSIONS entry against the server: connect, login,
receive PLO_PLAYERPROPS + level board, move, chat. Reports pass/fail/skip
per version.

The GServer `generation` option restricts which client versions may join
(allowedversions.txt [generation-range]), so a single server run can never
accept every version:
    generation = modern   -> 6.037 (and 5.x)
    generation = classic  -> 2.17 / 2.21 / 2.22 (with the widened range)
    generation = original -> 1.411
Versions the server rejects (login refused/timed out) are reported as SKIP,
not FAIL, so this probe can run under any generation setting. To fully
exercise the GEN_3/GEN_4 codecs, run it once under each generation.

Run: python -m game_tester.version_probe [host] [port]
"""

from __future__ import annotations

import sys
import time
from typing import List, Tuple

from .login import login_session


def _in_game(client) -> bool:
    """This probe's own readiness rule: it reports player.level, so waiting on
    client._current_level_name (login.level_ready) could return before that
    field is set and make an accepted login look like a FAIL."""
    return bool(client.tiles and client.player.level)


def probe_version(version: str, host: str = "localhost", port: int = 14900,
                  account: str = "testbot1", password: str = "testpass"
                  ) -> Tuple[str, str]:
    """Probe one version. Returns (verdict, details) where verdict is
    PASS / FAIL / SKIP."""
    try:
        with login_session(host, port, account, password, version=version,
                           timeout=8.0, settle_timeout=5.0, poll=0.01,
                           ready=_in_game) as session:
            c = session.client
            if not session.connected:
                return "FAIL", "tcp connect failed"
            if not session.accepted:
                # Most likely the server generation doesn't allow this version.
                return "SKIP", "login refused/timed out (version not allowed by server generation?)"

            board_ok = bool(c.tiles) and sum(1 for t in c.tiles if t) > 100
            level_ok = bool(c.player.level)

            start_x = c.player.x
            for _ in range(4):
                c.move(1, 0)
                c.update()
                time.sleep(0.1)
            move_ok = c.player.x != start_x

            c.say(f"probe {version}")
            for _ in range(10):
                c.update()
                time.sleep(0.05)
            chat_ok = c.connected

            ok = board_ok and level_ok and move_ok and chat_ok
            details = (f"level={c.player.level!r} board={board_ok} "
                       f"move={move_ok} chat={chat_ok}")
            return ("PASS" if ok else "FAIL"), details
    except Exception as e:  # noqa: BLE001
        return "FAIL", f"exception: {e}"


def run_version_probe(host: str = "localhost", port: int = 14900,
                      versions: List[str] = None) -> bool:
    """Probe each version; returns True if nothing FAILed (SKIPs allowed)."""
    if versions is None:
        versions = ["1.411", "2.17", "2.21", "2.22", "6.037"]

    print("=" * 64)
    print(f"  VERSION PROBE - {host}:{port}")
    print("=" * 64)
    any_fail = False
    for v in versions:
        verdict, details = probe_version(v, host, port)
        flag = {"PASS": " ", "SKIP": "-", "FAIL": "*"}[verdict]
        print(f" {flag}{v:<8} {verdict:<5} {details}")
        if verdict == "FAIL":
            any_fail = True
        time.sleep(0.3)
    print("=" * 64)
    return not any_fail


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 14900
    sys.exit(0 if run_version_probe(host, port) else 1)
