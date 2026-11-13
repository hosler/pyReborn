"""The fixed-tick timing model (pyreborn/clock.py; the reference client's
50 ms tick, scratchpad/pygame-framework-1111/timing-spec.md).

Tick policy, mechanics counted in ticks, script timers on the tick clock,
input latching between ticks, one position packet per tick, a session
whose simulation and packets are identical at 30, 60 and 144 frames a second,
and the script-set frame tick (adventure_setframetick, TTime.cpp:23-26) with
its script-clock rule (TScriptUniverse.cpp:226-231).
"""
from collections import defaultdict

import pygame
import pytest
from reborn_protocol.gs2.compiler import Gs2Compiler

import offline_game
from offline_game import _running, key_event
from pyreborn.clock import Clock
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2
from pyreborn.packets import PacketID
from pyreborn.throwing import make_throw

TICK = Clock.tick_length
X2 = 78 + 32
SPRITE = 17 + 32


# == tick policy =============================================================

def test_accumulator_arithmetic_and_alpha():
    clock = Clock(source=lambda: 0.0)
    assert clock.ticks_due(0.02) == 0
    assert clock.alpha == pytest.approx(0.4)
    assert clock.ticks_due(0.03) == 1          # 0.05 held: one tick
    assert clock.accumulator == pytest.approx(0.0, abs=1e-12)
    assert clock.ticks_due(0.07) == 1          # 0.02 left over, kept
    assert clock.alpha == pytest.approx(0.4)
    assert clock.dropped_ticks == 0


@pytest.mark.parametrize("fps", [30, 60, 120, 144])
def test_one_tick_per_tick_length_at_any_frame_rate(fps):
    clock = Clock(source=lambda: 0.0)
    ticks = sum(clock.ticks_due(1.0 / fps) for _ in range(10 * fps))
    assert abs(ticks - 200) <= 1
    assert clock.dropped_ticks == 0


@pytest.mark.parametrize("stall", [0.15, 5.0])
def test_a_stall_runs_one_tick_and_drops_the_rest(stall):
    clock = Clock(source=lambda: 0.0)
    assert clock.ticks_due(stall) == 1
    assert clock.accumulator == 0.0
    assert clock.dropped_ticks == int(round(stall / TICK)) - 1
    assert clock.ticks_due(0.0) == 0           # no backlog afterwards


def test_zero_and_negative_dt_are_safe():
    clock = Clock(source=lambda: 0.0)
    assert clock.ticks_due(0.0) == 0
    assert clock.ticks_due(-1.0) == 0
    assert clock.accumulator == 0.0 and clock.alpha == 0.0


def test_max_ticks_per_frame_is_honoured(monkeypatch):
    monkeypatch.setattr(Clock, "MAX_TICKS_PER_FRAME", 3)
    clock = Clock(source=lambda: 0.0)
    assert clock.ticks_due(0.15) == 3
    assert clock.ticks_due(0.5) == 3
    assert clock.dropped_ticks == 7 and clock.accumulator == 0.0


def test_sim_time_advances_only_with_ticks():
    clock = Clock(source=lambda: 123.0)
    start = clock.sim_now()
    clock.ticks_due(1.0)
    assert clock.sim_now() == start            # due is not done
    clock.begin_tick()
    assert clock.sim_now() == pytest.approx(start + TICK)


# == helpers =================================================================

def hold(monkeypatch, *keys):
    """Hold `keys` (pygame keycodes) down until the next call."""
    held = defaultdict(bool, {k: True for k in keys})
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: held)
    return held


def movement_packets(game, start=0):
    return [data for pid, data in game.client._protocol.sent[start:]
            if pid == PacketID.PLI_PLAYERPROPS and len(data) > 2
            and data[0] == SPRITE and data[2] == X2]


# == mechanics in ticks ========================================================

@pytest.mark.parametrize("key,axis,sign", [
    (pygame.K_RIGHT, 0, 1), (pygame.K_LEFT, 0, -1),
    (pygame.K_DOWN, 1, 1), (pygame.K_UP, 1, -1)])
def test_walking_n_ticks_moves_half_a_tile_per_tick(make_game, monkeypatch,
                                                    key, axis, sign):
    """TPlayer.cpp:807, :7436: 0.5 tile per tick."""
    game = make_game(player_xy=(30.0, 30.0))
    hold(monkeypatch, key)
    start = (game.client.x, game.client.y)
    game.ticks(8)
    moved = (game.client.x, game.client.y)[axis] - start[axis]
    assert moved == pytest.approx(sign * 8 * 0.5)


@pytest.mark.parametrize("fps", [30, 60, 144])
def test_walk_distance_is_independent_of_the_frame_rate(make_game,
                                                        monkeypatch, fps):
    game = make_game(player_xy=(20.0, 30.0))
    hold(monkeypatch, pygame.K_RIGHT)
    tick0, x0 = game.clock.tick, game.client.x
    game.frames(fps, dt=1.0 / fps)             # one second
    ticks = game.clock.tick - tick0
    assert abs(ticks - 20) <= 1
    assert game.client.x - x0 == pytest.approx(ticks * 0.5)


def test_arrow_flies_one_tile_per_tick(make_game):
    """TClient.cpp:3646: one tile per tick, until a wall."""
    game = make_game(arrows=[(40.0, 30.0, 1)])
    game.ticks(1)
    (arrow,) = game.active_projectiles
    xs = []
    for _ in range(5):
        xs.append(arrow["x"])
        game.ticks(1)
    assert [round(b - a, 6) for a, b in zip(xs, xs[1:])] == [-1.0] * 4


def test_a_throw_lands_on_its_ninth_tick(make_game):
    """TPlayer.cpp:7831: nine ticks of flight."""
    game = make_game()
    obj = make_throw(30.0, 30.0, 2, "bush", (4, 5, 6, 7))
    game.thrown_objects.append(obj)
    landed = None
    for tick in range(1, 15):
        game.ticks(1)
        if obj not in game.thrown_objects:
            landed = tick
            break
    assert landed == 9


def test_bomb_with_counter_n_explodes_on_tick_n_plus_one(make_client):
    """TServerLevel.cpp:1322: a wire counter N explodes after N + 1 ticks."""
    client = make_client()
    n = 20
    assert client.put_bomb(30.0, 30.0, consume_ammo=False,
                           timer_ms=(n + 1) * 50)
    exploded = []
    client.on_bomb_exploded = lambda record, cells: exploded.append(client.clock.tick)
    start = client.clock.tick
    for _ in range(n + 3):
        client.run_due_ticks(1)
    assert exploded == [start + n + 1]


def test_an_explosion_lasts_twelve_ticks(make_client):
    """TServerLevel.cpp:1606, TExplosion.cpp:101-102: counter 11..0."""
    client = make_client()
    client.make_explosion(30.0, 30.0, 1, 1, 0, False)
    seen = 1
    while client.active_explosions:
        client.run_due_ticks(1)
        seen += bool(client.active_explosions)
    assert seen == 12


def test_death_status_at_28_ticks_and_revival_input_at_30(make_game,
                                                          monkeypatch):
    """TPlayer.cpp:2706: DEAD after 28 ticks; :7319: input back at 30."""
    game = make_game(hearts=0.0)
    player = game.client.player
    hold(monkeypatch, pygame.K_RIGHT)          # a revival key, held all along
    game.ticks(1)                              # the tick that sees the death
    dead_at = revived_at = None
    for tick in range(1, 40):
        game.ticks(1)
        if dead_at is None and player.status & 0x08:
            dead_at = tick
        if player.hearts > 0:
            revived_at = tick
            break
    assert dead_at == 28
    assert revived_at == 30


def test_emoticon_clears_after_32_ticks(make_client):
    """TPlayer::showEmoticon sets 32 (TInitStatics.cpp:1011); the timer
    counts it down once per tick (TPlayer.cpp:7262-7287)."""
    client = make_client()
    client.player.show_emoticon("smile")
    client.run_due_ticks(31)
    assert client.player.emoticon == "smile"
    client.run_due_ticks(1)
    assert client.player.emoticon == ""


def test_items_expire_after_165_ticks(make_client):
    """putExtra starts at 164 and animateExtras deletes it below zero
    (ground_items.ITEM_LIFETIME_TICKS)."""
    client = make_client(items=[(20.0, 20.0, offline_game.ITEM_GREENRUPEE)])
    level = client.current_level_name
    assert client.items_in_level(level)
    client.run_due_ticks(164)
    assert client.items_in_level(level)
    client.run_due_ticks(1)
    assert not client.items_in_level(level)


# == scripts on the tick clock ===================================================

def _gs1(client, script):
    gs1 = ClientGS1(client)
    client.npcs[7001] = {"x": 30, "y": 30, "visible": True}
    gs1.load_script("timer", script, npc_id=7001)
    gs1.trigger_npc_event(7001, "playerenters")
    return gs1, gs1._progs["timer"]["scopes"]["this"]


def _gs1_tick(gs1):
    gs1.process_coroutines(TICK)
    gs1.process_timeouts(TICK)


@pytest.mark.parametrize("value,fires_on", [(0.05, 1), (0.1, 2), (0.15, 3),
                                            (0.01, 1)])
def test_gs1_timeout_fires_on_its_tick(make_client, value, fires_on):
    """TScriptSpace.cpp:1030-1047: fires once less than 0.0001 is left."""
    gs1, this = _gs1(make_client(),
                     f"if (playerenters) timeout = {value};\n"
                     "if (timeout) this.fired = this.fired + 1;")
    for tick in range(1, 5):
        _gs1_tick(gs1)
        if this.get("fired"):
            break
    assert tick == fires_on and this["fired"] == 1


def test_gs1_timeout_zero_cancels(make_client):
    gs1, this = _gs1(make_client(),
                     "if (playerenters) { timeout = 0.05; timeout = 0; }\n"
                     "if (timeout) this.fired = 1;")
    for _ in range(4):
        _gs1_tick(gs1)
    assert not this.get("fired")


@pytest.mark.parametrize("value,after", [(0.05, 1), (0.1, 2)])
def test_gs1_sleep_resumes_on_its_tick(make_client, value, after):
    """TScriptSpace.cpp:1062: sleep shares the script clock."""
    gs1, this = _gs1(make_client(),
                     f"if (playerenters) {{ sleep {value}; this.after = 1; }}")
    for tick in range(1, 5):
        _gs1_tick(gs1)
        if this.get("after"):
            break
    assert tick == after


needs_gs2 = pytest.mark.skipif(not Gs2Compiler().available,
                               reason="gs2test compiler binary not built")


def _gs2(body):
    rt = ClientGS2()
    vm = rt.load_bytecode("weapon", "timer", Gs2Compiler().compile(body))
    assert vm is not None
    return rt, vm


def _gs2_tick(rt):
    rt.process_coroutines(TICK)
    rt.process_timeouts(TICK)


def _first_tick(rt, check, limit=6):
    for tick in range(1, limit):
        _gs2_tick(rt)
        if check():
            return tick
    return None


@needs_gs2
@pytest.mark.parametrize("value,fires_on", [(0.05, 1), (0.1, 2), (0.01, 1)])
def test_gs2_settimer_fires_on_its_tick(value, fires_on):
    rt, vm = _gs2("function onCreated() { setTimer(%s); }\n"
                  "function onTimeout() { this.fired++; }" % value)
    assert _first_tick(rt, lambda: vm.this.get("fired")) == fires_on


@needs_gs2
def test_gs2_settimer_zero_cancels():
    rt, vm = _gs2("function onCreated() { setTimer(0.05); setTimer(0); }\n"
                  "function onTimeout() { this.fired++; }")
    assert _first_tick(rt, lambda: vm.this.get("fired")) is None


@needs_gs2
@pytest.mark.parametrize("value,after", [(0.05, 1), (0.1, 2)])
def test_gs2_sleep_resumes_on_its_tick(value, after):
    rt, vm = _gs2("function onCreated() { sleep(%s); this.after = 1; }" % value)
    assert _first_tick(rt, lambda: vm.this.get("after")) == after


@needs_gs2
@pytest.mark.parametrize("value,after", [(0.05, 1), (0.1, 2)])
def test_gs2_scheduleevent_fires_on_its_tick(value, after):
    rt, vm = _gs2('function onCreated() { scheduleevent(%s, "onPing", 7); }\n'
                  "function onPing(v) { this.got = v; }" % value)
    assert _first_tick(rt, lambda: vm.this.get("got")) == after
    assert vm.this.get("got") == 7


@needs_gs2
def test_gs2_waitfor_times_out_on_its_tick():
    rt, vm = _gs2("public function wait() {\n"
                  '  this.r = waitfor(this, "Never", 0.1);\n'
                  "  this.done = 1;\n}")
    rt._run(vm, "wait")
    assert _first_tick(rt, lambda: vm.this.get("done")) == 2
    assert vm.this.get("r") == 0


# == input latching ==============================================================

def test_a_tap_between_two_ticks_acts_exactly_once(make_game, monkeypatch):
    game = make_game()
    swings = []
    game._swing_sword = lambda: swings.append(game.clock.tick)
    hold(monkeypatch)                          # nothing held at any tick
    game.frames(1, dt=1 / 60)                  # sync: tick boundary pending
    while game.clock.accumulator > 1e-9:
        game.frames(1, dt=1 / 60)
    # Down and up inside one inter-tick gap: the frame that sees the KEYDOWN
    # runs no tick, and the key is released before the next one.
    game.frames(1, dt=1 / 60, events=[key_event(pygame.K_SPACE)])
    assert swings == []
    game.frames(6, dt=1 / 60)
    assert len(swings) == 1


def test_holding_across_100_frames_at_144fps_walks_once_per_tick(make_game,
                                                                 monkeypatch):
    game = make_game(player_xy=(20.0, 30.0))
    hold(monkeypatch, pygame.K_RIGHT)
    tick0, x0 = game.clock.tick, game.client.x
    game.frames(100, dt=1 / 144)
    ticks = game.clock.tick - tick0
    assert ticks == int(100 / 144 / TICK + 1e-9)
    assert game.client.x - x0 == pytest.approx(ticks * 0.5)


# == packets ======================================================================

def test_at_most_one_position_packet_per_tick_and_none_between(make_game,
                                                               monkeypatch):
    game = make_game(player_xy=(20.0, 30.0))
    hold(monkeypatch, pygame.K_RIGHT, pygame.K_DOWN)   # diagonal: 4 steps/tick
    for _ in range(30):
        mark, tick = len(game.client._protocol.sent), game.clock.tick
        game.frames(1, dt=1 / 60)
        sent = len(movement_packets(game, mark))
        assert sent <= game.clock.tick - tick
    # A stall: one tick, one packet, no burst.
    mark = len(game.client._protocol.sent)
    game.frames(1, dt=0.5)
    assert len(movement_packets(game, mark)) == 1


def _session(make_game, monkeypatch, fps):
    """A scripted session sampled at `fps`: the keys held for each tick and a
    sword tap; returns per-tick state and the packets each tick sent."""
    game = make_game(player_xy=(20.0, 30.0), arrows=[(40.0, 32.0, 1)])
    plan = ([(pygame.K_RIGHT,)] * 8 + [(pygame.K_DOWN,)] * 6
            + [(pygame.K_RIGHT, pygame.K_UP)] * 6 + [()] * 4)
    held = hold(monkeypatch)
    log = []
    real_tick = game._simulation_tick
    loopback = game.client._protocol

    def recorded(strict):
        mark = len(loopback.sent)
        real_tick(strict)
        p = game.client.player
        log.append((game.clock.tick, round(p.x, 6), round(p.y, 6), p.direction,
                    game.current_anim_name, p.action_mode,
                    tuple(sorted((round(a["x"], 6), round(a["y"], 6))
                                 for a in game.active_projectiles)),
                    tuple(loopback.sent[mark:])))
    game._simulation_tick = recorded
    start = game.clock.tick
    tapped = False
    while game.clock.tick - start < len(plan):
        index = game.clock.tick - start
        held.clear()
        held.update({k: True for k in plan[index]})
        events = None
        if index == 10 and not tapped:
            events, tapped = [key_event(pygame.K_SPACE)], True
        game.frames(1, dt=1.0 / fps, events=events)
    return [(t - start,) + tuple(rest) for t, *rest in log]


def test_simulation_and_packets_are_identical_at_30_60_and_144_fps(
        make_game, monkeypatch):
    """Interpolation is presentation only: drawing at different alphas
    changes nothing the simulation does or sends."""
    runs = {fps: _session(make_game, monkeypatch, fps) for fps in (30, 60, 144)}
    assert len(runs[60]) == 24
    assert runs[30] == runs[60] == runs[144]
    assert any(entry[-1] for entry in runs[60])        # it did send


# == thrown bomb landing (render scene) ===========================================

def test_a_thrown_bomb_lands_on_tick_nine_and_its_fuse_runs_from_landing(
        make_game):
    """A carried bomb's fuse is paused (TServerLevel.cpp:1310-1340 only counts
    lying bombs); on landing it is re-placed with the fuse it had left
    (TServerCarry.cpp:237-258), so the count restarts at the landing tick.
    The flight is nine ticks (TPlayer.cpp:7831), and the bomb is drawn from
    the landing tick on."""
    from frame_baseline import capture
    game = make_game()
    player = game.client.player
    with _running(game):
        bomb = {"x": player.x + .5, "y": player.y - 1.375,
                "time": game.clock.sim_now(), "fuse_time": 3.0, "power": 1,
                "exploded": False, "carried_by": player.id,
                "fuse_remaining": 0.5}
        game.active_bombs.append(bomb)
        player.pickup_object("bomb", (), (player.x, player.y))
        player.carried_bomb = bomb
        game._throw_object()
    drawn = []
    real = game._render_bomb_ticking
    game._render_bomb_ticking = lambda *a: (drawn.append(game.clock.tick), real(*a))
    start = game.clock.tick
    landed = None
    for _ in range(12):
        game.ticks(1)
        if landed is None and not bomb.get("in_flight"):
            landed = game.clock.tick
    assert landed - start == 9
    assert drawn and drawn[0] == landed
    capture(game, "landed")
    # 0.5 s of fuse left = 10 ticks from landing, not from the throw.
    while not bomb.get("exploded") and game.clock.tick - landed < 20:
        game.ticks(1)
    assert game.clock.tick - landed == 10
    capture(game, "burst")
    assert game.frame_errors == {}


# == "never" sentinels at session start ==========================================

def test_first_actions_right_after_session_start_are_not_held_back(
        make_game, monkeypatch):
    """Cooldowns compare simulation time with the time of the last action.
    "Never" is -inf / None, not 0.0: with the simulation clock at zero (no
    SIM_ORIGIN offset) the first grab, the first script triggeraction, the
    first flag send and the first chat bubble all go through."""
    monkeypatch.setattr(Clock, "SIM_ORIGIN", 0.0)
    game = make_game()
    assert game.clock.sim_now() == 0.0
    grabs = []
    game._try_grab = lambda: grabs.append(game.clock.tick)
    hold(monkeypatch, pygame.K_a)
    game.ticks(1, events=[key_event(pygame.K_a)])
    assert grabs == [1]                                 # action_delay passed

    sent = []
    game.client.triggeraction = lambda *a, **k: sent.append(a)
    with _running(game):
        game.gs1.on_triggeraction(30.0, 30.0, "first", 0)
    assert sent and sent[0][0] == "first"

    with _running(game):
        assert game.gs1._flag_send_allowed()

    game.local_chat_text = "hi"
    game.local_chat_time = game.clock.sim_now()
    bubbles = []
    game._render_speech_bubble = lambda x, y, text: bubbles.append(text)
    with _running(game):
        game._render_player_chat(10, 20)
    assert bubbles == ["hi"]


@pytest.mark.parametrize("frame_tick", [16, 41])
def test_simulation_and_packets_are_identical_across_fps_at_a_script_tick(
        make_game, monkeypatch, frame_tick):
    """The same holds with a script-set frame tick: the frame rate decides
    how many ticks run per second, never what a tick does or sends."""
    def session(fps):
        real = offline_game.build_client

        def build(**knobs):
            client = real(**knobs)
            client.clock.set_frame_tick(frame_tick)
            return client
        monkeypatch.setattr(offline_game, "build_client", build)
        try:
            return _session(make_game, monkeypatch, fps)
        finally:
            monkeypatch.setattr(offline_game, "build_client", real)
    runs = {fps: session(fps) for fps in (30, 60, 144)}
    assert len(runs[60]) == 24
    assert runs[30] == runs[60] == runs[144]


# == the frame tick (TTime::frametick) ===========================================

def _setframetick(rt, value):
    from pyreborn.gs2_client import registry
    handler = registry._GS2_BARE["adventure_setframetick"]
    return handler(rt.host, None, "adventure_setframetick", [value], None)


def _getframetick(rt, name="adventure_getframetick"):
    from pyreborn.gs2_client import registry
    return registry._GS2_BARE[name](rt.host, None, name, [], None)


def test_a_session_starts_at_fifty_ms():
    """TServerList.cpp:376 sets 50 at server-list login."""
    clock = Clock(source=lambda: 0.0)
    assert clock.frame_tick_ms == 50
    assert clock.tick_length == pytest.approx(0.05)
    assert Clock.tick_length == pytest.approx(0.05)


@pytest.mark.parametrize("value,stored", [
    (1000 / 60, 16), (1000 / 24, 41), (1000 / 120, 8), (50, 50), (0, 0),
    (0.99995, 1), (2.9, 2), (-1, 4294967295), (-0.5, 4294967295),
    (1e12, 2147483648), ("33", 33), ("junk", 0)])
def test_setframetick_converts_like_the_reference(value, stored):
    """'i' argument: floor(v + 0.0001) as int32 (TScriptMachine.cpp:4522-4528),
    stored in a uint32_t (TTime.cpp:8, :23-26); out of int32 range -> INT_MIN."""
    rt = ClientGS2()
    assert _setframetick(rt, value) == 0.0
    assert rt.clock.frame_tick_ms == stored
    assert _getframetick(rt) == stored
    assert _getframetick(rt, "getframetick") == stored


def test_setframetick_without_an_argument_changes_nothing():
    from pyreborn.gs2_client import registry
    rt = ClientGS2()
    registry._GS2_BARE["adventure_setframetick"](
        rt.host, None, "adventure_setframetick", [], None)
    assert rt.clock.frame_tick_ms == 50


def test_bare_setframetick_is_not_the_reference_setter():
    """TTime.cpp:60-63 registers only adventure_setframetick; a bare
    setFrameTick is a script's own function (weapon -Adventure)."""
    from pyreborn.gs2_client import registry
    rt = ClientGS2()
    registry._GS2_BARE["setframetick"](rt.host, None, "setframetick", [16], None)
    assert rt.clock.frame_tick_ms == 50


def test_the_frame_tick_does_not_leak_into_the_next_server(make_client):
    """Every server gets a new Client, so a new Clock at 50 ms."""
    first = make_client()
    first.clock.set_frame_tick(16)
    second = make_client()
    assert second.clock.frame_tick_ms == 50
    assert first.clock is not second.clock


@pytest.mark.parametrize("frame_tick,fps,per_second", [
    (50, 30, 20), (50, 60, 20), (50, 144, 20),
    (41, 30, 24), (41, 60, 24), (41, 144, 24),
    (16, 30, 30), (16, 60, 60), (16, 144, 62),
    (8, 30, 30), (8, 60, 60), (8, 144, 124),
    (0, 30, 30), (0, 60, 60), (0, 144, 144)])
def test_ticks_per_second_at_a_frame_tick(frame_tick, fps, per_second):
    """At most one tick per frame, late time dropped (AndroidInterface.cpp:
    170-179): a tick shorter than the frame runs once per frame."""
    clock = Clock(source=lambda: 0.0)
    clock.set_frame_tick(frame_tick)
    ticks = sum(clock.ticks_due(1.0 / fps) for _ in range(10 * fps))
    assert abs(ticks / 10 - per_second) <= 1


def test_a_huge_frame_tick_stops_the_ticks():
    clock = Clock(source=lambda: 0.0)
    clock.set_frame_tick(-1)
    assert clock.tick_length == pytest.approx(4294967.295)
    assert sum(clock.ticks_due(1 / 60) for _ in range(600)) == 0


def test_walking_is_half_a_tile_per_tick_at_any_frame_tick(make_game,
                                                           monkeypatch):
    """TPlayer.cpp:807, :7436 count walking per tick: a 16 ms tick walks
    three times as fast in real time, and each tick still moves 0.5."""
    speeds = {}
    for frame_tick in (50, 16):
        game = make_game(player_xy=(10.0, 30.0))
        game.clock.set_frame_tick(frame_tick)
        hold(monkeypatch, pygame.K_RIGHT)
        tick0, x0 = game.clock.tick, game.client.x
        game.frames(30, dt=1 / 60)                 # half a second
        ticks = game.clock.tick - tick0
        assert game.client.x - x0 == pytest.approx(ticks * 0.5)
        speeds[frame_tick] = ticks
    assert speeds == {50: 10, 16: 30}


def test_sim_time_counts_ticks_whatever_the_frame_tick():
    t = [0.0]
    clock = Clock(source=lambda: t[0])
    start = clock.sim_now()
    clock.begin_tick()
    clock.set_frame_tick(16)
    clock.begin_tick()
    clock.set_frame_tick(100)
    clock.begin_tick()
    assert clock.sim_now() == pytest.approx(start + 3 * Clock.TICK_SECONDS)


def test_script_clock_steps_by_the_frame_tick_or_follows_real_time():
    """TScriptUniverse.cpp:226-231."""
    t = [0.0]
    clock = Clock(source=lambda: t[0])
    t[0] += 0.05
    clock.begin_tick()
    assert clock.script_dt == pytest.approx(0.05)
    t[0] += 0.3                                 # a late tick
    clock.begin_tick()
    assert clock.script_dt == pytest.approx(0.05)   # virtual: one step
    clock.set_frame_tick(16)
    t[0] += 0.016
    clock.begin_tick()
    # Real time now: the 0.25 s the steps fell behind plus this tick's 16 ms.
    assert clock.script_dt == pytest.approx(0.266)
    t[0] += 0.017
    clock.begin_tick()
    assert clock.script_dt == pytest.approx(0.017)
    clock.set_frame_tick(100)
    t[0] += 0.5
    clock.begin_tick()
    assert clock.script_dt == pytest.approx(0.1)


def test_script_clock_never_runs_backwards():
    t = [0.0]
    clock = Clock(source=lambda: t[0])
    for _ in range(3):
        t[0] += 0.05
        clock.begin_tick()
    t[0] -= 1.0                                 # a source that steps back
    clock.set_frame_tick(16)
    before = clock.script_now()
    clock.begin_tick()
    assert clock.script_now() == before and clock.script_dt == 0.0


@needs_gs2
def test_pending_timers_across_a_mid_session_frame_tick_change(make_game):
    """A 0.5 timer armed at 50 ms keeps its remaining script time across the
    switch: 4 counted ticks of 0.05 at 50 ms (armed between ticks, it counts
    from the second tick, Clock.script_pass), then 16 ms ticks of real time,
    so it fires 0.5 s of script time after arming, in more (shorter) ticks."""
    game = make_game()
    vm = game.gs2.load_bytecode("weapon", "pending", Gs2Compiler().compile(
        "function onCreated() { setTimer(0.5); }\n"
        "function onTimeout() { this.fired = 1; }"))
    game.ticks(5)
    armed_left = game.gs2._timeouts[game.gs2._timeout_key(vm)]
    assert armed_left == pytest.approx(0.3)
    game.clock.set_frame_tick(16)
    ticks = 0
    while not vm.this.get("fired") and ticks < 100:
        game.frames(1, dt=0.016)
        ticks += 1
    # 0.3 s left at 16 ms per tick: 19 ticks (18.75 rounded up).
    assert ticks == 19


@needs_gs2
@pytest.mark.parametrize("fps", [60, 144])
def test_adventure_setframetick_drives_a_rearming_loop_in_the_game(make_game,
                                                                   fps):
    """The bomber cog loop through the real frame: Adventure_setFrameTick(
    1000/60) then setTimer(0.01) every onTimeout fires once per tick, about
    60 times a second; at the default tick it fires 20 times."""
    script = ("function onCreated() { %s setTimer(0.01); }\n"
              "function onTimeout() { this.fires++; setTimer(0.01); }")
    counts = {}
    for name, prefix in (("default", ""),
                         ("raised", "Adventure_setFrameTick(1000/60);")):
        game = make_game()
        vm = game.gs2.load_bytecode("weapon", "cog", Gs2Compiler().compile(
            script % prefix))
        game.frames(fps, dt=1.0 / fps)
        counts[name] = float(vm.this.get("fires") or 0)
    assert abs(counts["default"] - 20) <= 1
    assert 58 <= counts["raised"] <= 63


# == review findings (2026-11-12) ================================================

def _to_tick_boundary(game):
    """Run frames until the next frame of 1/60 s cannot complete a tick, so
    the next two frames run no tick."""
    game.frames(1, dt=1 / 60)
    while game.clock.accumulator > 1e-9:
        game.frames(1, dt=1 / 60)


def _count_swings(game):
    swings = []
    game._swing_sword = lambda: swings.append(game.clock.tick)
    return swings


def test_keys_typed_into_chat_never_reach_gameplay(make_game, monkeypatch):
    """Chat open; `s`, Right, Enter inside one tick: the chat took them all,
    so the tick that follows neither swings nor walks."""
    game = make_game(player_xy=(20.0, 30.0))
    swings = _count_swings(game)
    hold(monkeypatch)
    game.ticks(1, events=[key_event(pygame.K_RETURN)])
    assert game.chat.typing
    _to_tick_boundary(game)
    x0 = game.client.x
    game.frames(1, dt=1 / 60, events=[key_event(pygame.K_s, "s")])
    game.frames(1, dt=1 / 60, events=[key_event(pygame.K_RIGHT)])
    game.frames(1, dt=1 / 60, events=[key_event(pygame.K_RETURN)])
    assert not game.chat.typing
    game.ticks(2)
    assert swings == [] and game.client.x == x0


def test_a_key_held_while_chat_closes_walks_as_before_the_tick_model(
        make_game, monkeypatch):
    """The code before the tick model read held keys every frame
    (pygame.key.get_pressed), so an arrow held down while the chat closed
    walked from the closing frame on. The tick model keeps that."""
    game = make_game(player_xy=(20.0, 30.0))
    held = hold(monkeypatch)
    game.ticks(1, events=[key_event(pygame.K_RETURN)])
    held[pygame.K_RIGHT] = True
    game.ticks(1, events=[key_event(pygame.K_RIGHT)])
    x0 = game.client.x
    game.ticks(1, events=[key_event(pygame.K_RETURN)])
    game.ticks(2)
    assert game.client.x == pytest.approx(x0 + 1.5)


@pytest.mark.parametrize("between", ["chat_open_close", "focus_lost",
                                     "server_warp", "death"])
def test_a_latched_edge_is_dropped_when_play_was_interrupted(
        make_game, monkeypatch, between):
    """A sword tap latched between two ticks does not act when, before that
    tick, an overlay opened (or closed), the window lost focus, the server
    warped us or we died."""
    game = make_game(player_xy=(20.0, 30.0),
                     extra_levels={"elsewhere.nw": None})
    swings = _count_swings(game)
    hold(monkeypatch)
    _to_tick_boundary(game)
    game.frames(1, dt=1 / 60, events=[key_event(pygame.K_SPACE)])
    if between == "chat_open_close":
        game.frames(1, dt=1 / 60, events=[key_event(pygame.K_RETURN),
                                          key_event(pygame.K_RETURN)])
    elif between == "focus_lost":
        game.frames(1, dt=1 / 60, events=[
            pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    elif between == "server_warp":
        game.server.run(lambda w: w.me.warp("elsewhere.nw", 10.0, 12.0))
        game.frames(1, dt=1 / 60)
    else:
        game.client.player.hearts = 0.0
        game.frames(1, dt=1 / 60)
    game.ticks(1)
    game.client.player.hearts = 3.0
    game.ticks(2)
    assert swings == []


def test_a_timeout_armed_while_walking_fires_on_the_next_tick(make_game,
                                                              monkeypatch):
    """The reference runs the scripts after the player's movement and queues
    the touch event into that script pass (TPlayer.cpp:7374 doNPCActions,
    TScriptSpace.cpp:459: timers are checked before the queued events
    run), so `timeout = 0.05` set by playertouchsme is stamped with this
    tick's script time and fires on the next tick."""
    npc = dict(offline_game.IMAGE_NPC, x=31.5, y=30.0,
               script="if (playertouchsme) timeout = 0.05;\n"
                      "if (timeout) this.fired = 1;\n")
    game = make_game(player_xy=(29.0, 30.0), npcs=[npc])
    events = []
    real = game.gs1.trigger_npc_event

    def trigger(npc_id, event, *a, **k):
        events.append((event, game.clock.tick))
        return real(npc_id, event, *a, **k)
    game.gs1.trigger_npc_event = trigger
    hold(monkeypatch, pygame.K_RIGHT)
    game.ticks(4)
    touched = [t for e, t in events if e == "playertouchsme"]
    fired = [t for e, t in events if e == "timeout"]
    assert touched and fired
    assert fired[0] == touched[0] + 1


@pytest.mark.parametrize("seconds,ticks", [(0.05, 1), (0.15, 3), (0.3, 6),
                                           (0.35, 7), (0.37, 8), (0.0, 0)])
def test_passed_is_exact_in_ticks_from_any_start_tick(seconds, ticks):
    clock = Clock(source=lambda: 0.0)
    for start in range(0, 2000, 7):
        clock.tick = start
        stamp = clock.sim_now()
        clock.tick = start + ticks - 1
        assert ticks == 0 or not clock.passed(stamp, seconds)
        clock.tick = start + ticks
        assert clock.passed(stamp, seconds)


def test_action_and_sword_cooldowns_do_not_depend_on_the_start_tick(
        make_game, monkeypatch):
    """Action cooldown 7 ticks, sword cooldown 4 ticks, from any tick."""
    game = make_game(player_xy=(20.0, 30.0))
    grabs = []
    game._try_grab = lambda: grabs.append(game.clock.tick)
    swings = _count_swings(game)
    held = hold(monkeypatch)
    for key, log, gap in ((pygame.K_a, grabs, 7), (pygame.K_SPACE, swings, 4)):
        for offset in range(5):
            game.ticks(10 + offset)
            log.clear()
            for _ in range(12):
                held.clear()
                held[key] = True
                game.ticks(1, events=[key_event(key)])
                held.clear()
            assert [b - a for a, b in zip(log, log[1:])] == [gap] * (len(log) - 1)
            assert len(log) >= 2


@needs_gs2
def test_scripted_movement_is_announced_on_every_tick(make_game):
    """GS2 `player.x += 0.25` every tick: one position packet every tick
    (the once-per-tick throttle must not skip ticks)."""
    game = make_game(player_xy=(20.0, 30.0))
    game.gs2.load_bytecode("weapon", "mover", Gs2Compiler().compile(
        "function onCreated() { setTimer(0.05); }\n"
        "function onTimeout() { player.x += 0.25; setTimer(0.05); }"))
    game.ticks(3)
    counts = []
    for _ in range(12):
        mark = len(game.client._protocol.sent)
        game.ticks(1)
        counts.append(len(movement_packets(game, mark)))
    assert counts == [1] * 12


# == the frame tick across servers (TServerList.cpp:132-167, :376) ==============

def _accept_server_warp(game):
    """A script's PLO_SERVERWARP, confirmed in the prompt."""
    with offline_game._running(game):
        assert game.offer_server_warp({"host": "127.0.0.1", "port": 14999,
                                       "name": "next"})
    game.frames(int(game.SERVER_WARP_ARM_SECONDS * 60) + 2)
    game.frames(1, events=[key_event(pygame.key.key_code(c), c)
                           for c in game.SERVER_WARP_CONFIRM_WORD])
    game.frames(1, events=[key_event(pygame.K_RETURN)])
    assert game.switch_server is not None and game.switch_server.port == 14999


def test_a_script_serverwarp_keeps_the_frame_tick(make_game):
    """handleServerWarp hands the move to StartScript_Connector and leaves
    TTime::frametick alone: the next session ticks as the scripts set it."""
    from pyreborn.example_pygame import session_client
    game = make_game()
    game.clock.set_frame_tick(16)
    _accept_server_warp(game)
    assert game.switch_frame_tick == 16
    client = session_client("127.0.0.1", 14999, "6.037", game.switch_frame_tick)
    assert client.clock.frame_tick_ms == 16


def test_a_server_the_player_picks_starts_at_fifty_ms(make_game):
    """A server-list login sets frametick = 50 (TServerList.cpp:376)."""
    from pyreborn.example_pygame import session_client
    from pyreborn.listserver import ServerEntry
    game = make_game()
    game.clock.set_frame_tick(16)
    game.servers = [ServerEntry(name="other", type_prefix="", language="",
                                description="", url="", version="",
                                player_count=0, ip="127.0.0.1", port=14998)]
    game.frames(1, events=[key_event(pygame.K_F8)])
    game.frames(1, events=[key_event(pygame.K_RETURN)])
    assert game.switch_server is game.servers[0]
    assert game.switch_frame_tick is None
    client = session_client("127.0.0.1", 14998, "6.037", game.switch_frame_tick)
    assert client.clock.frame_tick_ms == 50
