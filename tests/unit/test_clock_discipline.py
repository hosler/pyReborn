"""One clock, two named reads: nothing in pyreborn/ reads time except
pyreborn/clock.py, and every frame-time read is classified.

``Clock.sim_now()`` is simulation time: it advances only when a 50 ms tick runs
and is what every timer that affects state or packets reads. ``frame_now()``
(and ``frame_now_ms()``) is monotonic real time, allowed only for
presentation and for real-world waits; FRAME_READS lists every function that
reads it, how many times, and why. A new frame-time read fails here until it
is classified, and so does an extra read inside an already listed function.

Direct time reads outside clock.py fail too: a call OR a reference
(``f = time.time``, ``default=time.monotonic``) to the time module's clocks,
``datetime.now/utcnow/today``, pygame's ``get_ticks``/``get_time``/
``get_rawtime``, and constructing a ``pygame.time.Clock``, except the counted
DIRECT_READS entries.
"""
import ast
from collections import Counter
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "pyreborn"

FORBIDDEN_TIME = {"time", "monotonic", "sleep", "perf_counter", "process_time",
                  "time_ns", "monotonic_ns", "perf_counter_ns",
                  "process_time_ns", "thread_time", "thread_time_ns"}
FORBIDDEN_DATETIME = {"now", "utcnow", "today"}
FORBIDDEN_PYGAME = {"get_ticks", "get_time", "get_rawtime"}

PRESENTATION = "presentation"
REAL_WAIT = "real-time wait"

#: (file relative to pyreborn/, function, reads, class, why). Every
#: frame_now()/frame_now_ms() read. Simulation reads use sim_now() and are
#: not listed.
FRAME_READS = {
    ("client.py", "_login_wait", 3, REAL_WAIT, "login response timeout"),
    ("client.py", "update", 3, REAL_WAIT,
     "the packet wait and the headless tick pump measure real time"),
    ("client_actions.py", "_note_server_warp_blocked", 1, REAL_WAIT,
     "rate of the blocked-server-warp notice (UI, not simulation)"),
    ("client_actions.py", "note_server_warp_declined", 1, REAL_WAIT,
     "decline cooldown of the consent prompt (UI policy)"),
    ("client_actions.py", "send_server_warp", 1, REAL_WAIT,
     "minimum interval between server-warp requests (UI policy)"),
    ("client_actions.py", "server_warp_allowed", 1, REAL_WAIT,
     "decline cooldown of the consent prompt (UI policy)"),
    ("client_files.py", "request_update_package", 1, REAL_WAIT,
     "download stall stamp"),
    ("client_warp.py", "consume_warp_echo", 1, REAL_WAIT,
     "age of a sent warp's server echo (network round trip)"),
    ("client_warp.py", "note_client_warp", 1, REAL_WAIT,
     "stamp of a sent warp for its echo (network round trip)"),
    ("client_warp.py", "warp_to_level", 1, PRESENTATION,
     "start of the held transition frame"),
    ("game/callbacks/client_callbacks.py", "on_add_player", 1, PRESENTATION,
     "join announcements after the login roster dump"),
    ("game/callbacks/client_callbacks.py", "on_hurt", 2, PRESENTATION,
     "damage number float and hurt flash"),
    ("game/gs2_gui/manager.py", "now_ms", 1, PRESENTATION,
     "GUI animation and double-click timing"),
    ("game/hud.py", "_draw_server_warp_prompt", 1, PRESENTATION,
     "prompt arm indicator"),
    ("game/input.py", "_handle_server_warp_key", 1, PRESENTATION,
     "prompt arming delay (per-frame UI input)"),
    ("game/input.py", "offer_server_warp", 1, PRESENTATION,
     "prompt opened stamp"),
    ("game/input.py", "show_hud_notice", 1, PRESENTATION, "HUD notice expiry"),
    ("game/overlays.py", "draw", 1, PRESENTATION, "HUD notice expiry"),
    ("game/render.py", "_render", 3, PRESENTATION,
     "held-transition and slide timing"),
    ("game/render.py", "_sync_camera", 1, PRESENTATION, "camera shake easing"),
    ("game/render_effects.py", "_expire_leaf_particles", 1, PRESENTATION,
     "leaf particles (never affect state)"),
    ("game/render_effects.py", "_render_break_effects", 1, PRESENTATION,
     "break burst animation"),
    ("game/render_effects.py", "_render_combat_presentation", 1, PRESENTATION,
     "hurt vignette and death/respawn fades"),
    ("game/render_effects.py", "_render_damage_numbers", 1, PRESENTATION,
     "damage number float"),
    ("game/render_effects.py", "_render_leaf_particles", 1, PRESENTATION,
     "leaf particles"),
    ("game/render_effects.py", "_render_leaps", 1, PRESENTATION,
     "debris leap animation"),
    ("game/render_effects.py", "_render_water_ripples", 1, PRESENTATION,
     "water ripples"),
    ("game/render_effects.py", "_spawn_break_effect", 1, PRESENTATION,
     "break burst stamp"),
    ("game/render_effects.py", "_spawn_hit_break_effect", 1, PRESENTATION,
     "break burst stamp"),
    ("game/render_effects.py", "_spawn_leaf_particles", 1, PRESENTATION,
     "leaf particle stamp"),
    ("game/render_effects.py", "_spawn_leaps", 1, PRESENTATION,
     "debris leap stamp"),
    ("game/render_effects.py", "_start_camera_shake", 1, PRESENTATION,
     "camera shake start"),
    ("game/render_entities.py", "_render_player", 1, PRESENTATION,
     "hurt blink alpha"),
    ("game/render_objects.py", "_render_chest_reveals", 1, PRESENTATION,
     "chest reveal rise"),
    ("game/render_world.py", "_shimmer_ramp_step", 1, PRESENTATION,
     "water shimmer"),
    ("game/setup.py", "_check_level_change", 1, REAL_WAIT,
     "waiting for a new level's NPCs to stream in"),
    ("game/setup.py", "_update_low_hearts_warning", 1, PRESENTATION,
     "low-hearts beep interval"),
    ("gs2_client/host_objects.py", "sleep", 5, REAL_WAIT,
     "blocking sleep() outside a coroutine pumps the network in real time"),
    ("gs2_client/runtime.py", "__init__", 1, REAL_WAIT,
     "class join download deadline"),
    ("gs2_client/runtime.py", "_expire_listed_joins", 1, REAL_WAIT,
     "class join download deadline"),
    ("gs2_client/runtime.py", "_join_listed_classes", 1, REAL_WAIT,
     "class join download deadline"),
    ("gs2_client/runtime.py", "fetch_weapon", 2, REAL_WAIT,
     "findweapon download wait"),
    ("gs2_client/runtime.py", "ready", 1, REAL_WAIT,
     "class join download deadline"),
    ("inventory_ui.py", "handle_click", 1, PRESENTATION, "double-click"),
    ("nc_link.py", "_await_nc_proof", 2, REAL_WAIT, "NC login proof timeout"),
    ("nc_link.py", "pump_correlated_requests", 1, REAL_WAIT,
     "NC request timeout"),
    ("pygame_game.py", "run", 2, REAL_WAIT,
     "the frame dt the tick accumulator is fed"),
    ("pygame_game.py", "start", 1, PRESENTATION,
     "join announcements after the login roster dump"),
    ("rc_link.py", "_await_rc_proof", 2, REAL_WAIT, "RC login proof timeout"),
    ("sounds.py", "_remember_pending", 1, REAL_WAIT,
     "pending sound download age"),
    ("sounds.py", "load_bytes", 1, REAL_WAIT, "pending sound download age"),
    ("sprites.py", "_display_sheet", 1, PRESENTATION,
     "animated image (not gani) frames"),
    ("update_packages.py", "expire_stalled", 1, REAL_WAIT,
     "download stall timeout"),
    ("update_packages.py", "file_chunk", 1, REAL_WAIT, "download stall stamp"),
    ("update_packages.py", "handle_package_size", 1, REAL_WAIT,
     "download stall stamp"),
}

#: (file, function, reads, why): direct time reads that stay.
DIRECT_READS = {
    ("game/ui.py", "_draw", 1,
     "TextInput caret blink phase: a widget draw with no clock path"),
    ("game/gs2_gui/text_controls.py", "_draw_self", 1,
     "GS2 text-edit caret blink phase: a widget draw with no clock path"),
    ("game/gs2_gui/collection_controls.py", "_draw_self", 1,
     "GS2 textlist row flicker phase: a widget draw with no clock path"),
    ("game/gs2_gui/manager.py", "_ticks", 1,
     "fallback for a GUI manager with no owning runtime; "
     "GS2GuiManager.now_ms reads the client clock first"),
    ("pygame_game.py", "__init__", 1,
     "pygame.time.Clock frame limiter: display pacing only"),
    ("pygame_screens.py", "__init__", 1,
     "login/server-list screens' pygame.time.Clock: display pacing only"),
}


def _modules():
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        yield rel, ast.parse(path.read_text(), filename=str(path))


def _walk(tree):
    """Yield (node, enclosing function name) for every node."""
    def walk(node, current):
        for child in ast.iter_child_nodes(node):
            nxt = child.name if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            yield child, current
            yield from walk(child, nxt)
    yield from walk(tree, "<module>")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _direct_reads(rel, tree):
    """Counter of (rel, function) -> direct time reads, and what they are."""
    time_aliases, datetime_aliases = {"time"}, {"datetime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "time":
                    time_aliases.add(item.asname or "time")
                if item.name == "datetime":
                    datetime_aliases.add(item.asname or "datetime")
    found = Counter()
    what = {}
    for node, func in _walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted(node)
        if dotted is None:
            dotted = ""
        head = dotted.split(".")[0] if dotted else ""
        hit = None
        if head in time_aliases and node.attr in FORBIDDEN_TIME and \
                dotted.count(".") == 1:
            hit = dotted
        elif head in datetime_aliases and node.attr in FORBIDDEN_DATETIME:
            hit = dotted
        elif node.attr in FORBIDDEN_PYGAME:
            hit = dotted or node.attr
        elif dotted.endswith("time.Clock") and dotted.startswith("pygame"):
            hit = dotted
        if hit:
            found[(rel, func)] += 1
            what.setdefault((rel, func), []).append(f"{node.lineno}:{hit}")
    return found, what


def test_no_direct_time_reads_outside_the_clock():
    allowed = {(f, fn): n for f, fn, n, _ in DIRECT_READS}
    seen, offenders = set(), []
    for rel, tree in _modules():
        if rel == "clock.py":
            continue
        found, what = _direct_reads(rel, tree)
        for key, count in found.items():
            seen.add(key)
            if count != allowed.get(key, 0):
                offenders.append(f"{key[0]} {key[1]}(): {count} direct reads "
                                 f"(allowed {allowed.get(key, 0)}) {what[key]}")
    assert not offenders, (
        "read time through client.clock (sim_now()/frame_now()), not "
        "directly; or add a DIRECT_READS entry with a reason:\n"
        + "\n".join(offenders))
    stale = sorted(set(allowed) - seen)
    assert not stale, f"DIRECT_READS entries that match nothing any more: {stale}"


def _frame_reads():
    found = Counter()
    for rel, tree in _modules():
        if rel == "clock.py":
            continue
        for node, func in _walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                    "frame_now", "frame_now_ms"):
                found[(rel, func)] += 1
    return found


def test_every_frame_time_read_is_classified():
    """A frame_now() site is presentation or a real-world wait, never
    simulation; an unlisted one, or one more in a listed function, fails."""
    allowed = {(f, fn): n for f, fn, n, _, _ in FRAME_READS}
    found = _frame_reads()
    wrong = [f"{rel} {fn}(): {n} frame_now reads (classified {allowed.get((rel, fn), 0)})"
             for (rel, fn), n in sorted(found.items())
             if allowed.get((rel, fn)) != n]
    assert not wrong, (
        "classify each frame_now() read in FRAME_READS (presentation or "
        "real-time wait); simulation reads sim_now():\n" + "\n".join(wrong))
    stale = sorted(set(allowed) - set(found))
    assert not stale, f"FRAME_READS entries that match nothing any more: {stale}"


def test_classification_entries_state_a_class_and_a_reason():
    for entry in FRAME_READS:
        assert len(entry) == 5 and entry[3] in (PRESENTATION, REAL_WAIT)
        assert entry[4].strip() and entry[2] > 0
    for entry in DIRECT_READS:
        assert len(entry) == 4 and entry[3].strip() and entry[2] > 0


def test_the_clock_has_no_unnamed_read():
    """now()/now_ms() are gone: a read says which time it is."""
    from pyreborn.clock import Clock
    assert not hasattr(Clock, "now") and not hasattr(Clock, "now_ms")
    offenders = [f"{rel} {func}()" for rel, tree in _modules()
                 for node, func in _walk(tree)
                 if isinstance(node, ast.Attribute) and node.attr in ("now", "now_ms")
                 and isinstance(node.value, ast.Attribute)
                 and "clock" in node.value.attr.lower()]
    assert not offenders, offenders


def test_the_scanner_is_not_blind():
    """Non-call references, datetime, perf_counter, pygame Clock and a second
    read in one function are all caught."""
    source = (
        "import time, datetime, pygame\n"
        "def f(read=time.monotonic):\n"
        "    a = time.perf_counter\n"
        "    b = datetime.datetime.now()\n"
        "    c = pygame.time.Clock()\n"
        "    d = pygame.time.get_ticks() + pygame.time.get_ticks()\n")
    found, _ = _direct_reads("x.py", ast.parse(source))
    assert found[("x.py", "f")] == 6      # the default argument counts too


def test_no_from_time_import():
    offenders = []
    for rel, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ("time", "datetime"):
                names = {a.name for a in node.names}
                if node.module == "time" or names & {"datetime", "date"}:
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, "from time/datetime import ...: " + ", ".join(offenders)


# == simulation time against a duration: only through Clock.passed ==========
#
# sim_now() is SIM_ORIGIN + tick * 0.05, a float: `now - stamp > 0.3` is 6
# ticks from some start ticks and 7 from others. Every comparison of
# simulation time with a duration or a deadline goes through
# clock.passed(stamp, seconds), which is exact in ticks. The scanner flags an
# ordering comparison (<, <=, >, >=) whose operands involve sim_now(), a name
# assigned from it in the same function, or a parameter that carries a
# sim_now() reading in (SIM_PARAMETERS).

ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)

#: (file relative to pyreborn/, function, parameter): a parameter whose
#: callers pass a sim_now() reading.
SIM_PARAMETERS = {
    ("game/input.py", "_handle_input", "current_time"),
    ("game/input.py", "_update_death_state", "current_time"),
    ("game/input.py", "_revive_on_input", "current_time"),
    ("pygame_game.py", "_advance_combat_objects", "now"),
    ("hurt.py", "immune", "now"),
    ("hurt.py", "input_locked", "now"),
    ("hurt.py", "start", "now"),
    ("npc_script_display.py", "take_display", "now"),
    ("ground_items.py", "expire_items", "now"),
    ("client_combat.py", "_advance_arrow_sim", "now"),
    ("client_combat.py", "_explosion_cells", "now"),
    ("carrying.py", "bomb_sprite", "now"),
    ("sword.py", "due", "now"),
}


def _is_sim_read(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sim_now")


#: Calls whose result is still a time when an argument is one.
_TIME_PRESERVING = {"min", "max", "abs", "float", "getattr"}


def _mentions(node, names):
    """True when ``node`` evaluates to a simulation time (or a difference of
    two): a sim_now() read, a name holding one, arithmetic on one. A whole
    tick count (int()/floor() of one) or a container holding one is not."""
    if _is_sim_read(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.BinOp):
        return _mentions(node.left, names) or _mentions(node.right, names)
    if isinstance(node, ast.UnaryOp):
        return _mentions(node.operand, names)
    if isinstance(node, ast.IfExp):
        return _mentions(node.body, names) or _mentions(node.orelse, names)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _TIME_PRESERVING:
        return any(_mentions(arg, names) for arg in node.args)
    return False


def _targets(node):
    """Plain names bound by an assignment (not attributes or items)."""
    targets = list(node.targets if isinstance(node, ast.Assign) else [node.target])
    while targets:
        target = targets.pop()
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, (ast.Tuple, ast.List)):
            targets.extend(target.elts)
        elif isinstance(target, ast.Starred):
            targets.append(target.value)


def _sim_comparisons(rel, tree):
    out = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {param for f, fn, param in SIM_PARAMETERS
                 if f == rel and fn == func.name}
        grew = True
        while grew:
            grew = False
            for node in ast.walk(func):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) \
                        and node.value is not None and _mentions(node.value, names):
                    new = set(_targets(node)) - names
                    if new:
                        names |= new
                        grew = True
        for node in ast.walk(func):
            if isinstance(node, ast.Compare) and any(
                    isinstance(op, ORDERING) for op in node.ops) and (
                    _mentions(node.left, names)
                    or any(_mentions(c, names) for c in node.comparators)):
                out.append(f"{rel}:{node.lineno} {func.name}()")
    return sorted(set(out))


def test_simulation_time_is_compared_only_through_clock_passed():
    offenders = [hit for rel, tree in _modules() if rel != "clock.py"
                 for hit in _sim_comparisons(rel, tree)]
    assert not offenders, (
        "compare simulation time with a duration through "
        "clock.passed(stamp, seconds):\n" + "\n".join(offenders))


def test_the_sim_comparison_scanner_is_not_blind():
    source = (
        "def f(self):\n"
        "    now = self.clock.sim_now()\n"
        "    left = self.until - now\n"
        "    a = now - self.last > 0.3\n"
        "    b = self.clock.sim_now() < self.until\n"
        "    c = left <= 0\n"
        "    d = self.clock.passed(self.last, 0.3)\n")
    assert len(_sim_comparisons("x.py", ast.parse(source))) == 3
