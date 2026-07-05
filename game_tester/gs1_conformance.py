"""
gs1_conformance - GS1 behavioral CONFORMANCE suite (differential oracle).

Runs the SAME GS1 NPC script on two servers and diffs the *client-observable*
effects:

  * pygserver    - our Python server hosting the reborn_protocol.gs1 interpreter
                   via pygserver/gs1_host.py  (the implementation under test)
  * GServer-v2   - the canonical C++ ANTLR GS1 engine in bin/gs2emu, run
                   serverside=true  (the ORACLE)

This closes the biggest GS1 blind spot: until now every GS1 test was
ours-vs-our-interpreter, with no executable oracle. Here the oracle is the
real engine gs1_host.py was written against.

Design (see memory gs1-gs2-real-server-testing #2): we compare DECODED client
state, not raw packet bytes. For each GS1 command family a fixture NPC runs one
small script on `playerenters`; a pyReborn GameBot warps onto it, pumps the
client, and we read the resulting state (player props / NPC props / current
level). The decoded-protocol layer both servers already share does the hard
part, and we sidestep fragile trace parsing.

The GS1 script body is IDENTICAL on both servers; only the level *packaging*
(where the .nw lives, config) differs. Fixtures are authored here and written
to game_tester/fixtures/gs1/*.nw (self-contained, not the live world).

CLI (mirrors --gs2):
    python -m game_tester --gs1                    # spawn BOTH, diff (the suite)
    python -m game_tester --gs1 --host H --port P  # capture ONE server's effects

It SKIPS gracefully (clear message, non-failing) when the gs2emu binary or a
server can't be brought up, so it never blocks CI.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .game_bot import GameBot, Issue
from .reporter import TestResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent                 # pyReborn/game_tester
_PYREBORN = _HERE.parent                                # pyReborn
_REPO = _PYREBORN.parent                                # opengraal2
_FIXTURES = _HERE / "fixtures" / "gs1"                  # authored .nw fixtures
_GS2EMU_BIN = _REPO / "GServer-v2" / "bin"              # prebuilt oracle server
_PYGSERVER_DIR = Path(os.environ.get("PYGSERVER_DIR", _REPO / "pygserver"))

DEST_LEVEL = "qa_gs1_dest.nw"   # empty warp destination (no NPC)


def _issue(sev: str, desc: str) -> Issue:
    return Issue(timestamp=time.time(), severity=sev, category="gs1conf",
                 description=desc)


# ---------------------------------------------------------------------------
# The case table  --  one GS1 command family per row.
#
#   body   : GS1 statements run inside `if (playerenters) { ... }`
#   kind   : 'player' -> observe the acting player's decoded props
#            'npc'    -> observe the fixture NPC's decoded props
#            'warp'   -> observe the level the player ends up on
#   field  : which decoded field to read (see _observe)
#
# Add a family: append a row. That's the whole extension surface.
# ---------------------------------------------------------------------------
@dataclass
class GS1Case:
    name: str
    family: str
    body: str
    kind: str
    field: str
    # A KNOWN, documented pygserver<->oracle divergence: the suite expects
    # these to DIFFER (so it stays CI-green on the known state and only goes
    # red on a NEW divergence or a regression that makes them match). See the
    # `note` for the grounded explanation.
    expect_divergence: bool = False
    note: str = ""


CASES: List[GS1Case] = [
    # --- player-targeting: setplayerprop message codes + stat writes --------
    GS1Case("nickname", "setplayerprop #n (nickname)",
            "setplayerprop #n,QAConfNick;", "player", "nickname"),
    GS1Case("head", "setplayerprop #3 (head image)",
            "setplayerprop #3,qahead.png;", "player", "head_image"),
    GS1Case("body", "setplayerprop #8 (body image)",
            "setplayerprop #8,qabody.png;", "player", "body_image"),
    GS1Case("swordpower", "playerswordpower = N",
            "playerswordpower = 3;", "player", "sword_power"),
    GS1Case("hearts_set", "playerhearts = N (absolute)",
            "playerhearts = 2.5;", "player", "hearts"),
    # --- NPC-targeting: setimg / message ------------------------------------
    # (setani -> NPCProp::GANI(12) uses the generation-sensitive
    # PropertyGaniOrBowGif serializer; its wire form isn't a clean gs1_host
    # command observable, so it's intentionally left out.)
    GS1Case("npc_image", "setimg (NPC image)",
            "setimg qaconf_npc.png;", "npc", "image"),
    GS1Case("npc_message", "message (NPC chat bubble)",
            "message HelloFromNPC;", "npc", "message"),
    # --- warp ---------------------------------------------------------------
    GS1Case("warp", "setlevel2 (warp the player)",
            f"setlevel2 {DEST_LEVEL},20,20;", "warp", "level"),
    # --- #C0-#C7 colour codes: classic colour NAMES, not raw indices ---------
    # The oracle resolves #C values as classic colour names (Character.h
    # ClassicColors / GS1Visitor::getColorValueFromString): a bare number like
    # "9" is not a name -> slot 0, and a real name -> its enum index. This was a
    # divergence (gs1_host treated the value as a raw palette index) — now fixed
    # in gs1_host._resolve_color, so these must MATCH the oracle both ways.
    GS1Case("color_player_badname", "setplayerprop #C0,9 (non-name -> 0)",
            "setplayerprop #C0,9;", "player", "color0",
            note="'9' is not a classic colour name, so the slot resolves to 0 "
                 "(WHITE) on both, not the raw index 9."),
    GS1Case("color_player_name", "setplayerprop #C0,red (name -> index 4)",
            "setplayerprop #C0,red;", "player", "color0",
            note="'red' is ClassicColors index 4."),
    # (No non-name NPC case: an NPC's default colour[0] is already 0, so setting
    # it to 0 is a no-op the dirty-diff won't transmit and the client can't
    # observe it. The shared _resolve_color path is covered by
    # color_player_badname; color_npc_name covers the NPC setcharprop path.)
    GS1Case("color_npc_name", "setcharprop #C0,blue (name -> index 10)",
            "setcharprop #C0,blue;", "npc", "color0",
            note="'blue' is ClassicColors index 10."),
]


# ---------------------------------------------------------------------------
# Fixture authoring
# ---------------------------------------------------------------------------
def _empty_board() -> str:
    """64 rows of tile 0 (walkable)."""
    row = "AA" * 64
    return "\n".join(f"BOARD 0 {y} 64 0 {row}" for y in range(64))


def build_level_nw(body: str, npc_x: float = 30, npc_y: float = 30) -> str:
    """A GLEVNW01 level whose single NPC runs `body` on playerenters.

    This exact text is ingested by BOTH pygserver (level._parse_nw_file NPC
    block) and gs2emu (GServer LevelLoader) - the format is shared.
    """
    npc = (f"NPC - {npc_x} {npc_y}\n"
           f"if (playerenters) {{\n"
           f"{body}\n"
           f"}}\n"
           f"NPCEND")
    return f"GLEVNW01\n{_empty_board()}\n{npc}\n"


def generate_fixtures(dest: Path = _FIXTURES) -> List[str]:
    """(Re)write all case levels + the warp destination into `dest`.

    Returns the list of .nw filenames written. Single source of truth = CASES.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for c in CASES:
        fn = f"qa_gs1_{c.name}.nw"
        (dest / fn).write_text(build_level_nw(c.body))
        written.append(fn)
    # empty destination for the warp case (no NPC, so no re-warp loop)
    (dest / DEST_LEVEL).write_text(f"GLEVNW01\n{_empty_board()}\n")
    written.append(DEST_LEVEL)
    return written


# ---------------------------------------------------------------------------
# Observation  --  read decoded client state per case
# ---------------------------------------------------------------------------
def _fmt(v) -> str:
    """Normalise a value to a canonical string so diffs are exact."""
    if v is None:
        return "<none>"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, bool):
        return str(v)
    return str(v)


def _basename(level: Optional[str]) -> str:
    return (level or "").split("/")[-1]


def _current_npc(bot: GameBot) -> Optional[dict]:
    """The fixture NPC on the current level: the one nearest (30,30).

    (Each fixture level has exactly one scripted NPC; nearest-to-30,30 is a
    robust pick even if a stray default NPC exists.)"""
    npcs = bot.client.npcs
    if not npcs:
        return None
    return min(npcs.values(),
               key=lambda n: (n.get("x", 0) - 30) ** 2 + (n.get("y", 0) - 30) ** 2)


def _observe(bot: GameBot, case: GS1Case) -> str:
    p = bot.client.player
    if case.kind == "player":
        if case.field == "color0":
            cols = getattr(p, "colors", None) or []
            return _fmt(cols[0]) if cols else "<none>"
        return _fmt(getattr(p, case.field, None))
    if case.kind == "npc":
        npc = _current_npc(bot)
        if npc is None:
            return "<no-npc>"
        if case.field == "color0":
            cols = npc.get("colors") or []
            return _fmt(cols[0]) if cols else "<none>"
        return _fmt(npc.get(case.field))
    if case.kind == "warp":
        return _basename(bot.client._current_level_name)
    return "<?>"


# ---------------------------------------------------------------------------
# Capture  --  drive one server through every case
# ---------------------------------------------------------------------------
def _pump(bot: GameBot, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        bot.update(0.05)


def _run_case(bot: GameBot, case: GS1Case, settle: float) -> str:
    level = f"qa_gs1_{case.name}.nw"
    if case.kind == "warp":
        # the NPC warps us straight back off this level, so don't use the
        # strict warp_to (which waits for level==source); just fire the warp
        # request and watch where we land.
        bot.client.warp_to_level(level, 32, 32)
        deadline = time.time() + settle + 4.0
        while time.time() < deadline:
            bot.update(0.05)
            cur = _basename(bot.client._current_level_name)
            if cur and cur != level:
                break
        _pump(bot, 0.6)
        return _observe(bot, case)

    bot.warp_to(level, 32, 32)          # waits until we're on the level
    _pump(bot, settle)                  # let playerenters run + props arrive
    return _observe(bot, case)


def capture_effects(host: str, port: int, cases: List[GS1Case] = CASES,
                    account: str = "testbot1", settle: float = 1.8
                    ) -> Optional[Dict[str, str]]:
    """Connect a bot to host:port and record the observed effect of each case.

    Returns {case_name: observed_string}, or None if the bot can't connect
    (server unreachable)."""
    bot = GameBot(account, host, port)
    if not bot.connect():
        return None
    out: Dict[str, str] = {}
    try:
        for case in cases:
            try:
                out[case.name] = _run_case(bot, case, settle)
            except Exception as e:  # noqa: BLE001 - never let one case abort the sweep
                out[case.name] = f"<error: {e}>"
    finally:
        bot.disconnect()
    return out


# ---------------------------------------------------------------------------
# Server lifecycle  (self-contained; both spawned on free ports)
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(host: str, port: int, proc: subprocess.Popen,
               timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class _Server:
    """A spawned server: process + connection info + teardown."""
    def __init__(self, name: str, proc: subprocess.Popen, host: str,
                 port: int, workdir: Path, log: Path):
        self.name, self.proc = name, proc
        self.host, self.port = host, port
        self.workdir, self.log = workdir, log

    def stop(self):
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=5)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def log_tail(self, n: int = 2000) -> str:
        try:
            return self.log.read_text(errors="replace")[-n:]
        except OSError:
            return "(no log)"


def spawn_pygserver(fixtures: Path) -> Optional[_Server]:
    """Spawn our pygserver against a throwaway dir seeded with the fixtures."""
    run_server = _PYGSERVER_DIR / "run_server.py"
    if not run_server.exists():
        return None
    workdir = Path(tempfile.mkdtemp(prefix="gs1conf_pyg_"))
    for sub in ("accounts", "npcs", "world", "config"):
        (workdir / sub).mkdir()
    # start level + all fixtures
    start = _PYGSERVER_DIR / "levels" / "onlinestartlocal.nw"
    if start.exists():
        shutil.copy(start, workdir / "world" / "onlinestartlocal.nw")
    for nw in fixtures.glob("*.nw"):
        shutil.copy(nw, workdir / "world" / nw.name)
    port = _free_port()
    (workdir / "config" / "serveroptions.txt").write_text(
        f"serverport = {port}\n"
        "noverifylogin = true\n"
        "startlevel = onlinestartlocal.nw\n"
        "startx = 30\nstarty = 30.5\n"
        "staff = testbot1,testbot2\n"
    )
    log = workdir / "server.log"
    env = dict(os.environ)
    env["PYGSERVER_QA"] = "1"          # keep it fully offline (no listserver)
    with open(log, "wb") as lf:
        proc = subprocess.Popen(
            [sys.executable, str(run_server), str(workdir)],
            cwd=str(_PYGSERVER_DIR), stdout=lf, stderr=subprocess.STDOUT,
            env=env, start_new_session=True)
    srv = _Server("pygserver", proc, "127.0.0.1", port, workdir, log)
    if not _wait_port(srv.host, srv.port, proc):
        srv.stop()
        return None
    return srv


def spawn_gs2emu(fixtures: Path) -> Optional[_Server]:
    """Spawn the C++ oracle from a COPY of GServer-v2/bin (never touches the
    checkout): listserver pointed at 127.0.0.1 so it can't reach the public
    listserver, and the fixtures dropped into world/."""
    binary = _GS2EMU_BIN / "gs2emu"
    if not binary.exists():
        return None
    workdir = Path(tempfile.mkdtemp(prefix="gs1conf_gs2_"))
    run = workdir / "bin"
    shutil.copytree(_GS2EMU_BIN, run)
    cfg = run / "servers" / "default" / "config" / "serveroptions.txt"
    port = _free_port()
    lines = cfg.read_text(encoding="latin-1").split("\n")
    patched = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("listip"):
            patched.append("listip = 127.0.0.1"); continue   # no public listserver
        if s.startswith("serverport"):
            patched.append(f"serverport = {port}"); continue
        patched.append(ln)
    cfg.write_text("\n".join(patched), encoding="latin-1")
    world = run / "servers" / "default" / "world"
    for nw in fixtures.glob("*.nw"):
        shutil.copy(nw, world / nw.name)
    log = workdir / "gs2emu.log"
    with open(log, "wb") as lf:
        # start_new_session so it survives in its own group; we kill it on stop.
        proc = subprocess.Popen(["./gs2emu"], cwd=str(run),
                                stdout=lf, stderr=subprocess.STDOUT,
                                start_new_session=True)
    srv = _Server("gs2emu", proc, "127.0.0.1", port, workdir, log)
    if not _wait_port(srv.host, srv.port, proc):
        srv.stop()
        return None
    return srv


# ---------------------------------------------------------------------------
# Orchestration + diff
# ---------------------------------------------------------------------------
def _diff_results(pyg: Dict[str, str],
                  oracle: Optional[Dict[str, str]]) -> List[TestResult]:
    results: List[TestResult] = []
    for case in CASES:
        got = pyg.get(case.name, "<missing>")
        name = f"gs1conf_{case.name}"
        if oracle is None:
            # oracle unavailable -> informational, non-failing
            results.append(TestResult(
                name, True, 0.0,
                f"[oracle skipped] {case.family}: pygserver={got!r}", []))
            continue
        want = oracle.get(case.name, "<missing>")
        differ = got != want
        detail = f"{case.family}: pygserver={got!r} gs2emu(oracle)={want!r}"
        if case.expect_divergence:
            # known bug: differing is the expected (green) state; MATCHING now
            # means behavior changed and the table needs revisiting.
            passed = differ
            if differ:
                detail = f"[KNOWN DIVERGENCE] {detail}  ({case.note})"
                issues = []
            else:
                detail = (f"[UNEXPECTED MATCH - was a known divergence] {detail}"
                          f"  ({case.note})")
                issues = [_issue("MEDIUM",
                                 f"{case.family}: known divergence now matches "
                                 "- update the case table")]
        else:
            passed = not differ
            issues = [] if passed else [_issue(
                "HIGH", f"{case.family}: pygserver={got!r} != oracle={want!r}")]
        results.append(TestResult(name, passed, 0.0, detail, issues))
    return results


def _print_capture(title: str, cap: Dict[str, str]):
    print(f"\n  [{title}]")
    for case in CASES:
        print(f"    {case.name.ljust(14)} {case.family.ljust(34)} "
              f"-> {cap.get(case.name, '<missing>')!r}")


def run_gs1_conformance(host: Optional[str] = None, port: Optional[int] = None,
                        explicit_target: bool = False) -> List[TestResult]:
    """Entry point for `--gs1`.

    * explicit_target (a --host/--port was given): capture that ONE server's
      effects and print them (requires the fixtures to be loadable there;
      handy for pointing at a hand-run gs2emu/pygserver).
    * otherwise: spawn BOTH servers, capture, diff. Oracle-skip is graceful.
    """
    generate_fixtures()

    if explicit_target:
        cap = capture_effects(host or "localhost", port or 14900)
        if cap is None:
            return [TestResult("gs1conf_connect", False, 0.0,
                               f"could not connect to {host}:{port}", [])]
        _print_capture(f"{host}:{port}", cap)
        return [TestResult(f"gs1conf_{c.name}", True, 0.0,
                           f"{c.family}: {cap.get(c.name)!r}", [])
                for c in CASES]

    # ---- full differential run -------------------------------------------
    pyg_srv = spawn_pygserver(_FIXTURES)
    if pyg_srv is None:
        return [TestResult("gs1conf_pygserver", False, 0.0,
                           "could not start pygserver (checkout missing?)", [])]
    gs2_srv = None
    try:
        gs2_srv = spawn_gs2emu(_FIXTURES)
        if gs2_srv is None:
            print("\n  [note] gs2emu oracle unavailable "
                  f"(no binary at {_GS2EMU_BIN/'gs2emu'} or it failed to "
                  "start) - reporting pygserver capture only, no diff.")

        cap_pyg = capture_effects(pyg_srv.host, pyg_srv.port)
        if cap_pyg is None:
            return [TestResult("gs1conf_capture", False, 0.0,
                               "bot failed to connect to pygserver", [])]
        cap_oracle = None
        if gs2_srv is not None:
            cap_oracle = capture_effects(gs2_srv.host, gs2_srv.port)
            if cap_oracle is None:
                print("  [note] bot failed to connect to gs2emu - "
                      f"log tail:\n{gs2_srv.log_tail(800)}")

        _print_capture("pygserver (under test)", cap_pyg)
        if cap_oracle is not None:
            _print_capture("gs2emu  (C++ oracle)", cap_oracle)
        return _diff_results(cap_pyg, cap_oracle)
    finally:
        if gs2_srv is not None:
            gs2_srv.stop()
        pyg_srv.stop()


if __name__ == "__main__":       # allow: python -m game_tester.gs1_conformance
    for r in run_gs1_conformance():
        print(("[PASS]" if r.passed else "[FAIL]"), r.name, "-", r.details)
