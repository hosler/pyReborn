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
from typing import Any, Callable, Iterable

from pyreborn.gani import GaniParser


MAX_FILES = 40
MAX_GS1_OPS = 50_000
MAX_GS1_SECONDS = 1.0
MAX_GS2_OPS = 200_000
MAX_GS2_SECONDS = 2.0
# Client-install scripts are pulled, not pushed (see _fetch_referenced_scripts).
MAX_GS2_FETCHES = 32
MAX_GS2_FETCH_ROUNDS = 3
MAX_GS2_FUNCTIONS = 128     # Zelda's gui_builder class alone exports 65
# Cooperative sleeps to let ONE entry point run before abandoning it. Content
# main loops are `while (true) { ...; sleep(0.05); }`; run as a plain call the
# sleep is inert and the loop burns the whole op budget. ~14 ops/iteration, so
# 64 sees the repeating cycle several times over. Arbitrary; raise if needed.
MAX_GS2_YIELDS = 64
GS2_FETCH_SECONDS = 3.0
MAX_VM_WARNINGS = 20
# One gmap seam gets its own wall budget and its own stall detector, so a
# segment the server will not hand over costs one skip instead of the whole
# crawl's time budget; after this many CONSECUTIVE failures (a segment that
# does get crawled resets the count) the grid traversal gives up -- and says
# so -- rather than thrashing a live server.
GMAP_SEAM_SECONDS = 5.0
GMAP_SEAM_STALL_STEPS = 40
MAX_GMAP_SEAM_FAILURES = 5
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
    everything. Only the misleading stderr line is suppressed, so surviving
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
        "gmap": {"name": "", "grid_size": [0, 0], "segments_visited": 0,
                 "segments_skipped": []},
        "soak": {"frames": 0, "errors": 0},
        "gs2": {"ran": 0, "failed": 0, "capped": 0, "fetched": 0,
                "events_found": 0, "events_ran": 0, "events_failed": 0,
                "functions_ran": 0, "functions_failed": 0,
                "event_names": [], "implemented_count": 0,
                "true_gaps": [], "known_unsupported": [], "stubbed": [],
                "unknown_opcodes": [], "vm_errors": 0,
                "fetch_missing": [], "scripts": []},
        "gs1_parse": {"ok": 0, "failed": 0},
        "gs1_exec": {"ran": 0, "failed": 0, "capped": 0,
                     "implemented_count": 0, "true_gaps": [],
                     "known_unsupported": [], "stubbed": []},
        "render": {"ok": 0, "failed": 0},
        "errors": [],
    }


class _WarningCapture(logging.Handler):
    """Keep the VM warnings that survive _ResolvedCallFilter, for the record.

    The catalog previously counted failures but named none, so a crawl could
    not tell the engine owners WHICH script warned about WHAT."""

    def __init__(self, limit: int = MAX_VM_WARNINGS) -> None:
        super().__init__(level=logging.WARNING)
        self.limit = limit
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.messages) < self.limit:
            self.messages.append(record.getMessage()[:300])


class RecordingHost:
    """Inert GS2 host which records calls the VM cannot implement itself.

    One host per script by default. A CrawlSession hands the SAME host to
    every script a server serves, which is what makes cross-script calls
    resolve instead of being recorded as engine gaps."""

    # Calls whose first argument names another script the server serves only
    # on request: findweapon() -> PLI_UPDATESCRIPT, join() -> PLI_UPDATECLASS.
    SCRIPT_REFERENCES = {"findweapon": "weapon", "join": "class"}

    def __init__(self, session: "CrawlSession | None" = None) -> None:
        from reborn_protocol.gs2.vm import GS2Host
        self._base = GS2Host()
        self.session = session
        self.calls: Counter[str] = Counter()
        self.globals: dict[str, Any] = {}
        self.script_refs: dict[str, set[str]] = {"weapon": set(), "class": set()}

    def call_builtin(self, vm, name, args, obj=None):
        from reborn_protocol.gs2.values import to_str
        from reborn_protocol.gs2.vm import NOT_HANDLED
        self.calls[str(name)] += 1
        kind = self.SCRIPT_REFERENCES.get(str(name).casefold())
        if kind and args:
            try:
                referenced = to_str(args[0]).strip()
            except BaseException:
                referenced = ""
            if referenced:
                self.script_refs[kind].add(referenced)
        return NOT_HANDLED

    def get_object(self, name):
        # The live host resolves a weapon NAME to that weapon's script
        # object (gs2_client.GS2ClientHost.get_object), which is how
        # `("-Player/Movement").HurtPlayer(...)` reaches a public function
        # instead of the builtin dispatcher.
        return None if self.session is None else self.session.script_object(name)

    def create_object(self, classname, arg):
        from reborn_protocol.gs2.values import GS2Object
        return GS2Object(name=classname)

    def sleep(self, vm, seconds):
        return None

    def get_globals(self):
        return self.globals


#: cache for _recording_this's lazily built class (reborn_protocol is
#: imported on use throughout this module, never at import time)
_RECORDING_THIS: Any = None


def _recording_this(vm: Any, name: str):
    """A script's `this` inside a shared session: an unset member falls back
    to the owning VM's own functions.

    Exactly what the live client's gs2_client._ThisObject does, and the
    other half of resolving cross-script calls -- `plfunc.modifyclientr(..)`
    (Zelda's -Player/Movement calling into -Player/Functions, which
    published `plfunc = this` in onCreated) reads the member off a FOREIGN
    script's this-object, so the function lookup has to live there."""
    global _RECORDING_THIS
    if _RECORDING_THIS is None:
        from reborn_protocol.gs2.values import GS2Object

        class _RecordingThisObject(GS2Object):
            __slots__ = ("_vm",)

            def __init__(self, owner, obj_name):
                super().__init__(name=obj_name)
                self._vm = owner

            def get(self, key):
                value = super().get(key)
                if value is None and self._vm is not None:
                    return self._vm.script_function(key)
                return value

        _RECORDING_THIS = _RecordingThisObject
    return _RECORDING_THIS(vm, name)


class CrawlSession:
    """One shared host, globals dict and VM registry for a server's scripts.

    A server's scripts are one program: Zelda's -Player/Functions publishes
    `plfunc = this` from onCreated and -Player/Movement then calls
    plfunc.modifyclientr(...), plfunc.hit(...) and
    ("-Player/Movement").HurtPlayer(...) -- all of which the live client
    resolves through the shared globals dict and its weapon-name lookup.
    Running every blob against its own host reported all four as missing
    engine calls when each is the server's own code.

    The price is order dependence, which warm() removes for the shape that
    matters: every script's toplevel and onCreated run -- publishing their
    globals -- before any script is exercised."""

    def __init__(self) -> None:
        self.host = RecordingHost(session=self)
        self.vms: dict[tuple[str, str], Any] = {}
        self._by_name: dict[str, Any] = {}

    def vm_for(self, identity: tuple[str, str], blob: bytes):
        """The VM for one script, created (and registered by name) once."""
        vm = self.vms.get(identity)
        if vm is None:
            from reborn_protocol.gs2.vm import GS2VM
            kind, key = identity
            vm = GS2VM(blob, name=f"{kind}:{key}", host=self.host)
            vm.this = vm.thiso = _recording_this(vm, f"{kind}:{key}")
            self.vms[identity] = vm
            self._by_name.setdefault(str(key).casefold(), vm)
        return vm

    def script_object(self, name: Any):
        vm = self._by_name.get(str(name).casefold())
        return None if vm is None else vm.this

    def warm(self, identity: tuple[str, str], blob: bytes,
             max_ops: int = MAX_GS2_OPS,
             wall_seconds: float = MAX_GS2_SECONDS) -> None:
        """Load a script the way the client does -- toplevel, then onCreated
        -- so its globals exist before any other script runs."""
        vm = self.vm_for(identity, blob)
        vm.max_ops = max_ops

        def execute() -> None:
            vm.run_toplevel()
            if vm.has_function("onCreated"):
                vm.call("onCreated")

        _with_wall_alarm(wall_seconds, execute)


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


def other_gs2_functions(functions: Any, events: Iterable[str]) -> list[str]:
    """Return the non-event functions a corpus sweep should still call.

    Events alone leave most host calls unreached: a weapon's findweapon() /
    join() references live in helpers (-Player/Movement calls findweapon from
    DoSword, never from an on-event with an inert host), so the crawl saw
    neither the calls nor the scripts they name."""
    names = functions.keys() if isinstance(functions, dict) else functions
    skip = {str(event).casefold() for event in events}
    return sorted({str(name) for name in names
                   if str(name).casefold() not in skip}, key=str.casefold)


def run_gs2_bounded(blob: bytes, name: str = "script",
                    max_ops: int = MAX_GS2_OPS,
                    wall_seconds: float = MAX_GS2_SECONDS,
                    max_functions: int = MAX_GS2_FUNCTIONS,
                    session: "CrawlSession | None" = None,
                    max_yields: int = MAX_GS2_YIELDS) -> dict[str, Any]:
    """Parse and run bytecode with an inert host and strict operation budget.

    With a `session` the script shares one host, one globals dict and one VM
    registry with the rest of the server's scripts (see CrawlSession). The
    per-script figures below are then diffed off the shared counters so each
    report still describes only its own script."""
    from reborn_protocol.gs2.vm import GS2VM

    if session is None:
        host = RecordingHost()
        vm = GS2VM(blob, name=name, host=host)
    else:
        host = session.host
        kind, _, key = name.partition(":")
        vm = session.vm_for((kind, key) if key else ("weapon", kind), blob)
    before_calls = host.calls.copy()
    before_refs = {ref_kind: set(names)
                   for ref_kind, names in host.script_refs.items()}
    before_skipped = dict(GS2VM.ops_skipped)
    before_missing = dict(GS2VM.builtins_missing)
    started = time.monotonic()
    vm.max_ops = max_ops
    wall_capped = False
    events: list[str] = []
    event_failures: list[str] = []
    functions: list[str] = []
    function_failures: list[str] = []
    total_ops = 0
    total_errors = 0
    op_capped = False
    cooperative: list[str] = []

    def call_entry(entry: str, failures: list[str]) -> None:
        """Run one entry point the way the client's game loop does.

        iter_call + resume, rather than a plain call: a script that
        cooperatively sleeps then bounds itself by its yields instead of
        spinning the whole op budget with an inert sleep (see
        MAX_GS2_YIELDS). Hitting the yield budget is NOT `capped` -- an
        endless main loop is what the content is for -- so it is reported
        separately.
        """
        nonlocal total_ops, total_errors, op_capped
        generator = vm.iter_call(entry)
        yields = 0
        try:
            while yields < max_yields:
                try:
                    next(generator)
                except StopIteration:
                    break
                except Exception:
                    # _execute already swallows handler errors; anything
                    # escaping is counted through vm._errors below.
                    break
                yields += 1
            else:
                cooperative.append(entry)
        finally:
            generator.close()
        total_ops += vm._ops_used
        total_errors += vm._errors
        op_capped = op_capped or vm._ops_used >= max_ops
        if vm._errors:
            failures.append(entry)

    def execute() -> None:
        # vm._errors is reset per entry point, so accumulate as we go.
        nonlocal total_ops, total_errors, op_capped
        vm.run_toplevel()
        total_ops += vm._ops_used
        total_errors += vm._errors
        op_capped = op_capped or vm._ops_used >= max_ops
        table = getattr(vm, "functions", {})
        events.extend(enumerate_gs2_events(table))
        for event in events:
            call_entry(event, event_failures)
        # Helpers are called last and counted apart: out of context they are
        # a coverage sweep, not a claim that the content misbehaves.
        functions.extend(other_gs2_functions(table, events)[:max_functions])
        for function in functions:
            call_entry(function, function_failures)

    vm_logger = logging.getLogger("reborn_protocol.gs2.vm")
    resolved_filter = _ResolvedCallFilter(
        {item.casefold() for item in real_gs2_surface()})
    warnings = _WarningCapture()
    vm_logger.addFilter(resolved_filter)
    vm_logger.addHandler(warnings)
    try:
        wall_capped = _with_wall_alarm(wall_seconds, execute)
    finally:
        vm_logger.removeHandler(warnings)
        vm_logger.removeFilter(resolved_filter)
    elapsed = time.monotonic() - started
    capped = op_capped or wall_capped or elapsed >= wall_seconds
    skipped = sorted(op for op, count in GS2VM.ops_skipped.items()
                     if count > before_skipped.get(op, 0))
    missing = {call for call, count in GS2VM.builtins_missing.items()
               if count > before_missing.get(call, 0)}
    calls = host.calls - before_calls
    for call in missing:
        calls[call] = max(1, calls[call])
    return {"capped": capped, "steps": total_ops, "elapsed": elapsed,
            "cooperative": cooperative, "unknown_opcodes": skipped,
            **_classify_calls(calls, real_gs2_surface()),
            "events": events, "event_failures": event_failures,
            "functions": functions, "function_failures": function_failures,
            "vm_errors": total_errors,
            "warnings": warnings.messages,
            # only the names THIS script asked for (a shared host's set is
            # cumulative; the crawler unions them all anyway)
            "referenced_scripts": {
                ref_kind: sorted(names - before_refs.get(ref_kind, set()),
                                 key=str.casefold)
                for ref_kind, names in host.script_refs.items()}}


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
                 soak_wall_seconds: float = SOAK_WALL_SECONDS,
                 shared_host: bool = True) -> None:
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
        self._script_refs: dict[str, set[str]] = {"weapon": set(), "class": set()}
        self._scripts_requested: set[tuple[str, str]] = set()
        self._gmap_visited: set[tuple[int, int]] = set()
        self._foreign_warp = False
        # Default ON: a server's scripts call each other, and one host per
        # script reported every such call as an engine gap (see
        # CrawlSession). shared_host=False restores per-script isolation.
        self.session = CrawlSession() if shared_host else None

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
        """Breadth-first grid crawl, routing between work items over known seams.

        ONE unusable seam must not end the crawl. Every failed crossing is
        named in the record (a shaped error plus a per-segment skip reason),
        the traversal re-syncs to whichever segment the client actually sits
        in, and later work items are routed AROUND the seams that failed --
        each skipped segment gets one more attempt over a different route.
        The previous version returned a bare False from _cross_gmap_seam's
        post-warp level re-check and broke out of the whole loop: that is
        how Zelda's 100-segment gmap came back as 2 segments visited with an
        empty error list."""
        grid = dict(getattr(self.client, "gmap_grid", {}))
        origin = self._gmap_cell(start)
        if origin is None:
            self._error("gmap", "current segment is absent from the gmap grid", level=start)
            return
        skipped: list[dict[str, Any]] = []
        blocked: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        seen = {origin}
        retried: set[tuple[int, int]] = set()
        queue = deque([origin])
        current: tuple[int, int] | None = origin
        failures = 0
        while queue and len(self._gmap_visited) < self.max_levels and self.clock() < self.deadline:
            target = queue.popleft()
            route = self._grid_route(grid, current, target, blocked)
            if route is None:
                self._record_gmap_skip(skipped, target, grid.get(target, ""),
                                       "no unblocked route from the current segment")
                continue
            reason = ""
            for cell in route[1:]:
                phase, reason = self._cross_gmap_seam(current, cell, grid[cell])
                if reason:
                    blocked.add((current, cell))
                    self._error(phase, reason, level=self._level(),
                                context=f"{grid.get(current, '?')} -> {grid[cell]}")
                    break
                current = cell
            if not reason:
                level = self._level()
                if level.casefold() != str(grid[target]).casefold():
                    reason = (f"grid traversal ended in {level or '<none>'}, "
                              f"expected {grid[target]}")
                    self._error("gmap_warp", reason, level=level)
            if reason:
                failures += 1
                current = self._resync_gmap(skipped, target, grid, reason,
                                            retried, queue)
                if current is None or failures >= MAX_GMAP_SEAM_FAILURES:
                    if current is not None:
                        self._error("gmap", f"stopping grid traversal after "
                                    f"{failures} consecutive unusable seams",
                                    level=self._level())
                    break
                continue
            if target not in self._gmap_visited:
                failures = 0
                self._gmap_visited.add(target)
                self._inspect_level(self._level())
                if self._foreign_warp:
                    # the per-level soak was interrupted by a warp (already
                    # recorded there); carry on from wherever we landed
                    self._foreign_warp = False
                    current = self._resync_gmap(
                        skipped, target, grid, "foreign warp during the level soak",
                        retried, queue)
                    if current is None:
                        break
                    continue
                for dx, dy in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                    neighbour = (target[0] + dx, target[1] + dy)
                    if neighbour in grid and neighbour not in seen:
                        seen.add(neighbour)
                        queue.append(neighbour)
        if queue and self.clock() >= self.deadline:
            self._error("budget", "crawl time budget exhausted", level=self._level())
        self.result["gmap"] = {
            "name": str(getattr(self.client, "gmap_name", "")),
            "grid_size": [int(getattr(self.client, "gmap_width", 0)),
                          int(getattr(self.client, "gmap_height", 0))],
            "segments_visited": len(self._gmap_visited),
            "segments_skipped": skipped,
        }

    def _record_gmap_skip(self, skipped: list[dict[str, Any]],
                          cell: tuple[int, int], level: Any, reason: str) -> None:
        skipped.append({"cell": [int(cell[0]), int(cell[1])],
                        "level": str(level), "reason": reason[:200]})

    def _resync_gmap(self, skipped: list[dict[str, Any]], target: tuple[int, int],
                     grid: dict, reason: str, retried: set[tuple[int, int]],
                     queue: deque) -> tuple[int, int] | None:
        """Record a skipped segment and report where the client really is.

        Returns None when the client is no longer on the gmap at all, which
        is the one failure the grid traversal genuinely cannot continue past."""
        self._record_gmap_skip(skipped, target, grid.get(target, ""), reason)
        if target not in retried:
            # a walled seam does not mean the segment is unreachable: give it
            # one more go once the route can avoid the seam that failed
            retried.add(target)
            queue.append(target)
        cell = self._gmap_cell(self._level())
        if cell is None:
            self._error("gmap", "left the gmap grid; grid traversal cannot continue",
                        level=self._level())
        return cell

    @staticmethod
    def _grid_route(grid: dict, current: tuple[int, int], target: tuple[int, int],
                    blocked: set[tuple[tuple[int, int], tuple[int, int]]]
                    ) -> list[tuple[int, int]] | None:
        """Shortest 4-neighbour route across the grid, avoiding failed seams.

        Returns the cells to walk (including `current`), or None when no
        route survives. Replaces a walk over the BFS tree, which could only
        route along the edges the crawl had already used -- so a single
        failed seam left it with no way around and no way back."""
        if current == target:
            return [current]
        previous: dict[tuple[int, int], tuple[int, int] | None] = {current: None}
        queue = deque([current])
        while queue:
            cell = queue.popleft()
            for dx, dy in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                nxt = (cell[0] + dx, cell[1] + dy)
                if nxt in previous or nxt not in grid or (cell, nxt) in blocked:
                    continue
                previous[nxt] = cell
                if nxt == target:
                    route = deque([nxt])
                    step: tuple[int, int] | None = cell
                    while step is not None:
                        route.appendleft(step)
                        step = previous[step]
                    return list(route)
                queue.append(nxt)
        return None

    def _cross_gmap_seam(self, source: tuple[int, int], target: tuple[int, int],
                         expected_level: str) -> tuple[str, str]:
        """Walk across ONE gmap seam. Returns ("", "") on arrival, else the
        (error phase, reason) for the caller to record and route around.

        Every exit names itself. The post-warp level re-check used to end on
        a bare `return False`, and the loop had no budget of its own: a
        server that never handed us over spun until the crawl's own deadline
        and reported nothing."""
        dx, dy = target[0] - source[0], target[1] - source[1]
        if abs(dx) + abs(dy) != 1:
            raise ValueError("gmap seam target is not adjacent")
        source_level = str(getattr(self.client, "gmap_grid", {}).get(source, self._level()))
        boundary = ((target[0] * 64 + (0.25 if dx > 0 else 63.75)) if dx else
                    (target[1] * 64 + (0.25 if dy > 0 else 63.75)))
        axis = "x" if dx else "y"
        direction = dx or dy
        deadline = min(self.deadline, self.clock() + GMAP_SEAM_SECONDS)
        stalled = 0
        previous = None
        while self.clock() < deadline:
            level = self._level()
            if level.casefold() == expected_level.casefold():
                self._pump(0.2)
                settled = self._level()
                if settled.casefold() == expected_level.casefold():
                    return "", ""
                return ("gmap_warp",
                        f"entered {expected_level} but settled in "
                        f"{settled or '<none>'}")
            if level.casefold() != source_level.casefold():
                return ("gmap_warp",
                        f"foreign warp to {level or '<none>'} while crossing "
                        f"from {source_level} to {expected_level}")
            position = float(getattr(self.client, axis))
            if previous is not None and abs(position - previous) < 0.01:
                stalled += 1
                if stalled >= GMAP_SEAM_STALL_STEPS:
                    return ("gmap_seam",
                            f"stuck in {source_level} at {axis}={position:g} "
                            f"(seam at {boundary:g}); the segment never "
                            f"changed to {expected_level}")
            else:
                stalled = 0
            previous = position
            if (direction > 0 and position >= boundary) or (direction < 0 and position <= boundary):
                self._pump(0.05)      # past the seam: waiting on the handover
                continue
            if not self.client.move(dx, dy, step=0.5):
                return "gmap_move", "movement packet was rejected"
            self._pump(0.02)
        if self.clock() >= self.deadline:
            return "budget", "crawl time budget exhausted mid-seam"
        return ("gmap_seam",
                f"{GMAP_SEAM_SECONDS:g}s seam budget exhausted crossing from "
                f"{source_level} to {expected_level}")

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
        """Run every pushed script, then pull the ones the content asks for.

        Client-install weapons (findweapon) and script classes (join) are
        never pushed: the server announces them or leaves them to be named by
        the content, and only answers PLI_UPDATESCRIPT / PLI_UPDATECLASS,
        which is how a real install stays current (see gs2_client.fetch_weapon
        and join_class). On the Login servers those pulled scripts were the
        bulk of the real content, so a corpus crawl that ran only what arrived
        unprompted saw a fraction of the server's GS2."""
        self._run_available_bytecodes("pushed")
        for _ in range(MAX_GS2_FETCH_ROUNDS):
            if not self._fetch_referenced_scripts():
                break
            self._run_available_bytecodes("fetched")
        self.result["gs2"]["fetch_missing"] = sorted(
            (f"{kind}:{name}" for kind, name in self._scripts_requested
             if not self._have_bytecode(kind, name)), key=str.casefold)

    def _run_available_bytecodes(self, source: str) -> None:
        pending: list[tuple[tuple[str, str], bytes]] = []
        for kind, scripts in list(getattr(self.client, "gs2_bytecode", {}).items()):
            for key, blob in list(scripts.items()):
                identity = (str(kind), str(key))
                if identity in self._bytecodes_seen:
                    continue
                self._bytecodes_seen.add(identity)
                pending.append((identity, blob))
        if self.session is not None:
            # Load pass: every script publishes its globals before any of
            # them is exercised, so the recorded gaps do not depend on the
            # order the server happened to push its scripts in. A blob that
            # does not parse is left to the run pass below, which records it
            # with a full shaped error.
            for identity, blob in pending:
                try:
                    self.session.warm(identity, blob)
                except BaseException:
                    continue
        for (kind, key), blob in pending:
            identity = (kind, key)
            try:
                report = run_gs2_bounded(blob, f"{kind}:{key}",
                                         session=self.session)
                bucket = "capped" if report["capped"] else "ran"
                self.result["gs2"][bucket] += 1
                self._merge_host_coverage("gs2", report)
                self.result["gs2"]["events_found"] += len(report["events"])
                self.result["gs2"]["events_ran"] += (
                    len(report["events"]) - len(report["event_failures"]))
                self.result["gs2"]["events_failed"] += len(report["event_failures"])
                self.result["gs2"]["functions_ran"] += len(report["functions"])
                self.result["gs2"]["functions_failed"] += len(
                    report["function_failures"])
                event_names = set(self.result["gs2"]["event_names"])
                event_names.update(report["events"])
                self.result["gs2"]["event_names"] = sorted(event_names)
                self._record_script(identity, blob, source, report)
            except BaseException as exc:
                self.result["gs2"]["failed"] += 1
                match = re.search(r"offset (\d+)", str(exc))
                offset = int(match.group(1)) if match else 0
                start = max(0, offset - 16)
                context = blob[start:start + 32].hex(" ")
                self._error("gs2", exc, level=self._level(), asset=f"{kind}:{key}",
                            context=context)

    def _record_script(self, identity: tuple[str, str], blob: bytes, source: str,
                       report: dict[str, Any]) -> None:
        """Store the per-script detail the engine owners need to act on."""
        kind, key = identity
        referenced = report["referenced_scripts"]
        for ref_kind, names in referenced.items():
            self._script_refs.setdefault(ref_kind, set()).update(names)
        if source == "fetched":
            self.result["gs2"]["fetched"] += 1
        self.result["gs2"]["vm_errors"] += report["vm_errors"]
        self.result["gs2"]["unknown_opcodes"] = sorted(
            set(self.result["gs2"]["unknown_opcodes"]) | set(report["unknown_opcodes"]),
            key=str)
        self.result["gs2"]["scripts"].append({
            "kind": kind, "name": key, "source": source, "bytes": len(blob),
            "capped": report["capped"], "steps": report["steps"],
            "cooperative": report["cooperative"],
            "events": report["events"], "event_failures": report["event_failures"],
            "functions": report["functions"],
            "function_failures": report["function_failures"],
            "implemented_count": report["implemented_count"],
            "stubbed": report["stubbed"], "true_gaps": report["true_gaps"],
            "known_unsupported": report["known_unsupported"],
            "unknown_opcodes": report["unknown_opcodes"],
            "vm_errors": report["vm_errors"], "warnings": report["warnings"],
            "referenced_scripts": referenced,
        })

    def _have_bytecode(self, kind: str, name: str) -> bool:
        stored = getattr(self.client, "gs2_bytecode", {}).get(kind, {})
        return any(str(key).casefold() == name.casefold() for key in stored)

    def _collect_announced_scripts(self) -> None:
        """Queue header-only PLO_LOADSCRIPT announcements for fetching.

        The server announces every script it holds for us, sending bytecode
        only for the weapons. Classes arrive as a bare header plus CRC and are
        pulled when something join()s them (Zelda announces 11 that way)."""
        headers = dict(getattr(self.client, "gs2_script_headers", {}))
        for key, header in headers.items():
            if not isinstance(header, dict) or header.get("bytecode"):
                continue
            kind = str(header.get("type", ""))
            if kind in self._script_refs:
                self._script_refs[kind].add(str(header.get("name") or key))

    def _fetch_referenced_scripts(self) -> int:
        """Request referenced-but-absent scripts. Return how many went out."""
        self._collect_announced_scripts()
        requesters = {"weapon": getattr(self.client, "request_weapon_bytecode", None),
                      "class": getattr(self.client, "request_class_bytecode", None)}
        requested = 0
        for kind, names in self._script_refs.items():
            request = requesters.get(kind)
            for name in sorted(names, key=str.casefold):
                identity = (kind, name)
                if (request is None or identity in self._scripts_requested or
                        self._have_bytecode(kind, name)):
                    continue
                if (len(self._scripts_requested) >= MAX_GS2_FETCHES or
                        self.clock() >= self.deadline):
                    break
                self._scripts_requested.add(identity)
                try:
                    if request(name):
                        requested += 1
                except BaseException as exc:
                    self._error("gs2_fetch", exc, level=self._level(),
                                asset=f"{kind}:{name}")
        if requested:
            self._pump(GS2_FETCH_SECONDS)
        return requested

    def _merge_host_coverage(self, section: str, report: dict[str, Any]) -> None:
        target = self.result[section]
        target["implemented_count"] += report["implemented_count"]
        for key in ("true_gaps", "known_unsupported", "stubbed"):
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
