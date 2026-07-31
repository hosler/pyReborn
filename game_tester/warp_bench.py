"""Bot-driven level-link warp benchmark: where does link-warp latency go?

Walks a bot through the link destinations the server actually advertises for
its current level, timing each transition, then repeats so every destination is
measured COLD (first visit, server must build and stream the board) and WARM
(re-entry, the board is already in client.levels). That pair is the whole point:

    cold - warm ~= what the server round trip costs us
    warm        ~= what our own client costs us

Optimising without that split is how this investigation previously went wrong.

Per warp it records:
    name    our PLI_LEVELWARP to the server's PLO_LEVELNAME (round trip)
    board   the announcement to the 8 KB board landing
    render  to _tiles_level_name == target, i.e. the board becoming the ACTIVE
            render board - this is what gates the "Loading level..." overlay
            and the frozen-frame transition hold
    arrive  to bot.level == target, the authoritative "we are there" signal
            (position-derived. See GameBot.warp_to for why the raw
            _current_level_name field is not trustworthy here)

Usage:
    python -m game_tester.warp_bench [--host H] [--port P]
                                     [--account A] [--password P]
                                     [--rounds N] [--max-levels N]

Against a live server, point --host/--port at it and pass real credentials.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Dict, List, Optional

from .game_bot import GameBot

# A warp the server never confirms should be recorded as a failure, not hang
# the run. Deliberately above GameBot.warp_to's own 5s ceiling.
_WARP_TIMEOUT_S = 8.0


class WarpSample:
    __slots__ = ("target", "cold", "t_name", "t_board", "t_render",
                 "t_arrive", "ok", "note")

    def __init__(self, target: str, cold: bool):
        self.target = target
        self.cold = cold
        self.t_name = self.t_board = self.t_render = self.t_arrive = None
        self.ok = False
        self.note = ""


def _link_destinations(client, level: str) -> List[str]:
    """Distinct .nw destinations the server advertised for `level`."""
    out = []
    for link in client.links.get(level, []) or []:
        dest = None
        # 'dest_level' is what packet_codec/level.py parse_level_link emits;
        # the rest are tolerated in case another producer names it differently.
        for key in ("dest_level", "dest", "destination", "level", "newlevel"):
            value = link.get(key) if isinstance(link, dict) else None
            if isinstance(value, str) and value:
                dest = value
                break
        if (dest and dest.lower().endswith(".nw")
                and dest != level and dest not in out):
            out.append(dest)
    return out


def _timed_warp(bot: GameBot, target: str, x: float, y: float) -> WarpSample:
    """One warp, timing each stage from the packet stream and client state."""
    client = bot.client
    cold = target not in client.levels
    sample = WarpSample(target, cold)

    from pyreborn.packets import PacketID
    t0 = time.monotonic()
    orig_handle = client._handle_packet

    def _handle(pid, data):
        if pid == PacketID.PLO_LEVELNAME and sample.t_name is None:
            sample.t_name = time.monotonic() - t0
        elif pid in (PacketID.PLO_BOARDPACKET, 101) and sample.t_board is None:
            sample.t_board = time.monotonic() - t0
        return orig_handle(pid, data)

    client._handle_packet = _handle
    try:
        if not client.warp_to_level(target, x, y):
            sample.note = "send failed"
            return sample
        deadline = time.monotonic() + _WARP_TIMEOUT_S
        while time.monotonic() < deadline:
            bot.update(0.02)
            if sample.t_render is None and client._tiles_level_name == target:
                sample.t_render = time.monotonic() - t0
            if bot.level == target:
                sample.t_arrive = time.monotonic() - t0
                sample.ok = True
                break
        if not sample.ok:
            sample.note = "never arrived"
    finally:
        client._handle_packet = orig_handle
    return sample


def _fmt(value: Optional[float]) -> str:
    return "    -" if value is None else f"{value * 1000:5.0f}"


def run(host: str, port: int, account: str, password: str,
        rounds: int, max_levels: int, start_level: str = "",
        version: str = "6.037") -> int:
    bot = GameBot(account, host, port, password=password, version=version)
    if not bot.connect():
        print(f"connect/login failed for {account}@{host}:{port}")
        return 1
    try:
        client = bot.client
        for _ in range(40):
            bot.update(0.05)
        if start_level:
            # Spawn levels frequently have no doors at all, so the caller can
            # nominate somewhere with links. Warping there is not measured.
            print(f"positioning at {start_level} ...")
            _timed_warp(bot, start_level, 32.0, 32.0)
            for _ in range(20):
                bot.update(0.05)
        home = bot.level or client._current_level_name
        print(f"home level: {home}")

        targets = _link_destinations(client, home)
        if not targets:
            print("no link destinations advertised for this level - stand "
                  "somewhere with doors, or the server sends no PLO_LEVELLINK "
                  "here. Nothing to measure.")
            return 2
        targets = targets[:max_levels]
        print(f"measuring {len(targets)} destination(s) x {rounds} round(s): "
              f"{', '.join(targets)}\n")

        samples: List[WarpSample] = []
        print(f"{'#':>2} {'level':<28} {'cold':<5} "
              f"{'name':>5} {'board':>6} {'render':>7} {'arrive':>7}  note")
        n = 0
        for rnd in range(rounds):
            for target in targets:
                n += 1
                sample = _timed_warp(bot, target, 32.0, 32.0)
                samples.append(sample)
                print(f"{n:>2} {sample.target:<28} "
                      f"{'yes' if sample.cold else 'no':<5} "
                      f"{_fmt(sample.t_name)} {_fmt(sample.t_board)} "
                      f"{_fmt(sample.t_render)} {_fmt(sample.t_arrive)}  "
                      f"{sample.note}", flush=True)
                # Return home so the next warp starts from a consistent place;
                # not measured, and failures here are not the bot's fault.
                _timed_warp(bot, home, 32.0, 32.0)

        _summarize(samples)
        return 0
    finally:
        try:
            bot.disconnect()
        except Exception:
            pass


def _summarize(samples: List[WarpSample]) -> None:
    ok = [s for s in samples if s.ok and s.t_arrive is not None]
    print()
    print(f"{len(ok)}/{len(samples)} warps arrived")
    if not ok:
        print("nothing to summarize - every warp failed, so the timings above "
              "measure a rejection path, not latency")
        return

    def stats(values: List[float], label: str) -> None:
        if not values:
            return
        # median is the honest middle for a handful of samples; max is what
        # the player actually notices.
        values = sorted(values)
        print(f"  {label:<18} n={len(values):<3} "
              f"median {statistics.median(values) * 1000:6.0f}ms  "
              f"max {values[-1] * 1000:6.0f}ms")

    cold = [s.t_arrive for s in ok if s.cold]
    warm = [s.t_arrive for s in ok if not s.cold]
    stats(cold, "cold arrive")
    stats(warm, "warm arrive")
    stats([s.t_name for s in ok if s.t_name is not None], "round trip (name)")
    stats([s.t_render for s in ok if s.t_render is not None], "renderable")

    if cold and warm:
        delta = statistics.median(cold) - statistics.median(warm)
        print(f"\n  cold - warm = {delta * 1000:.0f}ms  <- the server round "
              f"trip + board build/stream")
        print(f"  warm        = {statistics.median(warm) * 1000:.0f}ms  <- "
              f"our own client cost on an already-cached board")


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m game_tester.warp_bench",
        description="Measure level-link warp latency with a bot.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=14900)
    parser.add_argument("--account", default="warpbench")
    parser.add_argument("--password", default="warpbench")
    parser.add_argument("--rounds", type=int, default=3,
                        help="passes over the destination list (default 3); "
                             "the first is cold, later ones warm")
    parser.add_argument("--max-levels", type=int, default=4,
                        help="cap destinations measured (default 4)")
    parser.add_argument("--version", default="6.037",
                        help="protocol version; classic servers need a 2.x "
                             "value (see version_probe.py)")
    parser.add_argument("--from", dest="start_level", default="",
                        help="warp here before measuring (spawn levels often "
                             "have no doors); not itself measured")
    args = parser.parse_args(argv)
    return run(args.host, args.port, args.account, args.password,
               args.rounds, args.max_levels, args.start_level, args.version)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
