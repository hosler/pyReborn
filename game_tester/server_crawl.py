"""Bounded, read-only deep-content crawl for public game servers."""

from __future__ import annotations

import logging
import os
import re
import signal
import threading
import time
import traceback
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable

from pyreborn.gani import GaniParser


MAX_FILES = 40
MAX_GS1_OPS = 50_000
MAX_GS1_SECONDS = 1.0
MAX_GS2_OPS = 200_000
MAX_GS2_SECONDS = 2.0
SOAK_SECONDS = 3.0
SOAK_DT = 0.05
SOAK_FRAME_INTERVAL = 0.5
SOAK_WALL_SECONDS = 5.0
TRACEBACK_LIMIT = 4000

# Calls intentionally outside a portable Python client's remit. Exact entries
# document the boundary; the two prefixes cover families of engine internals.
KNOWN_UNSUPPORTED_CALLS = {
    "quattro::*": "native Quattro audio-engine API",
    "gameobject::find": "native engine object registry",
    "object::findanyobjectbytype": "native engine object registry",
    "getdevicemodel": "native device identification",
    "setretinadisplaynoantialias": "native Retina display configuration",
    "switchopengldevicescale": "native OpenGL device scaling",
    "getscalefactor": "native display scale query",
    "getplatform": "native platform identification",
    "getpremiumoption": "proprietary account entitlement query",
    "getgamesubversion": "native client build metadata",
    "adventure_setframetick": "engine frame scheduler control",
    "setframetick": "engine frame scheduler control",
    "getframetick": "engine frame scheduler query",
    "fileupdate": "native client patcher operation",
    "switchopengl*": "native OpenGL backend configuration",
}


def is_known_unsupported(name: str) -> bool:
    """Return whether *name* matches the documented unsupported registry."""
    normalized = str(name).casefold()
    return (normalized.startswith("quattro::") or
            normalized.startswith("switchopengl") or
            normalized in KNOWN_UNSUPPORTED_CALLS)


def classify_host_call(name: str, implemented_surface: set[str],
                       stubbed_surface: set[str] | None = None) -> str:
    """Classify an intercepted call against a real client host surface."""
    normalized = str(name).casefold()
    if is_known_unsupported(normalized):
        return "known_unsupported"
    if normalized in {item.casefold() for item in (stubbed_surface or set())}:
        return "implemented_stub"
    if normalized in {item.casefold() for item in implemented_surface}:
        return "implemented"
    return "true_gap"


def real_gs1_surface() -> set[str]:
    """Introspect the live GS1 host's command/function dispatch surface."""
    from pyreborn.gs1_client import GS1ClientHost
    return set(GS1ClientHost.host_surface())


def real_gs2_surface() -> set[str]:
    """Introspect the live GS2 host's builtin/delegated dispatch surface."""
    from pyreborn.gs2_client import GS2ClientHost
    return set(GS2ClientHost.host_surface())


def real_gs2_stubbed_surface() -> set[str]:
    from pyreborn.gs2_client import GS2ClientHost
    return set(GS2ClientHost.stubbed)


class _WallBudgetExceeded(BaseException):
    """Escape the VM's ordinary Exception backstop when wall time expires."""


class _ResolvedCallFilter(logging.Filter):
    """Drop the VM's "unknown function/method" warnings for names the REAL
    client host resolves.

    The crawl deliberately runs bytecode against RecordingHost, which answers
    every host call with NOT_HANDLED so the call gets recorded — the VM then
    logs "unknown function X()" even though the live client's GS2ClientHost
    implements X. Those warnings misled a whole debugging round (sendtext/
    sort/makefirstresponder/findweapon/echo/isobject were all reported
    "unknown" while the catalog correctly classified them implemented).
    Classification is untouched — builtins_missing/host.calls still record
    everything; only the misleading stderr line is suppressed, so surviving
    unknown-call warnings during a crawl are genuine true gaps."""

    _CALL = re.compile(r"unknown (?:function|method) ([\w:.]+)\(\)")

    def __init__(self, resolved_names: set[str]):
        super().__init__()
        self._resolved = resolved_names

    def filter(self, record: logging.LogRecord) -> bool:
        match = self._CALL.search(record.getMessage())
        if match is None:
            return True
        name = match.group(1).casefold()
        return not (name in self._resolved or is_known_unsupported(name))


def shaped_error(phase: str, *, level: str = "", asset: str = "",
                 exception: BaseException | str, tb: str | None = None,
                 context: str = "") -> dict[str, str]:
    """Return the stable, bounded error shape stored in the catalog."""
    exc_text = (f"{type(exception).__name__}: {exception}"
                if isinstance(exception, BaseException) else str(exception))
    result = {"phase": phase, "exception": exc_text[:1000],
              "traceback": (tb or traceback.format_exc())[-TRACEBACK_LIMIT:]}
    if level:
        result["level"] = level
    if asset:
        result["asset"] = asset
    if context:
        result["context"] = context
    return result


def empty_crawl_record() -> dict[str, Any]:
    return {
        "levels_visited": [],
        "counts": {"levels": 0, "signs": 0, "links": 0, "npcs": 0,
                   "baddies": 0, "chests": 0},
        "files_parsed": {"ok": 0, "failed": 0},
        "gmap": {"name": "", "grid_size": [0, 0], "segments_visited": 0},
        "soak": {"frames": 0, "errors": 0},
        "gs2": {"ran": 0, "failed": 0, "capped": 0,
                "events_found": 0, "events_ran": 0, "events_failed": 0,
                "event_names": [], "implemented_count": 0,
                "true_gaps": [], "known_unsupported": []},
        "gs1_parse": {"ok": 0, "failed": 0},
        "gs1_exec": {"ran": 0, "failed": 0, "capped": 0,
                     "implemented_count": 0, "true_gaps": [],
                     "known_unsupported": []},
        "render": {"ok": 0, "failed": 0},
        "errors": [],
    }


class RecordingHost:
    """Inert GS2 host which records calls the VM cannot implement itself."""

    def __init__(self) -> None:
        from reborn_protocol.gs2.vm import GS2Host
        self._base = GS2Host()
        self.calls: Counter[str] = Counter()
        self.globals: dict[str, Any] = {}

    def call_builtin(self, vm, name, args, obj=None):
        from reborn_protocol.gs2.vm import NOT_HANDLED
        self.calls[str(name)] += 1
        return NOT_HANDLED

    def get_object(self, name):
        return None

    def create_object(self, classname, arg):
        from reborn_protocol.gs2.values import GS2Object
        return GS2Object(name=classname)

    def sleep(self, vm, seconds):
        return None

    def get_globals(self):
        return self.globals


class RecordingGS1Host:
    """Total, inert GS1 host used only for compatibility discovery."""

    def __init__(self) -> None:
        self.accesses: list[tuple[str, str]] = []
        self.commands: Counter[str] = Counter()

    def get_builtin(self, name, indices, ctx):
        self.accesses.append(("get", str(name)))
        return 0.0

    def set_builtin(self, name, value, indices, ctx) -> bool:
        self.accesses.append(("set", str(name)))
        return True

    def call_command(self, name, args, ctx) -> None:
        self.commands[str(name)] += 1
        self.accesses.append(("command", str(name)))

    def call_function(self, name, args, ctx):
        self.commands[str(name)] += 1
        self.accesses.append(("function", str(name)))
        return 0.0

    def message_code(self, code, args, ctx) -> str:
        self.accesses.append(("message_code", str(code)))
        return ""

    def weapon_message_code(self, code, index, ctx) -> str:
        self.accesses.append(("weapon_message_code", str(code)))
        return ""


def _with_wall_alarm(seconds: float, action: Callable[[], None]) -> bool:
    """Run an action and return whether the main-thread wall alarm fired."""
    can_alarm = (seconds > 0 and threading.current_thread() is
                 threading.main_thread() and hasattr(signal, "setitimer"))
    previous_handler = None
    try:
        if can_alarm:
            previous_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM,
                          lambda _signum, _frame: (_ for _ in ()).throw(
                              _WallBudgetExceeded()))
            signal.setitimer(signal.ITIMER_REAL, seconds)
        action()
        return False
    except _WallBudgetExceeded:
        return True
    finally:
        if can_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)


def run_gs1_bounded(source: str, *, max_ops: int = MAX_GS1_OPS,
                    wall_seconds: float = MAX_GS1_SECONDS) -> dict[str, Any]:
    """Run the two received-NPC lifecycle events with an inert host."""
    from reborn_protocol.gs1.interp import Interpreter
    from reborn_protocol.gs1.parser import parse
    from reborn_protocol.gs1.runtime import Context

    program = parse(source)
    host = RecordingGS1Host()
    started = time.monotonic()
    steps = 0

    def execute() -> None:
        nonlocal steps
        for event in ("created", "playerenters"):
            ctx = Context(host, this_obj={})
            ctx.max_steps = max(0, max_ops - steps)
            try:
                Interpreter(ctx).run_event(program, event)
            finally:
                steps += ctx.steps

    budget_capped = False
    try:
        wall_capped = _with_wall_alarm(wall_seconds, execute)
    except RuntimeError as exc:
        if "step budget exceeded" not in str(exc).lower():
            raise
        wall_capped = False
        budget_capped = True
    elapsed = time.monotonic() - started
    classifications = _classify_calls(host.commands, real_gs1_surface())
    return {"capped": budget_capped or wall_capped or steps >= max_ops or
            elapsed >= wall_seconds,
            "steps": steps, "elapsed": elapsed,
            **classifications, "host": host}


def _classify_calls(calls: Counter[str], surface: set[str]) -> dict[str, Any]:
    buckets = {"implemented": [], "implemented_stub": [], "true_gap": [],
               "known_unsupported": []}
    implemented_count = 0
    stubbed = real_gs2_stubbed_surface() if surface == real_gs2_surface() else set()
    for name, count in calls.items():
        classification = classify_host_call(name, surface, stubbed)
        if classification in ("implemented", "implemented_stub"):
            implemented_count += count
        if classification != "implemented":
            buckets[classification].append(name)
    return {"implemented_count": implemented_count,
            "stubbed": sorted(buckets["implemented_stub"], key=str.casefold),
            "true_gaps": sorted(buckets["true_gap"], key=str.casefold),
            "known_unsupported": sorted(buckets["known_unsupported"],
                                        key=str.casefold)}


def enumerate_gs2_events(functions: Any) -> list[str]:
    """Return event-shaped entries discovered from a GS2 function table.

    Covers bare events (onCreated) and dotted control/universe handlers
    (GlobalChat_ChatTab.onSelect, universe.onPlayerLogin) -- the official
    Login weapons register plenty of the latter and the old startswith("on")
    filter skipped them all."""
    names = functions.keys() if isinstance(functions, dict) else functions
    events = set()
    for name in names:
        text = str(name)
        if text.rsplit(".", 1)[-1].lower().startswith("on"):
            events.add(text)
    return sorted(events, key=str.casefold)


def run_gs2_bounded(blob: bytes, name: str = "script",
                    max_ops: int = MAX_GS2_OPS,
                    wall_seconds: float = MAX_GS2_SECONDS) -> dict[str, Any]:
    """Parse and run bytecode with an inert host and strict operation budget."""
    from reborn_protocol.gs2.vm import GS2VM

    host = RecordingHost()
    before_skipped = dict(GS2VM.ops_skipped)
    before_missing = dict(GS2VM.builtins_missing)
    started = time.monotonic()
    vm = GS2VM(blob, name=name, host=host)
    vm.max_ops = max_ops
    wall_capped = False
    events: list[str] = []
    event_failures: list[str] = []
    total_ops = 0
    op_capped = False

    def execute() -> None:
        nonlocal total_ops, op_capped
        vm.run_toplevel()
        total_ops += vm._ops_used
        op_capped = op_capped or vm._ops_used >= max_ops
        events.extend(enumerate_gs2_events(getattr(vm, "functions", {})))
        for event in events:
            vm.call(event)
            total_ops += vm._ops_used
            op_capped = op_capped or vm._ops_used >= max_ops
            if vm._errors:
                event_failures.append(event)

    vm_logger = logging.getLogger("reborn_protocol.gs2.vm")
    resolved_filter = _ResolvedCallFilter(
        {item.casefold() for item in real_gs2_surface()})
    vm_logger.addFilter(resolved_filter)
    try:
        wall_capped = _with_wall_alarm(wall_seconds, execute)
    finally:
        vm_logger.removeFilter(resolved_filter)
    elapsed = time.monotonic() - started
    capped = op_capped or wall_capped or elapsed >= wall_seconds
    skipped = sorted(op for op, count in GS2VM.ops_skipped.items()
                     if count > before_skipped.get(op, 0))
    missing = {call for call, count in GS2VM.builtins_missing.items()
               if count > before_missing.get(call, 0)}
    calls = host.calls.copy()
    for call in missing:
        calls[call] = max(1, calls[call])
    return {"capped": capped, "steps": total_ops, "elapsed": elapsed,
            "unknown_opcodes": skipped,
            **_classify_calls(calls, real_gs2_surface()),
            "events": events, "event_failures": event_failures}


def parse_nw(data: bytes) -> None:
    """Validate a downloaded text level through its board/entity grammar."""
    text = data.decode("latin-1")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "GLEVNW01":
        raise ValueError("missing GLEVNW01 level header")
    board_rows = [line for line in lines if line.startswith("BOARD ")]
    if board_rows and len(board_rows) != 64:
        raise ValueError(f"expected 64 BOARD rows, got {len(board_rows)}")
    for line in board_rows:
        parts = line.split(maxsplit=5)
        if len(parts) != 6 or int(parts[3]) <= 0:
            raise ValueError("malformed BOARD row")


def parse_gmap(data: bytes) -> tuple[int, int, list[str]]:
    """Validate a downloaded gmap and return its dimensions and segments."""
    width = height = 0
    segments: list[str] = []
    in_names = False
    for raw in data.decode("latin-1").splitlines():
        line = raw.strip()
        if line.startswith("WIDTH "):
            width = int(line.split()[1])
        elif line.startswith("HEIGHT "):
            height = int(line.split()[1])
        elif line == "LEVELNAMES":
            in_names = True
        elif line == "LEVELNAMESEND":
            in_names = False
        elif in_names:
            segments.extend(x.strip() for x in line.replace('"', '').rstrip(',').split(',')
                            if x.strip())
    if width <= 0 or height <= 0 or len(segments) != width * height:
        raise ValueError("malformed gmap dimensions or segment list")
    return width, height, segments


class DeepCrawler:
    """Crawl one authenticated client without chat, combat, pickup, or admin."""

    def __init__(self, client: Any, *, max_levels: int = 15, timeout: float = 120.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 renderer: Callable[[Any, str], None] | None = None,
                 ticker: Callable[[Any, str, float], None] | None = None,
                 soak_seconds: float = SOAK_SECONDS,
                 soak_dt: float = SOAK_DT,
                 soak_frame_interval: float = SOAK_FRAME_INTERVAL,
                 soak_wall_seconds: float = SOAK_WALL_SECONDS) -> None:
        self.client = client
        self.max_levels = max_levels
        self.clock = clock
        self.sleep = sleep
        self.deadline = clock() + timeout
        self.result = empty_crawl_record()
        self.renderer = renderer or self._render_frame
        self.ticker = ticker or ((lambda _client, _level, _dt: None)
                                 if renderer is not None else self._tick_frame)
        self.soak_seconds = soak_seconds
        self.soak_dt = soak_dt
        self.soak_frame_interval = soak_frame_interval
        self.soak_wall_seconds = soak_wall_seconds
        self._assets: set[str] = set()
        self._bytecodes_seen: set[tuple[str, str]] = set()
        self._gmap_visited: set[tuple[int, int]] = set()
        self._foreign_warp = False

    def _level(self) -> str:
        return (getattr(self.client, "_current_level_name", "") or
                getattr(getattr(self.client, "player", None), "level", ""))

    def _pump(self, seconds: float = 0.4) -> None:
        until = min(self.deadline, self.clock() + seconds)
        while self.clock() < until and getattr(self.client, "connected", True):
            self.client.update(timeout=min(0.05, max(0.0, until - self.clock())))

    def _error(self, phase: str, exc: BaseException | str, *, level="", asset="",
               context="") -> None:
        self.result["errors"].append(shaped_error(
            phase, level=level, asset=asset, exception=exc, context=context))

    def crawl(self) -> dict[str, Any]:
        start = self._level()
        if getattr(self.client, "in_gmap_segment", False):
            self._crawl_gmap(start)
            self._parse_assets()
            self._run_bytecodes()
            return self.result
        queue = deque([(start, None)])
        queued = {start.casefold()} if start else set()
        visited: set[str] = set()
        budget_exhausted = False
        while queue and len(visited) < self.max_levels and self.clock() < self.deadline:
            expected, link = queue.popleft()
            if link is not None:
                self.sleep(0.5)
                if self.clock() >= self.deadline:
                    budget_exhausted = True
                    break
                try:
                    if not self.client.use_link(link):
                        continue
                    self._pump()
                except BaseException as exc:
                    self._error("warp", exc, level=expected)
                    continue
            level = self._level() or expected
            key = level.casefold()
            if not level or key in visited:
                continue
            visited.add(key)
            self._inspect_level(level)
            for next_link in list(getattr(self.client, "links", {}).get(level, [])):
                dest = str(next_link.get("dest_level", "")).strip()
                dkey = dest.casefold()
                if dest and dkey not in visited and dkey not in queued:
                    queued.add(dkey)
                    queue.append((dest, next_link))
        if budget_exhausted or (queue and self.clock() >= self.deadline):
            self._error("budget", "crawl time budget exhausted",
                        level=self._level())
        self._parse_assets()
        self._run_bytecodes()
        return self.result

    def _gmap_cell(self, level: str) -> tuple[int, int] | None:
        return next((cell for cell, name in getattr(self.client, "gmap_grid", {}).items()
                     if str(name).casefold() == str(level).casefold()), None)

    def _crawl_gmap(self, start: str) -> None:
        """Breadth-first grid crawl, routing between work items over known seams."""
        grid = dict(getattr(self.client, "gmap_grid", {}))
        origin = self._gmap_cell(start)
        if origin is None:
            self._error("gmap", "current segment is absent from the gmap grid", level=start)
            return
        parent: dict[tuple[int, int], tuple[int, int] | None] = {origin: None}
        queue = deque([origin])
        current = origin
        aborted = False
        while queue and len(self._gmap_visited) < self.max_levels and self.clock() < self.deadline:
            target = queue.popleft()
            route = self._grid_route(current, target, parent)
            for cell in route[1:]:
                if not self._cross_gmap_seam(current, cell, grid[cell]):
                    aborted = True
                    break
                current = cell
            if aborted:
                break
            level = self._level()
            if level.casefold() != str(grid[target]).casefold():
                self._error("gmap_warp", "foreign warp during grid traversal",
                            level=level, context=f"expected {grid[target]}")
                break
            if target not in self._gmap_visited:
                self._gmap_visited.add(target)
                self._inspect_level(level)
                if self._foreign_warp:
                    break
                for dx, dy in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                    neighbour = (target[0] + dx, target[1] + dy)
                    if neighbour in grid and neighbour not in parent:
                        parent[neighbour] = target
                        queue.append(neighbour)
        if queue and self.clock() >= self.deadline:
            self._error("budget", "crawl time budget exhausted", level=self._level())
        self.result["gmap"] = {
            "name": str(getattr(self.client, "gmap_name", "")),
            "grid_size": [int(getattr(self.client, "gmap_width", 0)),
                          int(getattr(self.client, "gmap_height", 0))],
            "segments_visited": len(self._gmap_visited),
        }

    @staticmethod
    def _grid_route(current: tuple[int, int], target: tuple[int, int],
                    parent: dict[tuple[int, int], tuple[int, int] | None]
                    ) -> list[tuple[int, int]]:
        def ancestors(cell):
            out = []
            while cell is not None:
                out.append(cell)
                cell = parent[cell]
            return out
        left, right = ancestors(current), ancestors(target)
        right_set = set(right)
        common = next(cell for cell in left if cell in right_set)
        return left[:left.index(common) + 1] + list(reversed(right[:right.index(common)]))

    def _cross_gmap_seam(self, source: tuple[int, int], target: tuple[int, int],
                         expected_level: str) -> bool:
        dx, dy = target[0] - source[0], target[1] - source[1]
        if abs(dx) + abs(dy) != 1:
            raise ValueError("gmap seam target is not adjacent")
        source_level = str(getattr(self.client, "gmap_grid", {}).get(source, self._level()))
        boundary = ((target[0] * 64 + (0.25 if dx > 0 else 63.75)) if dx else
                    (target[1] * 64 + (0.25 if dy > 0 else 63.75)))
        axis = "x" if dx else "y"
        direction = dx or dy
        while self.clock() < self.deadline:
            level = self._level()
            if level.casefold() == expected_level.casefold():
                self._pump(0.2)
                return self._level().casefold() == expected_level.casefold()
            if level.casefold() != source_level.casefold():
                self._error("gmap_warp", "foreign warp during seam traversal",
                            level=level, context=f"expected {expected_level}")
                return False
            position = float(getattr(self.client, axis))
            if (direction > 0 and position >= boundary) or (direction < 0 and position <= boundary):
                self._pump(0.05)
                continue
            if not self.client.move(dx, dy, step=0.5):
                self._error("gmap_move", "movement packet was rejected", level=level)
                return False
            self._pump(0.02)
        return False

    def _inspect_level(self, level: str) -> None:
        client = self.client
        tiles = list(getattr(client, "tiles", []))
        links = list(getattr(client, "links", {}).get(level, []))
        signs = dict(getattr(client, "signs", {}).get(level, {}))
        npcs = [npc for npc in getattr(client, "npcs", {}).values()
                if (not isinstance(npc, dict) or not npc.get("_level")
                    or npc.get("_level") == level)]
        baddies = list(getattr(client, "baddies", {}).values())
        chests = getattr(client, "chests_in_level", lambda _level: {})(level)
        entry = {"name": level, "board_parsed": bool(tiles),
                 "tiles_valid": len(tiles) == 4096 and all(isinstance(x, int) for x in tiles),
                 "sign_count": len(signs), "signs_decoded": all(isinstance(x, str) for x in signs.values()),
                 "link_count": len(links), "npc_count": len(npcs),
                 "npc_props_parsed": all(isinstance(x, dict) for x in npcs),
                 "baddy_count": len(baddies), "chest_count": len(chests)}
        self.result["levels_visited"].append(entry)
        if not entry["tiles_valid"]:
            self._error("level_board", f"invalid tile board ({len(tiles)} tiles)",
                        level=level)
        if not entry["signs_decoded"]:
            self._error("sign_decode", "one or more signs were not decoded",
                        level=level)
        if not entry["npc_props_parsed"]:
            self._error("npc_props", "one or more NPC property sets were malformed",
                        level=level)
        counts = self.result["counts"]
        counts["levels"] += 1
        for singular, value in (("signs", signs), ("links", links), ("npcs", npcs),
                                ("baddies", baddies), ("chests", chests)):
            counts[singular] += len(value)
        self._collect_assets(npcs)
        self._parse_gs1(level, npcs)
        self._soak_level(level, entry)

    def _collect_assets(self, npcs: list[dict]) -> None:
        values: list[Any] = []
        values.extend(npcs)
        values.extend(getattr(self.client, "players", {}).values())
        values.extend(getattr(self.client, "weapons", {}).values())
        for props in values:
            for key in ("gani", "ani", "animation"):
                name = props.get(key) if isinstance(props, dict) else None
                if name:
                    filename = str(name).split(",", 1)[0].strip()
                    while filename.lower().endswith(".gani.gani"):
                        filename = filename[:-5]
                    if not filename.lower().endswith(".gani"):
                        filename += ".gani"
                    self._assets.add(filename)

    def _parse_gs1(self, level: str, npcs: list[dict]) -> None:
        from reborn_protocol.gs1.parser import parse
        for npc in npcs:
            if not isinstance(npc, dict):
                continue
            script = npc.get("script")
            if not script:
                continue
            source = (script.decode("latin-1", errors="replace")
                      if isinstance(script, bytes) else str(script))
            first = source.splitlines()[0][:160] if source else ""
            start = 0
            try:
                parse(source)
                self.result["gs1_parse"]["ok"] += 1
            except BaseException as exc:
                self.result["gs1_parse"]["failed"] += 1
                offset = getattr(exc, "pos", 0)
                start = max(0, offset - 60)
                self._error("gs1_parse", exc, level=level, asset=first,
                            context=source[start:start + 120])
                continue
            try:
                report = run_gs1_bounded(source)
                bucket = "capped" if report["capped"] else "ran"
                self.result["gs1_exec"][bucket] += 1
                self._merge_host_coverage("gs1_exec", report)
            except BaseException as exc:
                bucket = "capped" if "budget exceeded" in str(exc).lower() else "failed"
                self.result["gs1_exec"][bucket] += 1
                self._error("gs1_exec", exc, level=level, asset=first,
                            context=source[start:start + 120])

    def _soak_level(self, level: str, entry: dict[str, Any]) -> None:
        simulated = 0.0
        next_frame = 0.0
        frames = 0
        exceptions: list[str] = []
        started = self.clock()
        while simulated + 1e-9 < self.soak_seconds:
            if (self.clock() >= self.deadline or
                    self.clock() - started >= self.soak_wall_seconds):
                exceptions.append("per-level soak wall cap exceeded")
                self._error("soak", "per-level soak wall cap exceeded", level=level)
                break
            try:
                self.ticker(self.client, level, self.soak_dt)
                if self._level().casefold() != level.casefold():
                    self._foreign_warp = True
                    exceptions.append(f"foreign warp to {self._level()}")
                    self._error("gmap_warp", "foreign warp during soak",
                                level=self._level(), context=f"expected {level}")
                    break
                simulated += self.soak_dt
                if simulated + 1e-9 >= next_frame:
                    self.renderer(self.client, level)
                    frames += 1
                    next_frame += self.soak_frame_interval
            except BaseException as exc:
                exceptions.append(f"{type(exc).__name__}: {exc}"[:1000])
                self._error("soak", exc, level=level)
                break
        entry["frames_rendered"] = frames
        entry["soak_exceptions"] = exceptions
        self.result["soak"]["frames"] += frames
        self.result["soak"]["errors"] += len(exceptions)
        self.result["render"]["ok" if not exceptions else "failed"] += 1

    def _parse_assets(self) -> None:
        downloaded = getattr(self.client, "_received_files", {})
        eligible = (name for name in downloaded
                    if str(name).lower().endswith((".gani", ".nw", ".gmap")))
        gmap_name = str(getattr(self.client, "gmap_name", ""))
        names = list(dict.fromkeys([*sorted(self._assets),
                                    *(x["name"] for x in self.result["levels_visited"]),
                                    *([gmap_name] if gmap_name else []),
                                    *sorted(eligible)]))[:MAX_FILES]
        for name in names:
            if self.clock() >= self.deadline:
                break
            try:
                if name not in downloaded and not self.client.request_file(name):
                    raise RuntimeError("file request was rejected")
                while (self.clock() < self.deadline and
                       getattr(self.client, "is_file_pending", lambda _n: False)(name)):
                    self._pump(0.1)
                data = self.client.get_file(name)
                if data is None:
                    raise FileNotFoundError(name)
                if name.lower().endswith(".gani"):
                    parser = GaniParser([])
                    parser.parse_content(data.decode("latin-1"), Path(name).stem)
                elif name.lower().endswith(".nw"):
                    parse_nw(data)
                elif name.lower().endswith(".gmap"):
                    width, height, _segments = parse_gmap(data)
                    self.result["gmap"]["name"] = name
                    self.result["gmap"]["grid_size"] = [width, height]
                self.result["files_parsed"]["ok"] += 1
            except BaseException as exc:
                self.result["files_parsed"]["failed"] += 1
                self._error("asset_parse", exc, level=self._level(), asset=name)

    def _run_bytecodes(self) -> None:
        for kind, scripts in getattr(self.client, "gs2_bytecode", {}).items():
            for key, blob in scripts.items():
                identity = (str(kind), str(key))
                if identity in self._bytecodes_seen:
                    continue
                self._bytecodes_seen.add(identity)
                try:
                    report = run_gs2_bounded(blob, f"{kind}:{key}")
                    bucket = "capped" if report["capped"] else "ran"
                    self.result["gs2"][bucket] += 1
                    self._merge_host_coverage("gs2", report)
                    self.result["gs2"]["events_found"] += len(report["events"])
                    self.result["gs2"]["events_ran"] += (
                        len(report["events"]) - len(report["event_failures"]))
                    self.result["gs2"]["events_failed"] += len(report["event_failures"])
                    event_names = set(self.result["gs2"]["event_names"])
                    event_names.update(report["events"])
                    self.result["gs2"]["event_names"] = sorted(event_names)
                except BaseException as exc:
                    self.result["gs2"]["failed"] += 1
                    match = re.search(r"offset (\d+)", str(exc))
                    offset = int(match.group(1)) if match else 0
                    start = max(0, offset - 16)
                    context = blob[start:start + 32].hex(" ")
                    self._error("gs2", exc, level=self._level(), asset=f"{kind}:{key}",
                                context=context)

    def _merge_host_coverage(self, section: str, report: dict[str, Any]) -> None:
        target = self.result[section]
        target["implemented_count"] += report["implemented_count"]
        for key in ("true_gaps", "known_unsupported"):
            target[key] = sorted(set(target[key]) | set(report[key]),
                                 key=str.casefold)

    @staticmethod
    def _tick_frame(client: Any, level: str, dt: float) -> None:
        game = DeepCrawler._render_game(client)
        game._frame_dt = min(dt, 0.1)
        client.update(timeout=0)
        game._update_visual_position(game._frame_dt)
        game._update_animations(game._frame_dt)
        game._last_dt = game._frame_dt

    @staticmethod
    def _render_game(client: Any):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from pyreborn.pygame_game import GameClient
        game = getattr(client, "_crawl_render_game", None)
        if game is None:
            game = GameClient(client)
            # Bytecode and received NPC scripts are exercised only by recording hosts.
            client.on_gs2_bytecode = None
            client._crawl_render_game = game
        return game

    @staticmethod
    def _render_frame(client: Any, level: str) -> None:
        game = DeepCrawler._render_game(client)
        if game.minimap_data:
            game._build_minimap_surface()
        game._render()


def crawl_client(client: Any, max_levels: int = 15, timeout: float = 120.0,
                 **kwargs) -> dict[str, Any]:
    return DeepCrawler(client, max_levels=max_levels, timeout=timeout, **kwargs).crawl()
