"""Live behavioural fingerprints: catch scripts that silently take the wrong branch.

WHY THIS EXISTS
---------------
Every other suite answers "did anything crash / warn / mis-parse?".  A script
that silently takes the wrong branch does none of those things -- see
tests/test_behaviour_fingerprint_live.py for the outage that proved it.  A
branch flip is only observable in the SHAPE of what the content built, so
this module logs in like a real client and fingerprints that shape against a
checked-in baseline.

DESIGN RULES
------------
1. Structure, never pixels or exact strings.  Counts get *bands*, sets get
   subset/disjoint checks.  Server content churns. A branch flip does not
   look like churn (Login went 9 GUI roots -> 4, 90 named controls -> 3,
   3 weapon VMs -> 6 as it fell through to the legacy `-Serverlist` path).
2. Every band is derived from the baseline value plus a per-metric tolerance
   (see METRIC_BANDS).  The tolerances are judgement calls, not measurements.
   they are all in one table so re-tuning is a one-line edit.
3. A failure must name the invariant, the value now, and the value in the
   baseline -- "gui_named 3 outside band 67..115 (baseline 90)" is a bug
   report. "assertion failed" is not.
4. Re-baselining is deliberate and explicit (`--rebaseline`), never automatic,
   so a real content change shows up as a diff someone chose to accept.
5. Remote servers are PASSIVE: connect, watch, disconnect.  No chat, no
   movement, no combat, no writes, one connection per run.

Usage:
    python -m game_tester --behaviour                    # check every baseline
    python -m game_tester --behaviour --behaviour-server Login
    python -m game_tester --behaviour --rebaseline       # rewrite baselines
    python -m game_tester --behaviour --behaviour-server "local gs2emu" \
        --host localhost --port 14900 --rebaseline       # bootstrap a new one
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

BASELINE_PATH = Path(__file__).with_name("behaviour_baselines.json")
SCHEMA_VERSION = 1

#: Fixed simulation step.  Frames are paced to real time at this rate so the
#: amount of *script* time a fingerprint covers is the same on a fast and a
#: slow machine (host-call counts are driven by settimer/sleep, i.e. by script
#: time, so an unpaced loop would make them machine-dependent).
FRAME_DT = 1.0 / 60.0

#: Default observation window.  25s is what the ad-hoc Login diagnostic used:
#: long enough for the client-install weapon fetch (PLI_UPDATESCRIPT round
#: trips) plus the GUI build to finish, short enough to sweep several servers.
DEFAULT_SECONDS = 25.0

#: Seconds to wait between two remote connections in a multi-server run.
#: Politeness, not correctness -- these are other people's servers.
REMOTE_SPACING = 3.0

#: Loggers whose WARNING+ records count as engine noise for the fingerprint.
_WATCHED_LOGGERS = ("pyreborn", "reborn_protocol", "game_tester")

#: Warnings starting with this are server-content facts, not engine noise --
#: see _LogCapture.emit and the assets_refused invariant.
_REFUSAL_PREFIX = "Server refused file"


@dataclass
class Target:
    """A server to fingerprint.  `passive` servers are never written to."""
    name: str
    host: str
    port: int
    version: str = "6.037"
    seconds: float = DEFAULT_SECONDS
    passive: bool = True
    #: Public GS2 functions to invoke once the observation window closes, as
    #: "<weapon vm key>:<function>" -- the menu entries a user would click.
    #: A server's most complicated UI usually only exists after someone opens
    #: it: Login builds the whole Global Chat window (frame set, channel
    #: list, chat pane, smilie bar) in `-Serverlist_Chat.openChat()`, which
    #: nothing on the login path calls, so it was invisible to the harness --
    #: including a frame set that laid none of its cells out.  These MUST be
    #: local-only openers; see `_open_ui` for the etiquette rule.
    open_ui: Tuple[str, ...] = ()


#: Bootstrap addresses so `--rebaseline` can create an entry by name.  Once a
#: baseline exists its own recorded address wins (servers move).  The two
#: local gs2emu instances are ours and may be hammered; everything else is
#: someone else's box and is observed passively.
_LOGIN_UI = ("-serverlist_chat:openchat",)

DEFAULT_TARGETS: Dict[str, Target] = {
    "Login": Target("Login", "loginserver.graal.in", 14911, open_ui=_LOGIN_UI),
    "Login DEV": Target("Login DEV", "loginserver.graal.in", 14914,
                        open_ui=_LOGIN_UI),
    # Login Mobile runs a different weapon set (-mobile/serverlist,
    # -loginscreen) with no -Serverlist_Chat and no GUI roots at all, so it
    # has nothing to open.
    "Login Mobile": Target("Login Mobile", "loginserver.graal.in", 14912),
    "Zelda: A Link to the Past": Target(
        "Zelda: A Link to the Past", "hastur.eevul.net", 14912),
    "local gs2emu": Target("local gs2emu", "localhost", 14900,
                           seconds=15.0, passive=False),
    "local gs2emu 2006": Target("local gs2emu 2006", "127.0.0.1", 14901,
                                seconds=15.0, passive=False),
}


class _LogCapture(logging.Handler):
    """Count WARNING+ records from the engine, keyed by format template.

    The template (`record.msg` before % formatting) is the stable identity of
    a warning: "GS2 %s: unknown method %s()" stays constant while its
    arguments vary per script.  That makes "did a NEW kind of warning appear?"
    a usable invariant without pinning script names.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.kinds: Dict[str, int] = {}
        self.warnings = 0
        self.errors = 0
        self.samples: Dict[str, str] = {}
        self.refused: Dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(_WATCHED_LOGGERS):
            return
        if str(record.msg).startswith(_REFUSAL_PREFIX):
            # A refused file is a fact about the SERVER's content, not about
            # our engine: the login serverlist asks for a per-server icon that
            # most servers never published, and Zelda's scripts name art it
            # does not ship. Counting those as engine warnings made
            # no_new_warnings permanently red on four servers for something no
            # client change can fix, so they get their own banded metric
            # (assets_refused) and stay out of the strict template set.
            try:
                name = str(record.args[0]) if record.args else "?"
            except Exception:
                name = "?"
            self.refused[name] = self.refused.get(name, 0) + 1
            return
        key = f"{record.name}|{record.levelname}|{str(record.msg)[:160]}"
        self.kinds[key] = self.kinds.get(key, 0) + 1
        if record.levelno >= logging.ERROR:
            self.errors += 1
        else:
            self.warnings += 1
        if key not in self.samples:
            try:
                self.samples[key] = record.getMessage()[:300]
            except Exception:
                self.samples[key] = str(record.msg)[:300]


def _control_name(ctrl: Any) -> str:
    return str(getattr(ctrl, "ctrl_name", "") or getattr(ctrl, "name", "") or "")


#: How far a child may stick out of its parent before it counts as overflow.
#: Not zero: several Login panels are deliberately placed at y = -22 to draw
#: under their window's title bar (Serverlist_DescriptionPanel/TablesPanel,
#: weapon-Rescripted_Serverlist.txt:2016 and :2047), and scroll bars sit a
#: pixel or two proud of their frames.
OVERFLOW_SLOP = 24


def _is_scroll(ctrl: Any) -> bool:
    try:
        from pyreborn.game.gs2_gui import GuiScrollCtrl
    except Exception:
        return False
    return isinstance(ctrl, GuiScrollCtrl)


def _content_size(ctrl: Any) -> int:
    """How much CONTENT this control holds: tree nodes, list rows, or text.

    This is the axis the structural metrics are blind to.  A control-counting
    fingerprint cannot tell a populated server list from an empty one -- the
    tree control exists either way -- which is exactly how a 25/25 pass was
    recorded over a Login screen with no servers in it.
    """
    total = 0
    nodes = getattr(ctrl, "root_nodes", None)
    if nodes is not None:
        flat = getattr(ctrl, "flat_nodes", None)
        total += len(flat()) if callable(flat) else len(nodes)
    rows = getattr(ctrl, "list_rows", None)
    if rows:
        total += len(rows)
    try:
        text = ctrl.get("text")
    except Exception:
        text = None
    if isinstance(text, str) and text.strip():
        total += 1
    return total


def _walk_gui(gui: Any) -> Dict[str, Any]:
    """Structural summary of the GS2 GUI control tree."""
    roots = list(getattr(gui, "roots", []) or [])
    classes: Dict[str, int] = {}
    root_classes: Dict[str, int] = {}
    named: List[str] = []
    total = 0
    max_depth = 0
    tree_nodes = 0
    list_rows = 0
    text_controls = 0
    filled: List[str] = []
    overflowing: List[str] = []
    degenerate: List[str] = []

    def visit(ctrl: Any, depth: int, parent: Any, shown: bool) -> None:
        nonlocal total, max_depth, tree_nodes, list_rows, text_controls
        total += 1
        max_depth = max(max_depth, depth)
        classes[type(ctrl).__name__] = classes.get(type(ctrl).__name__, 0) + 1
        name = _control_name(ctrl)
        if name:
            named.append(name.lower())
        # Only a control the script NAMED is stable enough to key an
        # invariant on: anonymous ones fall back to their class name, so
        # several unrelated controls share one key and the set churns.
        script_name = str(getattr(ctrl, "ctrl_name", "") or "").lower()
        shown = shown and bool(getattr(ctrl, "visible", False))

        nodes = getattr(ctrl, "root_nodes", None)
        if nodes is not None:
            flat = getattr(ctrl, "flat_nodes", None)
            tree_nodes += len(flat()) if callable(flat) else len(nodes)
        rows = getattr(ctrl, "list_rows", None)
        if rows:
            list_rows += len(rows)
        try:
            text = ctrl.get("text")
        except Exception:
            text = None
        if isinstance(text, str) and text.strip():
            text_controls += 1
        if script_name and _content_size(ctrl):
            filled.append(script_name)

        # -- geometry ---------------------------------------------------
        # Only controls that are ACTUALLY on screen (own visibility AND
        # every ancestor's): a hidden pane is allowed to be any shape, and
        # several Login panels are built off-screen and moved on show.
        if shown and script_name:
            try:
                rect = ctrl.rect()
            except Exception:
                rect = None
            if rect is not None:
                if rect.width <= 0 or rect.height <= 0:
                    degenerate.append(script_name)
                # A scroll control's whole job is to host content BIGGER than
                # itself, so its children are exempt (Global Chat's channel
                # list is declared 220 wide inside a 150-wide scroll).
                if parent is not None and not _is_scroll(parent):
                    try:
                        pr = parent.rect()
                    except Exception:
                        pr = None
                    if pr is not None and pr.width > 0 and pr.height > 0 and (
                            rect.left < pr.left - OVERFLOW_SLOP
                            or rect.top < pr.top - OVERFLOW_SLOP
                            or rect.right > pr.right + OVERFLOW_SLOP
                            or rect.bottom > pr.bottom + OVERFLOW_SLOP):
                        overflowing.append(script_name)

        # Depth guard: a malformed tree must not hang the harness.
        if depth < 32:
            for child in list(getattr(ctrl, "children", []) or []):
                visit(child, depth + 1, ctrl, shown)

    for root in roots:
        name = type(root).__name__
        root_classes[name] = root_classes.get(name, 0) + 1
        visit(root, 0, None, True)

    return {
        "roots": len(roots),
        "controls": total,
        # `_named` is the manager's registry, which also holds profiles and
        # destroyed-but-referenced controls, so it is counted separately from
        # the names actually reachable in the tree.
        "named": len(getattr(gui, "_named", {}) or {}),
        "max_depth": max_depth,
        "root_names": sorted({n for n in (_control_name(r).lower() for r in roots) if n}),
        "root_classes": dict(sorted(root_classes.items())),
        "classes": dict(sorted(classes.items())),
        "tree_names": sorted(set(named)),
        # -- content (see _content_size) ---------------------------------
        "tree_nodes": tree_nodes,
        "list_rows": list_rows,
        "text_controls": text_controls,
        "filled_controls": sorted(set(filled)),
        # -- geometry ----------------------------------------------------
        "overflowing": sorted(set(overflowing)),
        "degenerate": sorted(set(degenerate)),
        "window_overlaps": sorted(_window_overlaps(roots)),
    }


def snapshot_gui(gui: Any) -> Dict[str, Any]:
    """Public structural GUI snapshot shared with exploration tools."""
    return _walk_gui(gui)


def snapshot_vms(gs2: Any) -> Dict[str, Any]:
    return {
        "weapon": sorted(str(k).lower() for k in gs2.vms.get("weapon", {})),
        "class": sorted(str(k).lower() for k in gs2.vms.get("class", {})),
        "npc_count": len(gs2.vms.get("npc", {})),
        "gani_count": len(gs2.vms.get("gani", {})),
    }


def snapshot_bytecodes(client: Any) -> Dict[str, int]:
    return {kind: len(blobs) for kind, blobs
            in (getattr(client, "gs2_bytecode", {}) or {}).items()}


def snapshot_host_counters() -> Dict[str, Dict[str, int]]:
    from reborn_protocol.gs2.vm import GS2VM
    return {"called": dict(GS2VM.builtins_called),
            "missing": dict(GS2VM.builtins_missing)}


def snapshot_logs(log_capture: Any) -> Dict[str, Any]:
    if log_capture is None:
        return {"warnings": 0, "errors": 0, "kinds": {}, "samples": {},
                "refused": {}}
    return {"warnings": log_capture.warnings, "errors": log_capture.errors,
            "kinds": dict(log_capture.kinds),
            "samples": dict(log_capture.samples),
            "refused": dict(log_capture.refused)}


def delta_counters(before: Any, after: Any) -> Any:
    """Positive mapping deltas, or newly-added members for sequence snapshots."""
    if isinstance(before, dict) and isinstance(after, dict):
        return {key: value - before.get(key, 0) for key, value in after.items()
                if isinstance(value, (int, float))
                and value - before.get(key, 0) > 0}
    if isinstance(before, (list, tuple, set)) and isinstance(after, (list, tuple, set)):
        return sorted(set(after) - set(before))
    return after if after != before else []


def _visible_windows(roots: Iterable[Any]) -> List[Tuple[str, Any]]:
    """Every VISIBLE GuiWindowCtrl, with the visibility of its ancestors
    taken into account (an invisible parent hides the whole subtree)."""
    try:
        from pyreborn.game.gs2_gui import GuiWindowCtrl
    except Exception:
        return []
    out: List[Tuple[str, Any]] = []
    for root in roots:
        stack = [(root, True)]
        while stack:
            ctrl, shown = stack.pop()
            shown = shown and bool(getattr(ctrl, "visible", False))
            if shown and isinstance(ctrl, GuiWindowCtrl):
                try:
                    out.append((_control_name(ctrl).lower()
                                or type(ctrl).__name__, ctrl.rect()))
                except Exception:
                    pass
            for child in list(getattr(ctrl, "children", []) or []):
                stack.append((child, shown))
    return out


def _window_overlaps(roots: Iterable[Any]) -> List[str]:
    """Pairs of visible windows whose rects intersect.

    Login's serverlist is a TILED layout -- `Serverlist_Window` on the left,
    `Serverlist_DescriptionWindow` and `Serverlist_TablesWindow` stacked to
    its right, all sized off the same client extent -- so any intersection
    between them means a layout arithmetic bug. Pairs are reported as sorted
    "a|b" strings so the baseline can carry known-good ones (a floating
    window a script deliberately opens on top of the layout).
    """
    windows = _visible_windows(roots)
    pairs = []
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            (na, ra), (nb, rb) = windows[i], windows[j]
            if ra.width > 0 and ra.height > 0 and ra.colliderect(rb):
                pairs.append("|".join(sorted((na, nb))))
    return pairs


def _vm_kind_key(gs2: Any, vm: Any) -> str:
    for kind, table in gs2.vms.items():
        for key, other in table.items():
            if other is vm:
                return f"{kind}:{key}"
    return f"?:{getattr(vm, 'name', '?')}"


@dataclass
class _Recorder:
    """Instance-level hooks on the live runtime (never patches the classes)."""
    events: Dict[str, int] = field(default_factory=dict)
    event_calls: int = 0

    def install(self, gs2: Any) -> Callable[[], None]:
        original = gs2._run

        def recording_run(vm, event, *args):
            try:
                key = f"{_vm_kind_key(gs2, vm)}.{str(event).lower()}"
                self.events[key] = self.events.get(key, 0) + 1
                self.event_calls += 1
            except Exception:
                pass
            return original(vm, event, *args)

        # Instance attribute shadows the bound method, so `self._run(...)`
        # inside ClientGS2 goes through us without touching ClientGS2 itself.
        gs2._run = recording_run
        return lambda: gs2.__dict__.pop("_run", None)


def _event_views(events: Dict[str, int]) -> Dict[str, Any]:
    """Two stable views of the events that fired.

    Per-VM keys are only stable for weapons and classes (NPC VMs are keyed by
    server-assigned ids that move whenever level content is edited), so NPC
    events are aggregated to `npc.<event>`.
    """
    weapon_events = set()
    kinds = set()
    for key in events:
        kind, _, rest = key.partition(":")
        event = rest.rpartition(".")[2]
        kinds.add(f"{kind}.{event}")
        if kind in ("weapon", "class"):
            weapon_events.add(key)
    return {
        "calls": sum(events.values()),
        "distinct": len(events),
        "kinds": sorted(kinds),
        "weapon_events": sorted(weapon_events),
    }


def _replay_existing_bytecode(gs2: Any, client: Any) -> int:
    """Load GS2 bytecode that arrived before the runtime was attached.

    `ClientGS2.attach()` installs `client.on_gs2_bytecode`, so anything the
    server pushed earlier only exists in `client.gs2_bytecode` and never
    reaches a VM.  A freshly logged-in client barely notices (the login burst
    is small and the interesting weapons are fetched later, on demand), but a
    connection that has been alive for a while -- e.g. one the catalog sweep
    already ran scenarios on -- has ALL of its weapons in that dict and would
    otherwise fingerprint as a server that runs no scripts at all.

    Classes first so a weapon's join resolves immediately.
    """
    loaded = 0
    stored = getattr(client, "gs2_bytecode", {}) or {}
    for kind in ("class", "weapon", "npc", "gani"):
        for key, blob in list(stored.get(kind, {}).items()):
            norm = key.lower() if isinstance(key, str) else key
            if norm in gs2.vms.get(kind, {}):
                continue
            try:
                if gs2.load_bytecode(kind, key, blob) is not None:
                    loaded += 1
            except Exception:
                # load_bytecode already logs; a bad blob must not abort the
                # capture (the log capture will have counted it).
                pass
    return loaded


def _open_ui(game: Any, specs: Iterable[str]) -> Dict[str, str]:
    """Invoke each "<weapon>:<function>" opener and report what happened.

    ETIQUETTE: only ever list functions that build UI locally.  Login's
    `openChat` calls addChatWindowControls + addPlayersToChatters + showtop,
    all client-side (Preagonal/gbf/bytecode/login/_Serverlist_Chat.gs2bc.gs2:
    533-538) -- the IRC session it displays was already established by the
    login path, so opening the window originates no traffic.  A function that
    sends is a live action on someone else's server and does not belong here.
    """
    outcome: Dict[str, str] = {}
    for spec in specs:
        weapon, _, function = str(spec).partition(":")
        vm = game.gs2.vms.get("weapon", {}).get(weapon.lower())
        if vm is None:
            outcome[spec] = "no such weapon vm"
            continue
        try:
            vm.call(function.lower())
            outcome[spec] = "ok"
        except Exception as exc:                    # noqa: BLE001
            # An opener that throws is itself a finding, but it must not
            # abort the capture -- the rest of the fingerprint is still good.
            outcome[spec] = f"raised {type(exc).__name__}: {exc}"[:160]
    return outcome


def capture_from_client(client: Any, seconds: float = DEFAULT_SECONDS,
                        verbose: bool = False,
                        replay_bytecode: bool = False,
                        open_ui: Iterable[str] = ()) -> Dict[str, Any]:
    """Fingerprint an already-logged-in `Client` by running a real GameClient.

    The pump mirrors GameClient.run()'s body minus `_handle_events` /
    `_handle_input` (which need a real window and keyboard), exactly like
    render_smoke.py's `_pump`.  Nothing here sends gameplay input. The only
    traffic we originate is what the client's own scripts ask for (weapon
    fetches, serverlist requests) -- i.e. what a real player's client sends
    just by sitting at the login screen.
    """
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from pyreborn.pygame_game import GameClient

    capture = _LogCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(capture)

    host_before = snapshot_host_counters()

    game = GameClient(client)
    recorder = _Recorder()
    uninstall = recorder.install(game.gs2)
    replayed = 0
    try:
        if replay_bytecode:
            replayed = _replay_existing_bytecode(game.gs2, client)
        game._load_npc_scripts()
        game._trigger_playerenters()

        start = time.monotonic()
        frames = 0
        deadline = start + seconds
        while time.monotonic() < deadline and client.connected:
            game._frame_dt = FRAME_DT
            client.update(timeout=0)
            game._load_new_npcs()
            game._process_pending_warp()
            game._process_self_shoots()
            game.gs1.process_coroutines(FRAME_DT)
            game.gs1.process_timeouts(FRAME_DT)
            game.gs2.process_coroutines(FRAME_DT)
            game.gs2.process_timeouts(FRAME_DT)
            game._check_scripted_link_warp()
            game.gs1.advance_input_frame()
            game._check_level_change()
            game._update_swimming_state()
            game._update_visual_position(FRAME_DT)
            game._update_animations(FRAME_DT)
            game._last_dt = FRAME_DT
            game._render()
            frames += 1
            # Pace to real time so script time ~= wall time (see FRAME_DT).
            slack = (start + frames * FRAME_DT) - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            if verbose and frames % 300 == 0:
                print(f"    ...{frames} frames, {time.monotonic() - start:.0f}s")

        # Open the menu-driven windows, then pump a few more frames so their
        # construction (and any timer it arms) settles before we measure.
        ui_opened = _open_ui(game, open_ui) if open_ui else {}
        if ui_opened:
            for _ in range(int(1.0 / FRAME_DT)):
                game._frame_dt = FRAME_DT
                client.update(timeout=0)
                game.gs2.process_coroutines(FRAME_DT)
                game.gs2.process_timeouts(FRAME_DT)
                game._render()
                frames += 1

        wall = time.monotonic() - start
        gs2 = game.gs2
        host_after = snapshot_host_counters()
        host_calls = delta_counters(host_before["called"], host_after["called"])
        missing = sorted(delta_counters(host_before["missing"],
                                        host_after["missing"]))
        logs = snapshot_logs(capture)

        fingerprint: Dict[str, Any] = {
            "seconds": round(seconds, 2),
            "wall_seconds": round(wall, 2),
            "frames": frames,
            "replayed_bytecode": replayed,
            "ui_opened": dict(sorted(ui_opened.items())),
            "connected_at_end": bool(client.connected),
            "level": (getattr(client, "_current_level_name", "") or
                      getattr(getattr(client, "player", None), "level", "") or ""),
            "bytecodes": snapshot_bytecodes(client),
            "vms": snapshot_vms(gs2),
            # GS1 content is the other half of "did the scripts run?": on
            # classic/GS1 worlds (and our own gs2emu fixtures) there is no
            # GS2 GUI at all, and a level whose NPC scripts stopped loading
            # shows up here.
            "world": {
                "npcs": len(getattr(client, "npcs", {}) or {}),
                "gs1_scripts": len(getattr(game.gs1, "scripts", {}) or {}),
                "weapons": len(getattr(client, "weapons", {}) or {}),
            },
            "gui": snapshot_gui(gs2.gui) if gs2.gui is not None else {
                "roots": 0, "controls": 0, "named": 0, "max_depth": 0,
                "root_names": [], "root_classes": {}, "classes": {},
                "tree_names": [],
            },
            "events": _event_views(recorder.events),
            "host_calls": {
                "total": sum(host_calls.values()),
                "distinct": len(host_calls),
                "names": sorted(host_calls),
                "missing": missing,
            },
            "logs": {
                "warnings": logs["warnings"],
                "errors": logs["errors"],
                "kinds": sorted(logs["kinds"]),
                "samples": [logs["samples"][k] for k in sorted(logs["kinds"])],
            },
            "assets": {
                "refused": sum(logs["refused"].values()),
                "names": sorted(logs["refused"]),
            },
        }
        return fingerprint
    finally:
        uninstall()
        root_logger.removeHandler(capture)
        try:
            game.sound_mgr.stop_all()
            game.sound_mgr.stop_music()
        except Exception:
            pass


def capture_target(target: Target, username: str, password: str,
                   verbose: bool = False) -> Dict[str, Any]:
    """Connect, log in, fingerprint, disconnect.  One connection, no writes.

    No settle poll: capture_from_client() pumps its own paced frames and the
    fingerprint is meant to include however the login itself unfolded.
    """
    from .login import login_session

    with login_session(target.host, target.port, username, password,
                       version=target.version, timeout=15.0,
                       settle=False) as session:
        if not session.connected:
            raise RuntimeError(f"connect failed: {target.host}:{target.port}")
        if not session.accepted:
            reason = session.rejection or "no reason given"
            raise RuntimeError(f"login rejected by {target.name}: {reason}")
        fingerprint = capture_from_client(session.client, target.seconds,
                                          verbose=verbose,
                                          open_ui=target.open_ui)
        fingerprint["address"] = {"host": target.host, "port": target.port}
        fingerprint["version"] = target.version
        return fingerprint


def _metric(fingerprint: Dict[str, Any], path: str) -> int:
    node: Any = fingerprint
    for part in path.split("."):
        if not isinstance(node, dict):
            return 0
        node = node.get(part, 0)
    if isinstance(node, bool):
        return int(node)
    if isinstance(node, (int, float)):
        return int(node)
    if isinstance(node, (list, dict)):
        return len(node)
    return 0


#: metric -> (relative tolerance, absolute slack).  A metric passes when it
#: lands in [base*(1-tol) - slack, base*(1+tol) + slack].
#:
#: THESE NUMBERS ARE JUDGEMENT CALLS, NOT MEASUREMENTS.  The shape of the
#: judgement:
#:   * things content authors change one at a time (a weapon, a window) get
#:     tol 0 and slack 1-3, because a branch flip moves them by much more;
#:   * things that scale with observation time (host calls, event calls) get
#:     a wide tolerance -- they are here to catch "the scripts stopped doing
#:     anything", not to police a 20% drift;
#:   * tree depth is near-constant for a given UI, so slack 1.
#: Retune here, or per server via the baseline's "tolerance" map.
METRIC_BANDS: Dict[str, Tuple[float, int]] = {
    "vms.weapon": (0.0, 1),
    "vms.class": (0.0, 1),
    "vms.npc_count": (0.5, 3),
    "bytecodes.weapon": (0.0, 2),
    "world.npcs": (0.3, 2),
    "world.gs1_scripts": (0.3, 2),
    "world.weapons": (0.0, 1),
    "gui.roots": (0.25, 1),
    "gui.named": (0.25, 3),
    "gui.controls": (0.25, 3),
    "gui.max_depth": (0.0, 1),
    # CONTENT, not structure. These are the metrics that would have caught
    # the 2026-07-25 outage: every structural count was inside its band while
    # the server list held zero rows. Banded loosely (a public server list
    # legitimately gains and loses entries, and chat/news panes churn), but a
    # branch that never populates a control at all lands at 0, which no
    # sensible band around a healthy value contains.
    "gui.tree_nodes": (0.6, 2),
    "gui.list_rows": (0.5, 3),
    "gui.text_controls": (0.4, 3),
    "events.distinct": (0.25, 2),
    "events.calls": (0.6, 5),
    "host_calls.total": (0.6, 25),
    "host_calls.distinct": (0.25, 3),
}

#: Human-facing names, so a failure reads like the thing that broke.
METRIC_LABELS = {
    "vms.weapon": "weapon_vms",
    "vms.class": "class_vms",
    "vms.npc_count": "npc_vms",
    "bytecodes.weapon": "weapon_bytecodes",
    "world.npcs": "level_npcs",
    "world.gs1_scripts": "gs1_scripts",
    "world.weapons": "player_weapons",
    "gui.roots": "gui_roots",
    "gui.named": "gui_named",
    "gui.controls": "gui_controls",
    "gui.max_depth": "gui_depth",
    "gui.tree_nodes": "tree_nodes",
    "gui.list_rows": "list_rows",
    "gui.text_controls": "text_controls",
    "events.distinct": "events_distinct",
    "events.calls": "event_calls",
    "host_calls.total": "host_calls",
    "host_calls.distinct": "host_builtins",
}


@dataclass
class InvariantResult:
    name: str
    passed: bool
    actual: str
    expected: str
    baseline: str

    def line(self) -> str:
        mark = "\033[92mPASS\033[0m" if self.passed else "\033[91mFAIL\033[0m"
        text = f"    [{mark}] {self.name:<18} {self.actual}"
        if not self.passed:
            text += f"\n           expected {self.expected} (baseline {self.baseline})"
        return text


def band_for(value: int, tolerance: float, slack: int) -> Tuple[int, int]:
    low = max(0, int(math.floor(value * (1.0 - tolerance))) - slack)
    high = int(math.ceil(value * (1.0 + tolerance))) + slack
    return low, high


def default_pins(fingerprint: Dict[str, Any]) -> Dict[str, Any]:
    """Pins a fresh baseline starts with. Hand-edit them, they are preserved.

    `required_controls` defaults to the NAMES OF THE ROOT CONTROLS only, not
    all ~90 named controls: roots are the windows a script decided to build,
    which is exactly the branch-flip signal, and they survive ordinary
    content churn inside a window.
    """
    gui = fingerprint.get("gui", {})
    return {
        "required_weapons": list(fingerprint.get("vms", {}).get("weapon", [])),
        # Populate by hand with weapons that must NEVER load -- e.g. the
        # legacy Login fallback path (-serverlist / -serverlistscreen /
        # -irc_login3) that only appears when the modern path was skipped.
        "forbidden_weapons": [],
        "required_controls": list(gui.get("root_names", [])),
        # Controls that must hold CONTENT (tree nodes / list rows / text).
        # Seeded from everything that was filled when the baseline was taken;
        # trim by hand to the ones that matter, because "this pane happened to
        # have text in it" is weaker evidence than "the server list has rows".
        "required_filled_controls": list(gui.get("filled_controls", [])),
        # Window pairs that are ALLOWED to intersect (a floating window a
        # script deliberately opens over a tiled layout). Empty means the
        # layout must stay tiled.
        "allowed_window_overlaps": list(gui.get("window_overlaps", [])),
        "required_event_kinds": list(fingerprint.get("events", {}).get("kinds", [])),
        "required_weapon_events": list(
            fingerprint.get("events", {}).get("weapon_events", [])),
    }


def _fmt_set(values: Iterable[str], limit: int = 6) -> str:
    values = list(values)
    head = ", ".join(values[:limit])
    if len(values) > limit:
        head += f", ... (+{len(values) - limit})"
    return head or "(none)"


def compare(observed: Dict[str, Any], entry: Dict[str, Any]) -> List[InvariantResult]:
    """Check one fingerprint against one baseline entry."""
    base = entry.get("observed", {})
    pins = entry.get("pins", {})
    overrides = entry.get("tolerance", {})
    # Invariants a given server cannot honour. The escape hatch exists for
    # metrics that depend on where the ACCOUNT is standing rather than on
    # what the content did: our own gs2emu instances drop us in whatever
    # level the account was last saved in, so level_npcs/gs1_scripts there
    # measure the level, not the engine.
    ignored = {str(name) for name in entry.get("ignore", [])}
    results: List[InvariantResult] = []

    for path, (tolerance, slack) in METRIC_BANDS.items():
        label = METRIC_LABELS.get(path, path)
        tolerance = float(overrides.get(label, overrides.get(path, tolerance)))
        base_value = _metric(base, path)
        value = _metric(observed, path)
        low, high = band_for(base_value, tolerance, slack)
        results.append(InvariantResult(
            name=label,
            passed=low <= value <= high,
            actual=str(value),
            expected=f"{low}..{high}",
            baseline=str(base_value),
        ))

    # --- the connection itself -------------------------------------------
    results.append(InvariantResult(
        name="stayed_connected",
        passed=bool(observed.get("connected_at_end")),
        actual="connected" if observed.get("connected_at_end") else "DROPPED",
        expected="connected",
        baseline="connected" if base.get("connected_at_end", True) else "DROPPED",
    ))

    # --- weapons that must / must not load --------------------------------
    weapons = set(observed.get("vms", {}).get("weapon", []))
    required = {str(w).lower() for w in pins.get("required_weapons", [])}
    missing = sorted(required - weapons)
    results.append(InvariantResult(
        name="weapons_present",
        passed=not missing,
        actual=f"missing {_fmt_set(missing)}" if missing else f"all {len(required)} present",
        expected=f"loads {_fmt_set(sorted(required))}",
        baseline=_fmt_set(sorted(base.get("vms", {}).get("weapon", []))),
    ))
    forbidden = {str(w).lower() for w in pins.get("forbidden_weapons", [])}
    intruders = sorted(forbidden & weapons)
    results.append(InvariantResult(
        name="weapons_forbidden",
        passed=not intruders,
        actual=f"loaded {_fmt_set(intruders)}" if intruders else "none loaded",
        expected=f"never loads {_fmt_set(sorted(forbidden))}" if forbidden else "n/a",
        baseline="none loaded",
    ))

    # --- GUI shape ---------------------------------------------------------
    tree_names = set(observed.get("gui", {}).get("tree_names", []))
    root_names = set(observed.get("gui", {}).get("root_names", []))
    reachable = tree_names | root_names
    want_controls = {str(c).lower() for c in pins.get("required_controls", [])}
    absent = sorted(want_controls - reachable)
    results.append(InvariantResult(
        name="controls_present",
        passed=not absent,
        actual=f"missing {_fmt_set(absent)}" if absent else f"all {len(want_controls)} present",
        expected=f"builds {_fmt_set(sorted(want_controls))}",
        baseline=f"{len(base.get('gui', {}).get('root_names', []))} root controls",
    ))
    # --- menu-driven UI openers -------------------------------------------
    ui = observed.get("ui_opened", {}) or {}
    broken_openers = sorted(k for k, v in ui.items() if v != "ok")
    if ui or base.get("ui_opened"):
        results.append(InvariantResult(
            name="ui_openers",
            passed=not broken_openers,
            actual=(f"failed {_fmt_set([f'{k} ({ui[k]})' for k in broken_openers], 3)}"
                    if broken_openers else f"all {len(ui)} opened"),
            expected="every configured opener runs",
            baseline=f"{len(base.get('ui_opened', {}) or {})} openers",
        ))

    # --- GUI CONTENT: are the controls actually populated? -----------------
    # See the `controls_filled` invariant below.
    # Nothing structural moved.
    filled = {str(c).lower() for c in observed.get("gui", {}).get("filled_controls", [])}
    want_filled = {str(c).lower() for c in pins.get("required_filled_controls", [])}
    empty = sorted(want_filled - filled)
    results.append(InvariantResult(
        name="controls_filled",
        passed=not empty,
        actual=f"empty {_fmt_set(empty)}" if empty else f"all {len(want_filled)} populated",
        expected=f"populates {_fmt_set(sorted(want_filled))}",
        baseline=f"{len(base.get('gui', {}).get('filled_controls', []))} populated",
    ))

    # --- GUI GEOMETRY -------------------------------------------------------
    # A control that hangs out of its parent, or that has collapsed to zero
    # area, is a layout bug the counts cannot see. Global Chat's frame set
    # was unimplemented, so its two cells kept their constructor defaults
    # (160x120 over 100x24 at the same origin) and the chat field hung 22px
    # through the bottom of the window.
    overflowing = observed.get("gui", {}).get("overflowing", [])
    base_overflowing = base.get("gui", {}).get("overflowing", [])
    new_overflow = sorted(set(overflowing) - set(base_overflowing))
    results.append(InvariantResult(
        name="within_parent",
        passed=not new_overflow,
        actual=(f"{len(new_overflow)} outside parent: " + _fmt_set(new_overflow)
                if new_overflow else "none"),
        expected="no control outside its parent's bounds beyond the baseline set",
        baseline=f"{len(base_overflowing)} known",
    ))
    degenerate = observed.get("gui", {}).get("degenerate", [])
    base_degenerate = base.get("gui", {}).get("degenerate", [])
    new_degenerate = sorted(set(degenerate) - set(base_degenerate))
    results.append(InvariantResult(
        name="nonzero_area",
        passed=not new_degenerate,
        actual=(f"{len(new_degenerate)} collapsed: " + _fmt_set(new_degenerate)
                if new_degenerate else "none"),
        expected="no visible control collapsed to zero area",
        baseline=f"{len(base_degenerate)} known",
    ))
    overlaps = set(observed.get("gui", {}).get("window_overlaps", []))
    allowed = {str(p).lower() for p in pins.get("allowed_window_overlaps", [])}
    bad_overlaps = sorted(overlaps - allowed)
    results.append(InvariantResult(
        name="window_layout",
        passed=not bad_overlaps,
        actual=(f"{len(bad_overlaps)} overlapping: " + _fmt_set(bad_overlaps)
                if bad_overlaps else f"{len(overlaps)} known overlaps"),
        expected="no unexpected pair of visible windows intersects",
        baseline=f"{len(base.get('gui', {}).get('window_overlaps', []))} known",
    ))

    base_classes = set(base.get("gui", {}).get("classes", {}))
    now_classes = set(observed.get("gui", {}).get("classes", {}))
    lost_classes = sorted(base_classes - now_classes)
    results.append(InvariantResult(
        name="control_classes",
        passed=not lost_classes,
        actual=f"lost {_fmt_set(lost_classes)}" if lost_classes else f"{len(now_classes)} kinds",
        expected=f"still builds {_fmt_set(sorted(base_classes))}",
        baseline=f"{len(base_classes)} kinds",
    ))

    # --- events that fired -------------------------------------------------
    kinds = set(observed.get("events", {}).get("kinds", []))
    want_kinds = set(pins.get("required_event_kinds", []))
    lost_kinds = sorted(want_kinds - kinds)
    results.append(InvariantResult(
        name="event_kinds",
        passed=not lost_kinds,
        actual=(f"never fired {_fmt_set(lost_kinds)}" if lost_kinds
                else f"all {len(want_kinds)} fired"),
        expected=f"fires {_fmt_set(sorted(want_kinds))}",
        baseline=_fmt_set(sorted(base.get("events", {}).get("kinds", []))),
    ))
    weapon_events = set(observed.get("events", {}).get("weapon_events", []))
    want_weapon_events = set(pins.get("required_weapon_events", []))
    lost_weapon_events = sorted(want_weapon_events - weapon_events)
    results.append(InvariantResult(
        name="weapon_events",
        passed=not lost_weapon_events,
        actual=(f"never fired {_fmt_set(lost_weapon_events)}" if lost_weapon_events
                else f"all {len(want_weapon_events)} fired"),
        expected=f"fires {_fmt_set(sorted(want_weapon_events))}",
        baseline=_fmt_set(sorted(base.get("events", {}).get("weapon_events", []))),
    ))

    # --- engine noise ------------------------------------------------------
    # Strict, not banded: a NEW missing builtin or a NEW warning template is a
    # gap the engine did not have when the baseline was taken, and the count
    # of hard errors must never grow.
    new_missing = sorted(set(observed.get("host_calls", {}).get("missing", [])) -
                         set(base.get("host_calls", {}).get("missing", [])))
    results.append(InvariantResult(
        name="no_new_gaps",
        passed=not new_missing,
        actual=f"new missing builtins {_fmt_set(new_missing)}" if new_missing else "none",
        expected="no builtins missing beyond the baseline set",
        baseline=_fmt_set(sorted(base.get("host_calls", {}).get("missing", []))),
    ))
    new_kinds = sorted(set(observed.get("logs", {}).get("kinds", [])) -
                       set(base.get("logs", {}).get("kinds", [])))
    results.append(InvariantResult(
        name="no_new_warnings",
        passed=not new_kinds,
        actual=(f"{len(new_kinds)} new: " + _fmt_set(
            [k.split("|")[-1] for k in new_kinds], 3)) if new_kinds else "none",
        expected="no warning templates beyond the baseline set",
        baseline=f"{len(base.get('logs', {}).get('kinds', []))} known kinds",
    ))
    # Refused files get a CEILING, not a band: fewer refusals is always an
    # improvement (2026-07-31 removed one by honouring the "-" no-image
    # sentinel), while a jump means we started asking for art nobody has --
    # which is a client bug even though each individual refusal is not.
    # The allowance is proportional because refusals scale with how many
    # servers the login list happens to be carrying.
    base_refused = int(base.get("assets", {}).get("refused", 0))
    now_refused = int(observed.get("assets", {}).get("refused", 0))
    allowed_refused = int(base_refused * 1.5) + 3
    results.append(InvariantResult(
        name="assets_refused",
        passed=now_refused <= allowed_refused,
        actual=(f"{now_refused}: " + _fmt_set(
            observed.get("assets", {}).get("names", []), 4)) if now_refused else "0",
        expected=f"<= {allowed_refused}",
        baseline=str(base_refused),
    ))
    base_errors = int(base.get("logs", {}).get("errors", 0))
    now_errors = int(observed.get("logs", {}).get("errors", 0))
    results.append(InvariantResult(
        name="log_errors",
        passed=now_errors <= base_errors,
        actual=str(now_errors),
        expected=f"<= {base_errors}",
        baseline=str(base_errors),
    ))
    return [result for result in results if result.name not in ignored]


def empty_baselines() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "servers": {}}


def load_baselines(path: Path | str = BASELINE_PATH) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_baselines()
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(
            data.get("servers"), dict):
        raise ValueError(f"unsupported behaviour-baseline file: {path}")
    return data


def save_baselines(data: Dict[str, Any], path: Path | str = BASELINE_PATH) -> None:
    data["schema_version"] = SCHEMA_VERSION
    Path(path).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_entry(target: Target, fingerprint: Dict[str, Any],
               previous: Optional[Dict[str, Any]] = None,
               reset_pins: bool = False) -> Dict[str, Any]:
    """Build/refresh a baseline entry.

    Pins (required/forbidden sets) are HAND-CURATED knowledge -- e.g. "the
    legacy `-serverlist` weapon must never load" is something a person
    learned from an outage, not something a capture can infer.  A rebaseline
    therefore refreshes the measured `observed` block but keeps existing pins
    unless explicitly told to reset them.
    """
    pins = default_pins(fingerprint)
    if previous and not reset_pins:
        # MERGE, don't replace: a wholesale swap meant a pin kind added after
        # a baseline was recorded could never reach it -- every rebaseline
        # restored the old dict, so `required_filled_controls` (added
        # 2026-07-25) stayed absent on all six servers and silently checked
        # nothing. Keys the previous entry curated win; keys it never had are
        # seeded from this capture.
        for key, value in previous.get("pins", {}).items():
            pins[key] = value
    entry = {
        "address": {"host": target.host, "port": target.port},
        "version": target.version,
        "seconds": target.seconds,
        "passive": target.passive,
        "open_ui": list(target.open_ui),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "observed": fingerprint,
        "pins": pins,
        "tolerance": (previous or {}).get("tolerance", {}),
        "ignore": (previous or {}).get("ignore", []),
    }
    return entry


def target_for(name: str, entry: Optional[Dict[str, Any]] = None,
               host: Optional[str] = None, port: Optional[int] = None,
               seconds: Optional[float] = None) -> Target:
    """Resolve a target from (in order) explicit args, baseline, defaults."""
    default = DEFAULT_TARGETS.get(name)
    address = (entry or {}).get("address", {})
    resolved_host = host or address.get("host") or (default.host if default else None)
    resolved_port = port or address.get("port") or (default.port if default else None)
    if not resolved_host or not resolved_port:
        raise ValueError(
            f"no address known for {name!r}: pass --host/--port to bootstrap it")
    open_ui = (entry or {}).get("open_ui")
    if open_ui is None:
        open_ui = list(default.open_ui) if default else []
    return Target(
        name=name,
        host=resolved_host,
        port=int(resolved_port),
        version=(entry or {}).get("version") or (default.version if default else "6.037"),
        seconds=float(seconds if seconds is not None else
                      (entry or {}).get("seconds",
                                        default.seconds if default else DEFAULT_SECONDS)),
        passive=(entry or {}).get("passive", default.passive if default else True),
        open_ui=tuple(str(spec) for spec in open_ui),
    )


def print_report(name: str, results: List[InvariantResult]) -> bool:
    failed = [r for r in results if not r.passed]
    status = "\033[91mFAIL\033[0m" if failed else "\033[92mOK\033[0m"
    print(f"\n[BEHAVIOUR] {name}: {status} "
          f"({len(results) - len(failed)}/{len(results)} invariants)")
    for result in results:
        if not result.passed:
            print(result.line())
    if not failed:
        print("    all invariants within baseline bands")
    return not failed


def check_fingerprint(name: str, fingerprint: Dict[str, Any],
                      baselines: Dict[str, Any]) -> bool:
    """Compare one captured fingerprint against the stored baseline."""
    entry = baselines.get("servers", {}).get(name)
    if entry is None:
        print(f"\n[BEHAVIOUR] {name}: \033[93mNO BASELINE\033[0m "
              f"(run --behaviour --behaviour-server {name!r} --rebaseline)")
        return True
    return print_report(name, compare(fingerprint, entry))


def run_behaviour_checks(selected: Optional[str] = None, *,
                         rebaseline: bool = False, reset_pins: bool = False,
                         host: Optional[str] = None, port: Optional[int] = None,
                         seconds: Optional[float] = None,
                         path: Path | str = BASELINE_PATH,
                         verbose: bool = False) -> bool:
    """Fingerprint every baselined server (or one) and check or rewrite it."""
    from pyreborn.prefs import Prefs

    baselines = load_baselines(path)
    names = list(baselines.get("servers", {}))
    if selected:
        names = [selected]
    elif rebaseline and not names:
        names = list(DEFAULT_TARGETS)
    if not names:
        print("no behaviour baselines recorded; bootstrap one with "
              "--behaviour --behaviour-server NAME --host H --port P --rebaseline")
        return False

    prefs = Prefs.load()
    all_ok = True
    for index, name in enumerate(names):
        entry = baselines.get("servers", {}).get(name)
        try:
            target = target_for(name, entry, host, port, seconds)
        except ValueError as exc:
            print(f"\n[BEHAVIOUR] {name}: \033[91mFAIL\033[0m {exc}")
            all_ok = False
            continue
        if index:
            time.sleep(REMOTE_SPACING if target.passive else 1.0)
        print(f"\n[BEHAVIOUR] {name} -> {target.host}:{target.port} "
              f"({target.seconds:.0f}s, {'passive' if target.passive else 'local'})")
        try:
            fingerprint = capture_target(target, prefs.username, prefs.password,
                                         verbose=verbose)
        except Exception as exc:
            print(f"    \033[91mFAIL\033[0m capture failed: {exc}")
            all_ok = False
            continue
        if rebaseline:
            baselines.setdefault("servers", {})[name] = make_entry(
                target, fingerprint, entry, reset_pins=reset_pins)
            save_baselines(baselines, path)
            gui = fingerprint["gui"]
            print(f"    rebaselined: {len(fingerprint['vms']['weapon'])} weapon VMs, "
                  f"{gui['roots']} gui roots, {gui['named']} named controls, "
                  f"{fingerprint['host_calls']['total']} host calls")
        else:
            all_ok = check_fingerprint(name, fingerprint, baselines) and all_ok
    return all_ok
