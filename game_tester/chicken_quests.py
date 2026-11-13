"""chicken_quests - end-to-end exercise for "The Great Egg Heist" (Chicken
Town v2 quest line).

Drives a real GS1-capable client stack (Client + GameClient, SDL dummy
driver - the pattern gs1_client_conformance.py and render_smoke.py already
use) against a LIVE server and walks the STAGED quest line end to end:
Mayor Cluckles (stage 0->1) -> Shelly the witness (stage 1->2) -> the four
eggs, gated inert/hidden below stage 2, west then down into the caves ->
Peep -> Hen Penny's reward -> the Mayor's payoff (stage 2->3) -> the town's
post-quest ambient lines. It also proves the client.-flag relog-persistence
fix: client.eq_stage, the egg flags, and the switched ambient dialogue all
survive a disconnect/reconnect.

Script delivery is REAL by default: the live server sends NPCPROP_SCRIPT for
level-embedded NPCs (PropertyGS1Script::serialize falls back to classic raw
text when generation is MODERN and hasNPCServer() is false - a server-source
fix, not a content one), so game._load_new_npcs() (called every frame by
_pump) picks up client.npcs[id]['script'] off the wire and loads + fires it
in the REAL client engine (ClientGS1) exactly like any other level. Nothing
in this file needs to duplicate that.

Simulated delivery survives as a FALLBACK (CHICKEN_QUESTS_INJECT=1, or
QuestSession(inject_scripts=True)), for exercising this harness/engine
against a server build that regresses delivery again - same seam
gs1_client_conformance.py's 'npc' channel uses (client.npcs[id]['script']
written directly, then _load_new_npcs() does the real parse+fire). Even in
that mode, everything except script TEXT - login, movement, collision,
warps, links, board data, flag wire round-trips - is the real live
connection.

Run:
    GSERVER_ACCOUNTS_DIR=<repo>/funtimes/accounts \
        ../.venv/bin/python -m game_tester.chicken_quests
    CHICKEN_QUESTS_INJECT=1 ../.venv/bin/python -m game_tester.chicken_quests
"""

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reborn_protocol.coords import local_to_world

from pyreborn import Client
from pyreborn.pygame_game import GameClient
from pyreborn.game.constants import PLAYER_STAND_X, PLAYER_STAND_Y

from .login import login_client
import logging
from pyreborn.logutil import log_swallowed
logger = logging.getLogger(__name__)

HOST = os.environ.get("PYREBORN_TEST_HOST", "localhost")
PORT = int(os.environ.get("PYREBORN_TEST_PORT", "14900"))
ACCOUNT = os.environ.get("PYREBORN_TEST_ACCOUNT", "testbot1")
PASSWORD = os.environ.get("PYREBORN_TEST_PASSWORD", "testpass")

# Script delivery: real by default (the live server sends NPCPROP_SCRIPT for
# level NPCs). Set CHICKEN_QUESTS_INJECT=1 to fall back to simulated
# delivery (see QuestSession.__init__ / _deliver_scripts).
INJECT_SCRIPTS = os.environ.get("CHICKEN_QUESTS_INJECT", "0") not in ("0", "", "false", "False")

_HERE = Path(__file__).resolve().parent            # pyReborn/game_tester
_REPO = _HERE.parent.parent                         # the checkout root
_WORLD_DIR = Path(os.environ.get(
    "CHICKEN_WORLD_DIR", str(_REPO / "funtimes" / "world")))

# chicken.gmap grid (WIDTH 3, HEIGHT 3). Interior levels (caves, the
# cave-entrance, the house) are plain, non-gmap levels.
_GMAP_GRID = {
    "chicken4.nw": (0, 0), "chicken5.nw": (1, 0), "chicken6.nw": (2, 0),
    "chicken2.nw": (0, 1), "chicken1.nw": (1, 1), "chicken7.nw": (2, 1),
    "chicken3.nw": (0, 2), "chicken9.nw": (1, 2), "chicken8.nw": (2, 2),
}

# Half the spread of a facing's two touch probes (TOUCH_OFFSETS: 1.05/1.95).
TOUCH_PROBE_HALFSPAN = 0.45

_QUEST_FLAGS = ("eq_stage", "eggq_1", "eggq_2", "eggq_3", "eggq_4",
                "eggq_done", "peep_found", "peep_done", "lever_last",
                "lc_started", "lc_beers", "lc_done")


# ---------------------------------------------------------------------------
# .nw NPC-block parser (minimal - image/x/y header through NPCEND). Mirrors
# pygserver/pygserver/level.py's own NPC-section reader; not imported from
# there since pyReborn's core carries no pygserver dependency.
# ---------------------------------------------------------------------------
def _parse_level_npcs(path: Path) -> List[dict]:
    lines = path.read_text().splitlines()
    npcs: List[dict] = []
    i, n = 0, len(lines)
    while i < n:
        parts = lines[i].split()
        if parts and parts[0] == "NPC" and len(parts) >= 3:
            try:
                nx, ny = float(parts[-2]), float(parts[-1])
            except ValueError:
                i += 1
                continue
            i += 1
            code_lines = []
            while i < n and lines[i].strip() != "NPCEND":
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip NPCEND
            npcs.append({"x": nx, "y": ny, "script": "\n".join(code_lines)})
        else:
            i += 1
    return npcs


_LEVEL_NPC_CACHE: Dict[str, List[dict]] = {}


def _level_npcs(level_name: str) -> List[dict]:
    if level_name not in _LEVEL_NPC_CACHE:
        path = _WORLD_DIR / level_name
        _LEVEL_NPC_CACHE[level_name] = (
            _parse_level_npcs(path) if path.exists() else [])
    return _LEVEL_NPC_CACHE[level_name]


# ---------------------------------------------------------------------------
# Account fixture reset - a prior run's client. flags persist server-side
# (that persistence IS finding 1's fix), so a re-run of this file needs a
# clean slate or it finds every egg already collected and the mayor already
# paid. Mirrors test_scenarios.reset_account_position's account-file idiom.
# ---------------------------------------------------------------------------
def reset_quest_account(account: str = ACCOUNT) -> bool:
    accounts_dir = (os.environ.get("GSERVER_ACCOUNTS_DIR")
                    or os.environ.get("PYGSERVER_ACCOUNTS_DIR"))
    if not accounts_dir:
        return False
    path = Path(accounts_dir) / f"{account}.txt"
    if not path.exists():
        return False
    # The server writes the header CRLF but appends FLAG lines with a bare
    # LF, so the file has mixed endings: keep each line's own.
    text = path.read_text(newline="")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    kept = []
    for line in lines:
        if line.startswith("FLAG client."):
            key = line[len("FLAG client."):].split("=", 1)[0]
            if key in _QUEST_FLAGS:
                continue
        kept.append(line)
    # MAPX/MAPY must name chicken1's gmap cell too: the server resolves the
    # login warp from LEVEL plus this cell, and a stale cell left by a run
    # that ended in another segment (e.g. chicken3) refuses the login with
    # "No level available".
    repl = {"LEVEL": "LEVEL chicken1.nw", "X": "X 30", "Y": "Y 36",
            "MAPX": "MAPX 1", "MAPY": "MAPY 1",
            # Payouts persist now, so zero the purse: Last Call must be
            # paid for by this run's own egg rewards, not earlier runs.
            "GRALATS": "GRALATS 0"}
    seen = {k: False for k in repl}
    out = []
    for line in kept:
        key = line.split(" ", 1)[0]
        if key in repl:
            ending = line[len(line.rstrip("\r\n")):]
            out.append(repl[key] + ending)
            seen[key] = True
        else:
            out.append(line)
    missing = [repl[k] + eol for k, was in seen.items() if not was]
    if missing:
        out[1:1] = missing
    path.write_text("".join(out), newline="")
    return True


# ---------------------------------------------------------------------------
# Frame pump - N real frames (GameClient.step).
# ---------------------------------------------------------------------------
def _pump(game, n: int = 8, dt: float = 0.05):
    for _ in range(n):
        # The real frame, packets waited for briefly (net_timeout) since
        # nothing else paces this loop.
        game.step(dt, strict=True, net_timeout=0.02)


class QuestSession:
    """One live GS1-capable session: real Client + GameClient, plus message
    capture and the level-local <-> world coordinate helpers this exercise
    needs on a gmap world."""

    def __init__(self, account: str = ACCOUNT, password: str = PASSWORD,
                inject_scripts: bool = INJECT_SCRIPTS):
        self.account = account
        self.password = password
        self.client: Optional[Client] = None
        self.game = None
        self.messages: List[str] = []
        # Real delivery is the default (the server now sends NPCPROP_SCRIPT
        # for level NPCs - see module docstring). Injection is a FALLBACK,
        # opt in via CHICKEN_QUESTS_INJECT=1 or inject_scripts=True, for
        # exercising the harness/engine when a server build regresses
        # delivery again.
        self.inject_scripts = inject_scripts
        self._connect()

    def _connect(self):
        self.client = Client(HOST, PORT, version="6.037")
        outcome = login_client(self.client, self.account, self.password,
                               timeout=8.0, settle=False)
        assert outcome.connected and outcome.accepted, (
            f"login failed for {self.account}: {outcome.rejection}")
        for _ in range(20):
            self.client.update(timeout=0.05)
        self.game = GameClient(self.client)
        self.game.running = True
        self.messages = []
        self.game.gs1.on_say = lambda npc_id, text: self.messages.append(text)
        self.game.gs1.on_say2 = lambda text: self.messages.append(text)
        self.game.start()
        _pump(self.game, 10)
        self._deliver_scripts()

    def reconnect(self):
        """Disconnect and log back in - a fresh Client/GameClient/ClientGS1,
        the relog-persistence path (finding 1 / step d's exploit-regression
        check: a fresh engine instance must still see the persisted flags)."""
        self.disconnect()
        self._connect()

    def disconnect(self):
        try:
            self.client.disconnect()
        except Exception:
            log_swallowed(logger, level=logging.DEBUG)

    def pump(self, n: int = 8, dt: float = 0.05):
        _pump(self.game, n, dt)

    def clear_messages(self):
        self.messages.clear()

    def any_message_contains(self, needle: str) -> bool:
        needle = needle.lower()
        return any(needle in m.lower() for m in self.messages)

    def client_flag(self, name: str):
        return self.game.gs1._shared["client"].get(name)

    def stage(self) -> float:
        """client.eq_stage as a number - unset reads as 0 (not started),
        mirroring the guarded strtofloat(#s(client.eq_stage)) idiom every
        staged NPC script uses."""
        raw = self.client_flag("eq_stage")
        if not raw:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    # -- simulated script delivery (see module docstring) -------------------

    def _deliver_scripts(self):
        """FALLBACK ONLY (see __init__): match every wire NPC on the CURRENT
        level to its script text on disk by position, inject it at the
        streamed-script seam, and let the real engine load + fire it
        (gs1_client_conformance.py's 'npc' channel pattern). A no-op unless
        inject_scripts is set - real delivery already puts non-empty script
        text on client.npcs[id]['script'], and _load_new_npcs() (called by
        _pump every frame) loads and fires it on its own; nothing here needs
        to duplicate that when the server is doing its job."""
        if not self.inject_scripts:
            return
        level = self.client._current_level_name
        defs = _level_npcs(level)
        if not defs:
            return
        delivered = False
        for npc_id, npc in self.client.npcs.items():
            if npc.get("script") or npc.get("_level") != level:
                continue
            nx, ny = npc.get("x", 0.0), npc.get("y", 0.0)
            match = min(
                defs, key=lambda d: (d["x"] - nx) ** 2 + (d["y"] - ny) ** 2,
                default=None)
            if match is not None and (match["x"] - nx) ** 2 + (match["y"] - ny) ** 2 < 0.01:
                npc["script"] = match["script"]
                delivered = True
        if delivered:
            self.pump(3)

    # -- coordinates ----------------------------------------------------

    def target_world(self, level_name: str, local_x: float,
                     local_y: float) -> Tuple[float, float]:
        cell = _GMAP_GRID.get(level_name)
        if cell is not None and self.client.in_gmap_segment:
            gx, gy = cell
            return local_to_world(local_x, local_y, gx, gy)
        return local_x, local_y

    # -- movement ---------------------------------------------------------

    def walk_to(self, target_x: float, target_y: float, timeout: float = 10.0,
               tolerance: float = 0.5) -> bool:
        start = time.time()
        start_level = self.client._current_level_name
        stuck = 0
        best_dist = None
        while time.time() - start < timeout:
            dx = target_x - self.client.x
            dy = target_y - self.client.y
            if abs(dx) < tolerance and abs(dy) < tolerance:
                return True
            mdx = 0 if abs(dx) < tolerance else (1 if dx > 0 else -1)
            mdy = 0 if abs(dy) < tolerance else (1 if dy > 0 else -1)
            self.game._move(mdx, mdy)
            self.pump(1, 0.05)
            if self.client._current_level_name != start_level:
                # A touched NPC warped us mid-walk (e.g. the PK totem's
                # setlevel2) - the target was meant for the OLD level's
                # frame and is now meaningless; stop instead of walking the
                # new level toward a stale coordinate (which can trip one of
                # ITS links and bounce us straight back out).
                return False
            # Stuck detection tracks NET progress toward the target, not raw
            # frame-to-frame position - a target sitting behind a blocking
            # NPC/wall can make the player rock back and forth between two
            # tiles (mdx flips sign as dx crosses the tolerance band each
            # step) with neither axis ever literally frozen, so comparing
            # position to the previous frame never trips. That let a walk
            # toward a target on the far side of a blocking sprite spin for
            # the full timeout without ever reaching the sidestep recovery
            # below (found live: the lever's cooldown re-touch, approaching
            # from a resting spot the first touch had left north of it).
            dist = (target_x - self.client.x) ** 2 + (target_y - self.client.y) ** 2
            if best_dist is None or dist < best_dist - 0.01:
                best_dist = dist
                stuck = 0
            else:
                stuck += 1
                if stuck > 12:
                    # Sidestep recovery (mirrors GameBot.walk_to): nudge the
                    # perpendicular axis toward the target a couple of steps.
                    if mdx != 0:
                        sy = 1 if dy >= 0 else -1
                        self.game._move(0, sy)
                        self.pump(1, 0.05)
                        self.game._move(0, sy)
                        self.pump(1, 0.05)
                    if mdy != 0:
                        sx = 1 if dx >= 0 else -1
                        self.game._move(sx, 0)
                        self.pump(1, 0.05)
                        self.game._move(sx, 0)
                        self.pump(1, 0.05)
                    stuck = 0
                    best_dist = None
        return False

    def approach(self, target_x: float, target_y: float, timeout: float = 10.0):
        """Walk toward a world position, then push a few extra steps into it
        - covers a blocking NPC/wall on the final tile (playertouchsme fires
        off the blocked-move touch dispatch too, not just a completed step;
        see actions.py's _move).

        Stops the push loop the instant the level changes (e.g. the NPC we
        just touched warped us, like the PK totem's setlevel2): the
        remaining pushes would otherwise run in the NEW level against the
        OLD (now meaningless) target, and could walk us straight onto one of
        ITS links and back out again before the caller ever sees the warp.
        """
        start_level = self.client._current_level_name
        self.walk_to(target_x, target_y, timeout=timeout, tolerance=0.4)
        if self.client._current_level_name != start_level:
            return
        for _ in range(8):
            dx = target_x - self.client.x
            dy = target_y - self.client.y
            mdx = 0 if abs(dx) < 0.1 else (1 if dx > 0 else -1)
            mdy = 0 if abs(dy) < 0.1 else (1 if dy > 0 else -1)
            if mdx == 0 and mdy == 0:
                break
            self.game._move(mdx, mdy)
            self.pump(1, 0.05)
            if self.client._current_level_name != start_level:
                return

    def warp(self, level_name: str, x: float, y: float, timeout: float = 8.0) -> bool:
        self.client.warp_to_level(level_name, x, y)
        deadline = time.time() + timeout
        while (time.time() < deadline
               and self.client._current_level_name != level_name):
            self.client.update(timeout=0.1)
        self.pump(10)
        self._deliver_scripts()
        return self.client._current_level_name == level_name

    def _find_npc(self, level_name: str, npc_x: float, npc_y: float) -> Optional[dict]:
        best, best_d = None, None
        for npc in self.client.npcs.values():
            if npc.get("_level") != level_name:
                continue
            d = (npc.get("x", 0.0) - npc_x) ** 2 + (npc.get("y", 0.0) - npc_y) ** 2
            if best_d is None or d < best_d:
                best, best_d = npc, d
        return best

    def touch(self, level_name: str, npc_x: float, npc_y: float,
             timeout: float = 14.0):
        """Approach and push into the NPC at (npc_x, npc_y) on the level
        we're CURRENTLY standing in - no warp. go_and_touch() calls this
        after its warp; it is also usable bare for an immediate re-touch
        FROM A POSITION ALREADY KNOWN TO HAVE A CLEAR APPROACH (double-pay
        checks where the NPC's touch box has open ground on every side).

        Do NOT bare-call this for an immediate re-touch right after a
        PREVIOUS touch left the player resting wherever that touch's push
        happened to stop - if the NPC has a blocked side (a wall on one
        edge, another prop crowding another), the resting spot can be on
        the wrong side of it, and walk_to() then spends its whole budget
        failing to close the last fraction of a tile through the block
        with no fresh touch ever firing (found live: the lever, which backs
        onto the town hall wall). go_and_touch() from a verified-reachable
        point is the reliable way to re-touch - its warp is effectively
        instant, unlike a real walk, so it does not cost the wall-clock
        time re-walking from scratch would.

        The touch/collision test is driven by the player's FEET point
        (top-left + PLAYER_STAND_X/Y), not the NPC's raw (x, y) anchor, and a
        character NPC's touch box is itself offset +(0.5, 1.0) from its
        anchor (npc_handler.py's CHARACTER_TOUCH_DX/DY) - aiming the
        player's top-left at npc_x/npc_y (or even at its centre) can land
        the feet point entirely outside the touch shape. Resolve the REAL
        rect via the engine (gs1.npc_image_rect, the same function
        check_touch's shapes come from) and aim the feet point at its
        centre instead of hand-duplicating that geometry.
        """
        npc = self._find_npc(level_name, npc_x, npc_y)
        rect = self.game.gs1.npc_image_rect(npc) if npc is not None else None
        if rect is not None:
            # npc_image_rect prefers world_x/world_y (see its docstring), so
            # this rect is ALREADY in the player's own coordinate frame -
            # target_world would double-convert it.
            rx, ry, rw, rh = rect
            feet_x, feet_y = rx + rw / 2.0, ry + rh / 2.0
            # Touch is decided by the two per-direction probe points
            # (npc_handler.TOUCH_OFFSETS), which straddle the feet point at
            # +/-0.45 tile, and an image NPC is only hit where its art is
            # opaque. Centring the FEET on a narrow sprite (the 14px egg)
            # puts both probes on its transparent edge and the push never
            # touches. Centre the left-hand probe on the sprite instead.
            tx = feet_x - PLAYER_STAND_X + TOUCH_PROBE_HALFSPAN
            ty = feet_y - PLAYER_STAND_Y
        else:
            # No resolvable shape (script not loaded yet, or a bare "-"
            # script-only NPC) - fall back to standing on its own anchor,
            # which IS level-local and needs the usual conversion.
            local_x = npc_x + 1.0 - PLAYER_STAND_X
            local_y = npc_y + 1.0 - PLAYER_STAND_Y
            tx, ty = self.target_world(level_name, local_x, local_y)
        self.approach(tx, ty, timeout=timeout)

    def go_and_touch(self, level_name: str, warp_x: float, warp_y: float,
                     npc_x: float, npc_y: float, timeout: float = 14.0):
        """Warp near (level_name, warp_x, warp_y) - a spot verified reachable
        from the NPC's own coordinate - then touch() the NPC at
        (npc_x, npc_y)."""
        self.warp(level_name, warp_x, warp_y)
        self.touch(level_name, npc_x, npc_y, timeout=timeout)


# ---------------------------------------------------------------------------
# Quest waypoints - (level, warp_x, warp_y, npc_x, npc_y), each warp point
# verified reachable (BFS over the live board, see the offline board_bfs
# scouting pass this rewrite was built from) from its NPC's own position.
#
# v2 town-hall/witness/ambient placements (chicken1.nw), west-then-down egg
# trail (chicken2.nw -> chicken3.nw -> chicken_cave_entrance.nw ->
# chicken_cave_1.nw's dead-end nest corridor), and Peep/Hen Penny.
# ---------------------------------------------------------------------------
_MAYOR = ("chicken1.nw", 16, 30, 13, 27)
_SHELLY = ("chicken1.nw", 22, 35, 19, 38)
_LEVER = ("chicken1.nw", 20, 29, 17, 27)
# Bud and Benedict left the town square on 2026-08-07: the ambient cast now
# spreads across the gmap (Bud gossips by the chicken7 farm fence, Benedict
# watches the chicken5 bridge). Their stage-3 reaction lines are unchanged,
# so the post-quest sweep just travels further.
_BUD = ("chicken7.nw", 36, 21, 34, 19)
_CLUCK_NORRIS = ("chicken1.nw", 16, 41, 14, 42)
_BENEDICT = ("chicken5.nw", 28, 44, 30, 43)
# Eggs and Peep are narrow sprites touched through the two per-direction
# probe points (see QuestSession.touch), so their warp points sit directly
# above the sprite on its centre column (x = sprite centre - 0.6) and the
# walk is a straight push down. A diagonal final approach faces left/right
# and never probes the sprite, and a warp point already flush against it
# starts past the probe's reach. Egg 1's nook (x 44-46, y 26-27) opens only
# to the south, so its warp point is two tiles up, in the wall's shadow.
_EGG1 = ("chicken2.nw", 43.4, 24, 44, 28)
_EGG2 = ("chicken3.nw", 34, 5, 34, 3)
_EGG3 = ("chicken_cave_entrance.nw", 29, 22, 26, 22)
_EGG4 = ("chicken_cave_1.nw", 33.4, 35, 34, 39)
_PEEP = ("chicken_cave_1.nw", 33.4, 36, 34, 41)
_HENPENNY = ("chicken_cave_entrance.nw", 32, 12, 34, 10)
# Last Call. The drinker's script moves him to (34.5, 15.5) and seats him at
# the banquet table, so he is touched from the open floor to his north. The
# beer shop is an invisible NPC on the inn patio that answers the chat "beer"
# anywhere on chicken1; _BAR is just a spot on that patio.
_DRINKER = ("chicken_cave_entrance.nw", 33.9, 12, 34.5, 15.5)
_GATE_GUARD_POS = (30.0, 6.0)
_BAR = ("chicken1.nw", 47, 44)


def _gate_guard(s) -> Optional[dict]:
    """The gate guard if he is still at his post. _find_npc returns the
    NEAREST NPC at any distance, so once he has gone it would hand back Hen
    Penny instead; only an NPC on the post itself counts."""
    gx, gy = _GATE_GUARD_POS
    for npc in s.client.npcs.values():
        if (npc.get("_level") == "chicken_cave_entrance.nw"
                and abs(npc.get("x", -99.0) - gx) < 1.5
                and abs(npc.get("y", -99.0) - gy) < 1.5):
            return npc
    return None

_EGGS = (
    ("egg1_chicken2_west", _EGG1, "eggq_1", "warm. suspiciously warm"),
    ("egg2_chicken3_southwest", _EGG2, "eggq_2", "licking these"),
    ("egg3_cave_entrance", _EGG3, "eggq_3", "darker in here"),
    ("egg4_cave_nest", _EGG4, "eggq_4", "sitting on a chick"),
)

_RESULTS: List[Tuple[str, bool, str]] = []


def _report(name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" - {detail}" if detail else ""))
    return ok


def run() -> bool:
    reset_ok = reset_quest_account()
    if not reset_ok:
        print("[WARN] could not reset the quest account fixture "
              "(GSERVER_ACCOUNTS_DIR unset or account file missing) - "
              "a prior run's flags may make later steps look like failures")

    s = QuestSession()

    # a. Stage 0: Mayor's hook. Touching him sets eq_stage=1 and the dialogue
    #    is the "thief" hook line, not the stage-1 follow-up.
    s.clear_messages()
    s.go_and_touch(*_MAYOR)
    _report("a_mayor_hook_sets_stage1",
            s.stage() == 1 and s.any_message_contains("golden eggs"),
            f"stage={s.stage()}; messages={s.messages}")

    # b. Stage 1: touching the Mayor again gives the DIFFERENT "already
    #    hooked" line, not the stage-0 hook repeated - proves the mayor's
    #    before/after-witness dialogue actually differs on stage, not just
    #    on a single "already talked to him" flag.
    s.clear_messages()
    s.go_and_touch(*_MAYOR)
    _report("b_mayor_stage1_dialogue_differs_from_hook",
            s.stage() == 1 and s.any_message_contains("impossible to miss")
            and not s.any_message_contains("golden eggs, gone"),
            f"stage={s.stage()}; messages={s.messages}")

    # c. Eggs are inert at stage 1 (below the stage>=2 gate): touching one
    #    sets no flag and prints no pickup line. This is the "eggs
    #    inert/hidden below stage 2" requirement - checked BEFORE Shelly
    #    raises the stage, so a flag slipping through here is a real bug.
    #    Bud/Cluck Norris/Benedict's ambient timeout chatter can freely
    #    interleave during the walk over (that noise is real and expected,
    #    see the module docstring's cadence note), so the assertion checks
    #    for the ABSENCE of the egg's own pickup line specifically, not an
    #    empty message list.
    s.clear_messages()
    s.go_and_touch(*_EGG1)
    _report("c_egg1_inert_before_stage2",
            s.client_flag("eggq_1") is None
            and not s.any_message_contains("suspiciously warm"),
            f"eggq_1={s.client_flag('eggq_1')!r}; messages={s.messages}")

    # d. Shelly (the witness): stage 0/unset gives the ambient "someone
    #    should ask him why" line; at stage 1 she raises the stage to 2 and
    #    gives the trail. Touch her BEFORE the mayor hook too, to pin the
    #    stage-0 line (order matters: this must run first, but the mayor
    #    step above already advanced the account to stage 1 - so this
    #    confirms the stage-1 trail line instead, and the earlier egg-inert
    #    check already exercised the pre-stage1 gate).
    s.clear_messages()
    s.go_and_touch(*_SHELLY)
    _report("d_shelly_advances_to_stage2",
            s.stage() == 2 and s.any_message_contains("west")
            and s.any_message_contains("caves"),
            f"stage={s.stage()}; messages={s.messages}")

    # e. Eggs now unlocked (stage 2): collect all four, west then down into
    #    the caves, in trail order. Each sets its own eggq_N flag, hides,
    #    and prints its own line.
    for name, quest, flag, needle in _EGGS:
        s.clear_messages()
        s.go_and_touch(*quest)
        flag_val = s.client_flag(flag)
        _report(f"e_{name}_collected",
                bool(flag_val) and s.any_message_contains(needle),
                f"{flag}={flag_val!r}; messages={s.messages}")

    # f. Peep (nest corner, cave_1): flag set, hides. Then Hen Penny at the
    #    cave entrance: heal + 50 rupees, once only.
    s.clear_messages()
    s.go_and_touch(*_PEEP)
    _report("f_peep_found_flag_set", bool(s.client_flag("peep_found")),
            f"peep_found={s.client_flag('peep_found')!r}")

    s.client.player.hearts = max(0.5, s.client.player.hearts - 1.0)
    rupees_before4 = s.client.player.rupees
    s.clear_messages()
    s.go_and_touch(*_HENPENNY)
    rupees_after4 = s.client.player.rupees
    _report("f_henpenny_heal_and_reward",
            rupees_after4 - rupees_before4 == 50
            and s.client.player.hearts == s.client.player.max_hearts,
            f"rupees {rupees_before4} -> {rupees_after4}; "
            f"hearts={s.client.player.hearts}/{s.client.player.max_hearts}")
    s.clear_messages()
    rupees_before5 = s.client.player.rupees
    s.go_and_touch(*_HENPENNY)
    rupees_after5 = s.client.player.rupees
    _report("f_henpenny_no_double_pay", rupees_after5 == rupees_before5,
            f"rupees {rupees_before5} -> {rupees_after5}; "
            f"messages={s.messages}")

    # g. Return to the Mayor with all 4 eggs: the payoff pays exactly once
    #    (+100 rupees, full heal) and advances eq_stage to 3; touching again
    #    does NOT pay again and gives the stage-3 line instead.
    s.client.player.hearts = max(0.5, s.client.player.hearts - 1.0)
    rupees_before = s.client.player.rupees
    s.clear_messages()
    s.go_and_touch(*_MAYOR)
    rupees_after = s.client.player.rupees
    _report("g_mayor_payoff_pays_once_and_sets_stage3",
            rupees_after - rupees_before == 100 and s.stage() == 3
            and s.client.player.hearts == s.client.player.max_hearts,
            f"rupees {rupees_before} -> {rupees_after}; stage={s.stage()}")
    s.clear_messages()
    rupees_before2 = s.client.player.rupees
    s.go_and_touch(*_MAYOR)
    rupees_after2 = s.client.player.rupees
    _report("g_mayor_no_double_pay_stage3_line",
            rupees_after2 == rupees_before2
            and s.any_message_contains("statues"),
            f"rupees {rupees_before2} -> {rupees_after2}; "
            f"messages={s.messages}")

    # h. Stage 3: the town reacts. Bud/Cluck Norris/Benedict all switch to
    #    their post-quest touch line now that eq_stage == 3.
    for name, quest, needle in (
        ("bud", _BUD, "cracked the egg case"),
        ("cluck_norris", _CLUCK_NORRIS, "featherless biped"),
        ("benedict", _BENEDICT, "terrifying"),
    ):
        s.clear_messages()
        s.go_and_touch(*quest)
        _report(f"h_{name}_post_quest_line", s.any_message_contains(needle),
                f"messages={s.messages}")

    # i. Relog persistence: eq_stage survives, eggs stay hidden/inert, the
    #    Mayor still refuses to re-pay, and the ambient stage-3 lines are
    #    still switched. THE exploit-regression check for the client.-scope
    #    persistence fix this suite has pinned since v1.
    s.reconnect()
    _report("i_relog_stage_persisted", s.stage() == 3, f"stage={s.stage()}")
    rupees_before3 = s.client.player.rupees
    s.clear_messages()
    s.go_and_touch(*_MAYOR)
    rupees_after3 = s.client.player.rupees
    _report("i_relog_mayor_still_refuses_to_repay",
            rupees_after3 == rupees_before3,
            f"rupees {rupees_before3} -> {rupees_after3}; "
            f"messages={s.messages}")
    egg_still_hidden = []
    for name, quest, flag, _needle in _EGGS:
        rupees_b = s.client.player.rupees
        s.clear_messages()
        s.go_and_touch(*quest)
        egg_still_hidden.append((name, s.client_flag(flag) is not None
                                  and s.client.player.rupees == rupees_b))
    _report("i_relog_eggs_stay_hidden",
            all(ok for _, ok in egg_still_hidden), f"{egg_still_hidden}")
    s.clear_messages()
    s.go_and_touch(*_BUD)
    _report("i_relog_ambient_still_post_quest",
            s.any_message_contains("cracked the egg case"),
            f"messages={s.messages}")

    # j. Party lever (moved to the town hall side wall, same payout/cooldown
    #    script): pays out (lays 3 greenrupee ground items - `lay` drops an
    #    item, it does not credit the player directly, so the payout signal
    #    here is the persisted cooldown stamp + dialogue), then within
    #    cooldown a second pull does NOT pay; lap through a level link and
    #    back and confirm it STILL doesn't pay.
    s.clear_messages()
    s.go_and_touch(*_LEVER)
    stamp_after_first = s.client_flag("lever_last")
    _report("j_lever_first_pull_pays",
            bool(stamp_after_first) and s.any_message_contains("EVERYTHING"),
            f"lever_last={stamp_after_first!r}; messages={s.messages}")
    s.clear_messages()
    # A bare re-touch from wherever the FIRST pull left the player can start
    # already pressed against the lever's own blocking hitbox from the wrong
    # side (its north tile is a wall, so the only open approach is from the
    # south/east) - walk_to() then spends its whole budget trying to close
    # the last fraction of a tile through a block that a bare re-touch never
    # backs away from first, and no touch fires at all. go_and_touch's warp
    # is effectively instant (unlike a real walk), so re-using the SAME
    # verified-reachable approach point the first pull used is both fast and
    # reliable - found live positioning the v2 lever against the town hall
    # wall, where v1's mid-town position never took a wall on one side.
    s.go_and_touch(*_LEVER)
    stamp_after_second = s.client_flag("lever_last")
    _report("j_lever_cooldown_blocks_second_pull",
            stamp_after_second == stamp_after_first
            and s.any_message_contains("remembers"),
            f"lever_last={stamp_after_second!r}; messages={s.messages}")
    # Lap through a level link (house) and back. The regression this guards
    # against: `this.cooling`-style state living in `this.` scope, which
    # ClientGS1.clear() wipes on every level transition, so lapping through
    # ANY door would re-arm the payout instantly. The hard assertion is that
    # the stamp SURVIVES the transition (client. scope, not this.) - not
    # "still within the cooldown window", which two real live warps can
    # themselves burn through and would make this assertion a coin flip on a
    # loaded machine or slow network.
    s.warp("chicken_house1.nw", 30, 30)
    s.warp("chicken1.nw", 30, 36)
    stamp_survived_lap = s.client_flag("lever_last")
    _report("j_lever_flag_survives_level_lap",
            stamp_survived_lap == stamp_after_second,
            f"lever_last={stamp_survived_lap!r} (was {stamp_after_second!r} "
            f"before the lap)")

    # k. Last Call: five beers from the inn put the off-duty guard under,
    #    the gate guard leaves, the drinker pays out once, and all of it
    #    survives a relog. Each beer is bought and delivered separately: the
    #    carried Beer weapon must destroy itself on delivery, or one purchase
    #    could be counted five times.
    s.clear_messages()
    s.go_and_touch(*_DRINKER)
    _report("k_last_call_hook_sets_started",
            bool(s.client_flag("lc_started")),
            f"lc_started={s.client_flag('lc_started')!r}; messages={s.messages}")
    rupees_start = s.client.player.rupees
    _report("k_last_call_can_afford", rupees_start >= 25,
            f"rupees={rupees_start} (five beers cost 25; earlier steps pay)")
    beer_ok = True
    detail = []
    for n in range(1, 6):
        s.warp(*_BAR)
        s.client.send_level_chat("beer")  # CURCHAT: what playerchats sees
        s.pump(30)
        bought = "Beer" in s.client.weapons
        s.go_and_touch(*_DRINKER)
        s.pump(20)
        count = s.client_flag("lc_beers")
        consumed = "Beer" not in s.client.weapons
        detail.append(f"beer{n}: bought={bought} count={count!r} "
                      f"consumed={consumed}")
        if n == 1:
            # Same beer, second touch: nothing left to hand over.
            s.go_and_touch(*_DRINKER)
            s.pump(10)
            _report("k_last_call_one_beer_counts_once",
                    s.client_flag("lc_beers") == count,
                    f"lc_beers={s.client_flag('lc_beers')!r} after re-touch "
                    f"(was {count!r})")
        if not (bought and consumed and str(count) in (str(n), f"{n}.0")):
            beer_ok = False
            break
    _report("k_last_call_five_deliveries", beer_ok, "; ".join(detail))
    rupees_end = s.client.player.rupees
    _report("k_last_call_done_and_paid",
            bool(s.client_flag("lc_done")) and rupees_end == rupees_start - 25 + 40,
            f"lc_done={s.client_flag('lc_done')!r}; rupees "
            f"{rupees_start} -> {rupees_end} (want -25 +40)")
    s.pump(200)  # let the gate guard's walk-off cutscene play out
    s.warp("chicken4.nw", 30, 40)
    s.warp("chicken_cave_entrance.nw", 30, 20)
    gate = _gate_guard(s)
    gate_gone = gate is None or gate.get("visible") is False
    _report("k_last_call_gate_guard_stays_gone", gate_gone,
            f"gate npc={None if gate is None else (gate.get('x'), gate.get('y'), gate.get('visible'))}")
    s.reconnect()
    s.warp("chicken_cave_entrance.nw", 30, 20)
    gate = _gate_guard(s)
    rupees_relog = s.client.player.rupees
    s.clear_messages()
    s.go_and_touch(*_DRINKER)
    _report("k_last_call_relog_persists_no_repay",
            bool(s.client_flag("lc_done"))
            and (gate is None or gate.get("visible") is False)
            and s.client.player.rupees == rupees_relog,
            f"lc_done={s.client_flag('lc_done')!r}; gate_visible="
            f"{None if gate is None else gate.get('visible')}; rupees "
            f"{rupees_relog} -> {s.client.player.rupees}; messages={s.messages}")

    s.disconnect()

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"\n{'=' * 60}\n  CHICKEN QUESTS: {passed}/{total} passed\n{'=' * 60}")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
