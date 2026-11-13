"""GameClient's frame pipeline: start() / step() / shutdown(), run() over them,
error containment in the production loop, and the guard that keeps the
game_tester harnesses on step() instead of their own copies of the frame.

Offline: a real GameClient over an unconnected Client, SDL dummy drivers."""

import ast
import inspect
import logging
import os
import sys
import textwrap
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn import pygame_game
from pyreborn.pygame_game import GameClient

REPO = Path(__file__).resolve().parents[2]
LOGGER = "pyreborn.pygame_game"


@pytest.fixture
def game(monkeypatch, tmp_path):
    # shutdown() saves the window size: keep it off the real prefs.json.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return GameClient(Client('127.0.0.1', 14900, version='6.037'))


@pytest.fixture
def no_pygame_quit(monkeypatch):
    """shutdown() quits pygame; the rest of the test session still needs it."""
    calls = []
    monkeypatch.setattr(pygame_game.pygame, "quit", lambda: calls.append(1))
    return calls


# What a frame runs every time, and what a simulation tick runs inside it
# (pyreborn/clock.py, timing-spec.md): events and network per frame, the
# simulation in fixed 50 ms ticks, then the interpolated render. The tick
# follows the reference's timer pass: the player's counters and object
# animation, then keyCheck and movement, then the scripts, then the script
# warp and the level links (TPlayer.cpp:7211-7379, timing-impl.md).
FRAME_SEQUENCE = ["_handle_events", "client.update"]
TICK_SEQUENCE = [
    "client.run_tick", "_load_new_npcs", "_update_death_state",
    "_update_animations", "_advance_combat_objects",
    "_handle_input", "_update_low_hearts_warning", "_process_self_shoots",
    "gs1.process_coroutines", "gs1.process_timeouts",
    "gs2.process_coroutines", "gs2.process_timeouts",
    "_process_pending_warp", "_check_scripted_link_warp",
    "gs1.advance_input_frame", "_check_level_change",
    "_update_swimming_state",
]
RENDER_SEQUENCE = ["_update_visual_position", "_render"]
OLD_RUN_SEQUENCE = FRAME_SEQUENCE + TICK_SEQUENCE + RENDER_SEQUENCE


def _record_phases(game):
    calls = []

    def spy(name):
        def run(*args, **kwargs):
            calls.append((name, args, kwargs, game._frame_dt))
        return run

    for name in OLD_RUN_SEQUENCE:
        owner, _, attr = name.rpartition(".")
        target = {"": game, "client": game.client,
                  "gs1": game.gs1, "gs2": game.gs2}[owner]
        setattr(target, attr, spy(name))
    return calls


def test_a_tick_frame_runs_frame_then_tick_then_render(game, monkeypatch):
    monkeypatch.setattr("time.monotonic", lambda: 1234.5)   # frame time
    calls = _record_phases(game)
    game.step(0.05)
    assert [c[0] for c in calls] == OLD_RUN_SEQUENCE
    by_name = {c[0]: c for c in calls}
    # The production loop's arguments: non-blocking update; the tick reads
    # simulation time, one tick in.
    sim = game.clock.sim_now()
    assert game.clock.tick == 1
    assert by_name["client.update"][2] == {"timeout": 0.0}
    assert by_name["_handle_input"][1] == (sim,)
    assert by_name["_update_death_state"][1] == (sim,)
    for name in ("gs1.process_coroutines", "gs1.process_timeouts",
                 "gs2.process_coroutines", "gs2.process_timeouts",
                 "_update_animations"):
        assert by_name[name][1] == (0.05,)
    assert by_name["_advance_combat_objects"][1] == (0.05, sim)
    assert by_name["_update_visual_position"][1] == (game.clock.alpha,)
    assert by_name["_render"][3] == 0.05


def test_a_frame_without_a_whole_tick_runs_no_simulation(game):
    calls = _record_phases(game)
    game.step(1 / 60)
    assert [c[0] for c in calls] == FRAME_SEQUENCE + RENDER_SEQUENCE
    game.step(1 / 60)
    game.step(1 / 60)               # the third 1/60 s frame completes a tick
    assert [c[0] for c in calls].count("_handle_input") == 1
    assert game.clock.tick == 1


def test_a_stall_runs_one_tick_and_drops_the_rest(game):
    calls = _record_phases(game)
    game.step(0.5)
    assert game._frame_dt == 0.1            # presentation dt is clamped
    assert game.clock.tick == 1             # one tick, never a catch-up
    assert game.clock.dropped_ticks == 9
    assert [c[0] for c in calls].count("gs1.process_timeouts") == 1
    assert {c[0]: c for c in calls}["gs1.process_timeouts"][1] == (0.05,)


def test_step_passes_net_timeout_and_posts_events(game):
    calls = _record_phases(game)
    seen = []
    del game._handle_events
    real_get = pygame.event.get

    def handle_events():
        seen.extend(e.type for e in real_get())
    game._handle_events = handle_events
    event = pygame.event.Event(pygame.USEREVENT, {})
    game.step(0.05, net_timeout=0.02, events=[event])
    assert pygame.USEREVENT in seen
    assert {c[0]: c for c in calls}["client.update"][2] == {"timeout": 0.02}


def test_step_respawn_resets_the_idle_animation(game):
    _record_phases(game)
    anims = []
    game.player_anim.set_animation = lambda name, d: anims.append(name)
    game.client.player.hearts = 0
    game.step(0.05)
    assert game._was_dead is True and anims == []
    game.client.player.hearts = 3
    game.step(0.05)
    assert game._was_dead is False and anims == ["idle"]


def test_start_is_the_one_time_setup_and_idempotent(game):
    calls = []
    for name in ("_update_swimming_state", "_load_npc_scripts",
                 "_trigger_playerenters"):
        setattr(game, name, (lambda n: lambda *a: calls.append(n))(name))
    game.npc_handler.update_npcs = lambda: calls.append("update_npcs")
    game.client.player.x, game.client.player.y = 12.0, 18.5
    before = game.clock.frame_now()
    game.start()
    assert calls == ["_update_swimming_state", "_load_npc_scripts",
                     "_trigger_playerenters", "update_npcs"]
    assert (game.visual_x, game.visual_y) == (12.0, 18.5)
    assert game.arrival.gs1_level == game.client._current_level_name
    assert game.arrival.visual_epoch == game.client._plain_level_change_epoch
    assert game.roster_ready_time >= before + 2.0
    game.start()
    assert len(calls) == 4


def _raise_in_render_pass(game, times):
    """Make the entity pass raise `times` times, then behave."""
    real = game._render_entities
    state = {"left": times}

    def entities(*args, **kwargs):
        if state["left"]:
            state["left"] -= 1
            raise RuntimeError("bad entity draw")
        return real(*args, **kwargs)
    game._render_entities = entities


def test_strict_step_propagates_and_drops_the_half_built_frame(game):
    _raise_in_render_pass(game, 1)
    with pytest.raises(RuntimeError, match="bad entity draw"):
        game.step(0.05)
    # The pass raised mid-frame; its open context must not survive.
    assert game._frame_ctx is None
    game.step(0.05)          # the next frame renders
    assert game._frame_ctx.in_frame


def test_production_step_contains_a_render_failure_and_logs_once(game, caplog):
    _raise_in_render_pass(game, 2)
    presented = []
    real_present = game.viewport.present
    game.viewport.present = lambda: (presented.append(1), real_present())
    caplog.set_level(logging.WARNING, logger=LOGGER)

    game.step(0.05, strict=False)
    game.step(0.05, strict=False)
    errors = [r for r in caplog.records if r.name == LOGGER]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR
    assert errors[0].exc_info and "bad entity draw" in str(errors[0].exc_info[1])
    ((phase, kind, where), count), = game.frame_errors.items()
    assert (phase, kind, count) == ("render", "RuntimeError", 2)
    assert where.split(":")[0].endswith("test_frame_pipeline.py")
    assert game._frame_ctx is None and presented == []

    game.step(0.05, strict=False)
    assert presented == [1]                 # the next frame renders
    assert game._frame_ctx.in_frame
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1


def test_production_step_contains_a_script_hook_and_the_frame_goes_on(game, caplog):
    calls = _record_phases(game)

    def broken(dt):
        raise ValueError("timeout handler blew up")
    game.gs1.process_timeouts = broken
    caplog.set_level(logging.WARNING, logger=LOGGER)
    for _ in range(3):
        game.step(0.05, strict=False)
    names = [c[0] for c in calls]
    # The other engine, the level detector and the render still ran each frame.
    for name in ("gs2.process_timeouts", "_check_level_change", "_render"):
        assert names.count(name) == 3
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1
    assert [(k[0], k[1], n) for k, n in game.frame_errors.items()] == [
        ("gs1", "ValueError", 3)]
    with pytest.raises(ValueError):
        game.step(0.05)


def test_contained_input_failure_before_the_queue_read_still_quits(game):

    def broken():
        raise RuntimeError("settings overlay build failed")
    game._ensure_rc_ui = broken
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    game.running = True
    game.step(0.05, strict=False)
    assert game.running is False


def test_quit_later_in_a_batch_survives_a_raising_handler(game):
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0,
                                         unicode="a", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.QUIT))

    def broken(event):
        raise RuntimeError("key handler blew up")
    game._gs2_gui_event = broken
    game.running = True
    game.step(0.05, strict=False)
    assert game.running is False


def test_repeats_are_rate_limited_but_counted(game, caplog):
    _record_phases(game)
    game._handle_events = lambda: (_ for _ in ()).throw(KeyError("x"))
    caplog.set_level(logging.WARNING, logger=LOGGER)
    for _ in range(12):
        game.step(0.05, strict=False)
    records = [r for r in caplog.records if r.name == LOGGER]
    assert [r.levelno for r in records] == [logging.ERROR, logging.WARNING]
    assert list(game.frame_errors.values()) == [12]


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_interrupt_propagates_through_a_contained_step(game, exc):
    _record_phases(game)

    def interrupted(dt):
        raise exc()
    game.gs2.process_timeouts = interrupted
    with pytest.raises(exc):
        game.step(0.05, strict=False)


def _connected_while(monkeypatch, predicate):
    monkeypatch.setattr(Client, "connected", property(lambda self: predicate()))


def test_run_shuts_down_when_the_loop_body_raises_keyboard_interrupt(
        game, monkeypatch, tmp_path, no_pygame_quit):
    _connected_while(monkeypatch, lambda: True)
    disconnects = []
    game.client.disconnect = lambda: disconnects.append(1)
    seen = []

    def step(dt, **kwargs):
        seen.append(kwargs)
        raise KeyboardInterrupt
    game.step = step
    with pytest.raises(KeyboardInterrupt):
        game.run()
    assert seen == [{"strict": False}]       # production containment
    assert disconnects == [1] and no_pygame_quit == [1]
    assert (tmp_path / "pyreborn" / "prefs.json").exists()
    game.shutdown()                           # idempotent
    assert disconnects == [1] and no_pygame_quit == [1]


def test_run_ends_and_shuts_down_when_the_connection_drops(
        game, monkeypatch, no_pygame_quit):
    frames = []
    _connected_while(monkeypatch, lambda: len(frames) < 3)
    disconnects = []
    game.client.disconnect = lambda: disconnects.append(1)
    game.step = lambda dt, **kw: frames.append(dt)
    game.frame_limiter = type("Limiter", (), {"tick": lambda self, fps: 0})()
    assert game.run() is None
    assert len(frames) == 3 and all(0 <= dt <= 1.0 for dt in frames)
    assert disconnects == [1] and no_pygame_quit == [1]


def test_shutdown_survives_a_failing_step(game, no_pygame_quit, caplog):
    rc = []
    game.rc_ui = type("RC", (), {"shutdown": lambda self: rc.append(1)})()

    def broken():
        raise OSError("socket already gone")
    game.client.disconnect = broken
    game.shutdown(remember_window=False)
    assert rc == [1] and no_pygame_quit == [1]


# --------------------------------------------------------------------------
# Guard: the harnesses drive step(); no copy of the frame may come back.
# --------------------------------------------------------------------------

def _self_calls(func):
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    names = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "self":
            names.add(node.func.attr)
        elif (isinstance(owner, ast.Attribute) and owner.attr in ("gs1", "gs2")
              and isinstance(owner.value, ast.Name) and owner.value.id == "self"):
            names.add(node.func.attr)
    return names


STEP_PHASES = (_self_calls(GameClient.step)
               | _self_calls(GameClient._simulation_tick)) - {"_frame_phase"}
START_ONLY = _self_calls(GameClient.start) - STEP_PHASES

# (file, function) pairs allowed to call several frame-phase methods, with why.
ALLOWED = {
    # The passive level crawler advances only presentation (packets, visual
    # position, animations) for its screenshots. It never starts the game,
    # and must not run input or scripts against the servers it crawls.
    ("game_tester/server_crawl.py", "_tick_frame"),
}


def _violations(source, filename):
    """Functions (and module-level code) that copy the frame or the startup:
    two or more distinct step() phases, or any start()-only step."""
    tree = ast.parse(source, filename)
    scopes = [("<module>", [n for n in tree.body
                            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                  ast.ClassDef))])]
    scopes += [(n.name, [n]) for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found = []
    for name, nodes in scopes:
        called = set()
        for root in nodes:
            for node in ast.walk(root):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in STEP_PHASES | START_ONLY):
                    called.add(node.func.attr)
        phases = called & STEP_PHASES
        if (len(phases) >= 2 or called & START_ONLY) and (filename, name) not in ALLOWED:
            found.append(f"{filename}:{name} calls {sorted(called)}")
    return found


def test_guard_sees_the_phases():
    assert {"_handle_events", "_render", "_check_level_change",
            "process_timeouts", "_update_death_state"} <= STEP_PHASES
    assert {"_load_npc_scripts", "_trigger_playerenters"} <= START_ONLY
    # Not vacuous: the deleted headless pump_frame copy would be caught.
    old_copy = textwrap.dedent("""
        def pump_frame(game, dt, now):
            game._handle_events()
            game._handle_input(now)
            game._render()
        def settle(game):
            game._load_npc_scripts()
    """)
    assert len(_violations(old_copy, "x.py")) == 2


def test_no_harness_copies_the_frame_or_the_startup():
    found = []
    for path in sorted((REPO / "game_tester").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        found += _violations(path.read_text(encoding="utf-8"), rel)
    assert found == [], ("call GameClient.start()/step() instead of copying "
                         "their phases:\n" + "\n".join(found))
