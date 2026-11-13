from types import SimpleNamespace

import pytest
from reborn_protocol import PLSTATUS

from pyreborn.flyingobjects import (
    BOUNCE_COUNTER, FLYING_TICK_SECONDS, NOT_BOUNCING,
)
from pyreborn.gs1_client import ClientGS1
from pyreborn.npc_handler import NPCHandler
from pyreborn.tiletypes import is_blocking

from .test_gs1_npc_host_gaps import _client, _this

TICK = FLYING_TICK_SECONDS
WALL = next(tile for tile in range(4096) if is_blocking(tile))


@pytest.fixture
def new_harness(make_game, monkeypatch):
    """``new_harness(player_xy=(30, 30), immune=False, **knobs)``: a real
    offline game on an open board, with recorders on what flying.py does:
    ``hurts`` (hurt_local_by_flying calls), ``blasts`` (make_explosion calls),
    ``shots`` (gs1/gs2 wasshot triggers), ``probes`` (every wall, player and
    NPC probe, in order), ``npc_cells`` (``{(tx, ty): npc id}`` the NPC probe
    answers from) and the game's own sound manager (``sounds``). ``immune``
    makes the local player refuse hits."""
    def build(player_xy=(30.0, 30.0), immune=False, **knobs):
        knobs.setdefault('tiles', lambda tx, ty: 0)
        h = make_game(**knobs)
        h.hurts, h.blasts, h.shots, h.probes = [], [], [], []
        h.npc_cells = {}
        h.client.player.x, h.client.player.y = player_xy
        h.sounds = []
        real_play = h.sound_mgr.play
        monkeypatch.setattr(h.sound_mgr, 'play',
                            lambda name, *a, **k: (h.sounds.append(name),
                                                   real_play(name, *a, **k))[1])
        monkeypatch.setattr(h.client, 'can_receive_local_hit',
                            lambda *a, **k: not immune)
        real_hurt = h.client.hurt_local_by_flying
        monkeypatch.setattr(h.client, 'hurt_local_by_flying',
                            lambda *a: (h.hurts.append(a), real_hurt(*a))[1])
        real_boom = h.client.make_explosion
        monkeypatch.setattr(h.client, 'make_explosion',
                            lambda *a: (h.blasts.append(a), real_boom(*a))[1])
        monkeypatch.setattr(h.npc_handler, 'npc_at_point',
                            lambda x, y: h.npc_cells.get((int(x), int(y))))
        monkeypatch.setattr(
            h.gs1, 'trigger_npc_wasshot',
            lambda i, by: h.shots.append(('gs1', i, by)))
        monkeypatch.setattr(
            h.gs2, 'trigger_npc_wasshot',
            lambda i, by: h.shots.append(('gs2', i, by)))
        for name, label in (('_is_blocked_at', 'wall'),
                            ('_flying_hits_player', 'player'),
                            ('_flying_npc_at', 'npc')):
            real = getattr(h, name)

            def probe(*args, _real=real, _label=label, **kwargs):
                # ('wall', x, y, check_players), ('player', x, y), ('npc', x, y)
                if _label == 'wall':
                    check = kwargs.get('check_players',
                                       args[2] if len(args) > 2 else True)
                    h.probes.append((_label, args[0], args[1], check))
                else:
                    h.probes.append((_label,) + tuple(args[-2:]))
                return _real(*args, **kwargs)
            monkeypatch.setattr(h, name, probe)
        return h
    return build


def set_walls(h, cells):
    for tx, ty in cells:
        h.client.tiles[ty * 64 + tx] = WALL


def fly(h, x, y, direction, power, from_player=False):
    step = 20.0
    dx, dy = ((0, -step), (-step, 0), (0, step), (step, 0))[direction]
    return {'x': x, 'y': y, 'dx': dx, 'dy': dy, 'direction': direction,
            'power': power, 'from_player': from_player, 'lx': x, 'ly': y,
            'tick_acc': 0.0, 'bounce': NOT_BOUNCING}


def run(h, proj, ticks):
    """Advance whole ticks; returns the tick on which it finished."""
    for n in range(1, ticks + 1):
        if not h._advance_flying(proj, TICK):
            return n
    return None


def test_a_level_npcs_fireblast_hurts_the_player_and_explodes(new_harness):
    h = new_harness(player_xy=(30.0, 20.0))
    proj = fly(h, 20.0, 20.5, 3, 2)
    done = run(h, proj, 30)
    assert done == 9
    assert h.hurts == [(2, 1.0, 0.0)]      # power, unit travel direction
    assert len(h.blasts) == 1
    x, y, radius, kind, owner, from_player = h.blasts[0]
    assert (radius, kind, owner, from_player) == (2, 1, 0, False)
    # TServerFlying.cpp:102-103: (28 + 0.9375 - 1, 20.5 + 0.3125 - 1).
    assert (x, y) == (27.9375, 19.8125)
    assert h.sounds.count('bomb.wav') == 1       # :105 (the hurt sound is the victim's)


def test_a_weapon_scripts_shot_never_hurts_its_own_player(new_harness):
    h = new_harness(player_xy=(30.0, 20.0))
    proj = fly(h, 20.0, 20.5, 3, 3, from_player=True)
    assert run(h, proj, 30) is None          # flew straight through (:127)
    assert h.hurts == [] and h.blasts == []


def test_a_player_who_cannot_be_hurt_still_blocks_the_wall_probe(new_harness):
    h = new_harness(player_xy=(30.0, 20.0), immune=True)
    assert run(h, fly(h, 20.0, 20.75, 3, 2), 30) == 10
    assert h.hurts == []
    assert h.blasts == [(28.9375, 20.0625, 2, 1, 0, False)]


def test_a_remote_player_blocks_a_nukes_centre_probe(new_harness):
    # The wall query includes players (TServerFlying.cpp:276-279;
    # TServerLevel.cpp:2650), even though only the local player can be hurt.
    h = new_harness(player_xy=(0.0, 0.0))
    h.client.players[2] = {'x': 30.0, 'y': 20.0}
    assert run(h, fly(h, 20.0, 20.75, 3, 3), 30) == 10
    assert h.hurts == []
    assert h.probes[-1] == ('wall', 30.9375, 21.0625, True)
    assert h.blasts == [(28.9375, 20.0625, 2, 1, 0, False)]


def test_a_wall_explodes_a_nuke_where_it_was_one_tick_earlier(new_harness):
    h = new_harness(player_xy=(0.0, 0.0))
    set_walls(h, {(25, 20)})
    proj = fly(h, 20.0, 20.0, 3, 3)
    done = run(h, proj, 40)
    assert done is not None
    assert h.hurts == []
    assert len(h.blasts) == 1 and h.blasts[0][2:4] == (2, 1)


def test_power_one_ignores_walls(new_harness):
    # handleFlyingWallCollision returns at once for power <= 1 (:273); the
    # script callbacks only fire powers 2 and 3, so drive the rule directly.
    h = new_harness(player_xy=(0.0, 0.0))
    set_walls(h, {(25, 20)})
    proj = fly(h, 20.0, 20.0, 3, 1)
    assert run(h, proj, 10) is None and h.blasts == []
    assert all(probe[0] != 'wall' for probe in h.probes)


@pytest.mark.parametrize('direction, start, done', [
    (0, (-0.3125, 1.0625), 2),
    (1, (1.0625, -0.3125), 2),
])
def test_leaving_the_level_checks_top_left_and_motion(direction, start, done, new_harness):
    # Launch offsets leave the perpendicular axis negative. Only travel toward
    # that edge transfers, before all probes (TServerFlying.cpp:378-388).
    h = new_harness(player_xy=(30.0, 30.0))
    proj = fly(h, *start, direction, 3)
    for tick in range(1, done + 1):
        h.probes.clear()
        assert h._advance_flying(proj, TICK) is (tick < done)
        assert [p[0] for p in h.probes] == (
            ['player', 'npc', 'wall'] if tick < done else [])
    assert h.blasts == [] and h.hurts == []


@pytest.mark.parametrize('direction, start', [
    (2, (-0.3125, 61.0625)),
    (3, (61.0625, -0.3125)),
])
def test_a_nuke_whose_centre_passes_the_far_edge_explodes_on_the_edge(direction, start, new_harness):
    # Past the board with no side level, the level's tile query answers the
    # default tile (TServerLevel.cpp:587), whose type is a wall, so the centre
    # probe blocks one tick before the origin test (:381-388) would drop it.
    h = new_harness(player_xy=(30.0, 30.0))
    proj = fly(h, *start, direction, 3)
    assert run(h, proj, 5) == 2
    assert [p[0] for p in h.probes[-3:]] == ['player', 'npc', 'wall']
    assert len(h.blasts) == 1 and h.hurts == []


def test_the_local_player_blocks_flying_probes_but_never_movement(new_harness):
    # isOnPlayer walks the level's whole player list (TServerLevel.cpp:794,
    # :2650); the local player is on it. Movement must not collide with itself.
    h = new_harness(player_xy=(30.0, 20.0))
    assert h._is_blocked_at(31.0, 22.0, include_local=True)
    assert not h._is_blocked_at(31.0, 22.0)
    assert not h._is_blocked_at(29.9, 22.0, include_local=True)
    # The box starts at x + 0.5 (TServerLevel.cpp:789-794 bounds): 30.2 is left of it.
    assert not h._is_blocked_at(30.2, 22.0, include_local=True)
    assert h._is_blocked_at(30.5, 22.0, include_local=True)


@pytest.mark.parametrize('status', [PLSTATUS.DEAD, PLSTATUS.HIDDEN])
def test_a_dead_or_hidden_local_player_does_not_block_flying_probes(status, new_harness):
    # Mutation: drop the DEAD|HIDDEN test on the local player in
    # CollisionMixin._player_blocks -> the include_local probe turns True.
    h = new_harness(player_xy=(30.0, 20.0))
    assert h._is_blocked_at(31.0, 22.0, include_local=True)
    h.client.player.status = status
    assert not h._is_blocked_at(31.0, 22.0, include_local=True)


def test_a_bounce_uses_motion_for_the_level_edge_gate(new_harness):
    h = new_harness(player_xy=(0.0, 0.0))
    proj = fly(h, 0.0625, 20.0, 3, 3)
    proj.update(dx=-20.0, bounce=BOUNCE_COUNTER)
    assert run(h, proj, 1) == 1
    assert h.probes == [] and proj['bounce'] == BOUNCE_COUNTER


def test_negative_gmap_world_coordinates_obey_the_direction_gate(new_harness):
    h = new_harness(player_xy=(30.0, 30.0), gmap=True)
    assert h.client.in_gmap_segment
    proj = fly(h, -2.9375, 20.75, 3, 1)
    assert run(h, proj, 3) is None
    assert proj['lx'] == 0.0625
    assert [p[0] for p in h.probes] == ['player', 'npc'] * 3
    proj['dx'] = -20.0
    h.probes.clear()
    assert run(h, proj, 1) == 1
    assert h.probes == [] and h.blasts == []


def test_several_ticks_in_a_slow_frame_match_one_tick_per_frame(new_harness):
    h = new_harness(player_xy=(30.0, 20.0))
    slow = new_harness(player_xy=(30.0, 20.0))
    proj = fly(h, 20.0, 20.5, 3, 3)
    slow_proj = fly(slow, 20.0, 20.5, 3, 3)
    assert run(h, proj, 8) is None
    assert slow._advance_flying(slow_proj, 8 * TICK)
    assert slow.probes == h.probes
    assert run(h, proj, 1) == 1
    assert not slow._advance_flying(slow_proj, 3 * TICK)
    assert slow.probes == h.probes
    assert slow.hurts == h.hurts == [(3, 1.0, 0.0)]
    assert slow.blasts == h.blasts == [(27.9375, 19.8125, 2, 1, 0, False)]
    assert (slow_proj['lx'], slow_proj['ly']) == (proj['lx'], proj['ly'])


@pytest.mark.parametrize("from_player", [False, True])
def test_an_npc_hit_fires_wasshot_then_bounces_back_for_four_ticks(from_player, new_harness):
    h = new_harness(player_xy=(0.0, 0.0))
    h.npc_cells = {(24, 20): 7}
    proj = fly(h, 20.0, 20.0, 3, 3, from_player=from_player)
    hit_tick = None
    for n in range(1, 30):
        if not h._advance_flying(proj, TICK):
            end = n
            break
        if hit_tick is None and proj['bounce'] != NOT_BOUNCING:
            hit_tick = n
            assert proj['dx'] < 0          # reversed (:256-259)
            assert proj['bounce'] == BOUNCE_COUNTER
    assert h.shots == [('gs1', 7, from_player), ('gs2', 7, from_player)]
    assert end - hit_tick == 4              # :405-408
    assert h.blasts == [] and h.hurts == []  # an arrow sprite never explodes


def test_a_bouncing_object_no_longer_tests_player_or_npc(new_harness):
    h = new_harness(player_xy=(0.0, 0.0))
    h.npc_cells = {(24, 20): 7, (23, 20): 7, (22, 20): 7}
    proj = fly(h, 20.0, 20.0, 3, 2)
    run(h, proj, 30)
    assert len([s for s in h.shots if s[0] == 'gs1']) == 1


def test_sprite_position_tracks_the_partial_tick(new_harness):
    h = new_harness(player_xy=(0.0, 0.0))
    proj = fly(h, 10.0, 10.0, 3, 2)
    h._advance_flying(proj, TICK * 1.5)
    assert proj['lx'] == pytest.approx(11.0)
    assert proj['x'] == pytest.approx(11.0 + 20.0 * 0.5 * TICK)


# -- the client-side damage ----------------------------------------------------

@pytest.fixture
def victim(make_client, monkeypatch):
    """``victim(hearts_ok=True)``: (real offline client, log) where ``log.hurt``
    lists respond_to_hurt calls (the answer is ``hearts_ok``) and ``log.cb``
    the on_hurt callback calls."""
    def build(hearts_ok=True):
        client = make_client()
        log = SimpleNamespace(hurt=[], cb=[])
        monkeypatch.setattr(
            client, 'respond_to_hurt',
            lambda dmg, gani, knockback=None: log.hurt.append(
                (dmg, knockback)) or hearts_ok)
        monkeypatch.setattr(client, 'can_receive_local_hit', lambda *a, **k: True)
        client.on_hurt = lambda *a: log.cb.append(a)
        return client, log
    return build


@pytest.mark.parametrize("power, damage", [(2, 0.5), (3, 1.0)])
def test_flying_damage_is_the_arrow_damage_for_the_power(victim, power, damage):
    client, log = victim()
    # TServerFlying.cpp:222: powers 1 and 3 hit for a heart, the rest half.
    assert client.hurt_local_by_flying(power, 1.0, 0.0)
    assert log.hurt == [(damage, (1.0, 0.0))]
    assert log.cb == [(0, damage, 2, 1.0, 0.0)]


def test_flying_damage_respects_immunity(victim, monkeypatch):
    client, log = victim()
    monkeypatch.setattr(client, 'can_receive_local_hit', lambda *a, **k: False)
    assert not client.hurt_local_by_flying(2, 0.0, 1.0)
    assert log.hurt == []


# -- wiring ----------------------------------------------------------------------

def test_on_flying_queues_a_ticked_projectile_with_its_shooter(make_game):
    game = make_game()
    game.active_projectiles.clear()
    game.gs1.on_flying(4.0, 5.0, 3, 2)
    level_npc = game.active_projectiles[0]
    assert (level_npc['flying'], level_npc['power'], level_npc['from_player']) == (True, 2, False)
    assert level_npc['bounce'] == NOT_BOUNCING and (level_npc['lx'], level_npc['ly']) == (4.0, 5.0)


# -- GS1 wasshot / shotbyplayer ---------------------------------------------------

def test_gs1_wasshot_runs_the_event_and_scopes_the_shooter_flags():
    c = _client("room0.nw")
    src = ("if (wasshot) { if (shotbyplayer) { this.who = 1; } "
           "if (shotbybaddy) { this.who = 2; } }")
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-", "script": src, "_level": "room0.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", src, npc_id=5, x=10.0, y=10.0)
    gs1.trigger_npc_wasshot(5, True)
    assert _this(gs1, 5)["who"] == 1.0
    gs1.trigger_npc_wasshot(5, False)
    assert _this(gs1, 5)["who"] == 2.0
    assert gs1.shot_attribution is None


def test_the_shooter_flags_are_plain_flags_outside_wasshot():
    c = _client("room0.nw")
    src = "if (playerenters) { if (shotbyplayer) { this.who = 9; } }"
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-", "script": src, "_level": "room0.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", src, npc_id=5, x=10.0, y=10.0)
    gs1.trigger_npc_event(5, "playerenters")
    assert "who" not in _this(gs1, 5)


# -- the NPC probe ------------------------------------------------------------------

def _handler(shapes_type=None):
    c = _client("room0.nw")
    src = "if (playerenters) { setshape2 2,2,{2,2,2,2}; }" if shapes_type is None else \
        "if (playerenters) { setshape2 2,2,{20,20,20,20}; }"
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-", "script": src, "_level": "room0.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", src, npc_id=5, x=10.0, y=10.0)
    gs1.trigger_npc_event(5, "playerenters")
    handler = NPCHandler(c)
    handler.gs1 = gs1
    return handler


def test_npc_at_point_finds_the_npc_under_the_point():
    handler = _handler()
    assert handler.npc_at_point(10.5, 10.5) == 5
    assert handler.npc_at_point(13.0, 13.0) is None


def test_an_npc_wall_cell_is_not_a_target():
    # npc->getTileType(...) == 0x14 refuses the hit (TServerFlying.cpp:249).
    handler = _handler(shapes_type=20)
    assert handler.npc_at_point(10.5, 10.5) is None


# -- through the real render loop ---------------------------------------------------

def test_the_render_loop_runs_a_nuke_into_the_player(make_game, monkeypatch):
    game = make_game(player_xy=(40.0, 30.0))
    game.active_projectiles.clear()
    game.client.active_explosions.clear()
    game.client.player.x, game.client.player.y = 40.0, 30.0
    game.client.player.hurt.until = 0.0
    hurts = []
    monkeypatch.setattr(game.client, 'hurt_local_by_flying',
                        lambda *args: hurts.append(args) or True)
    game.gs1.on_flying(30.0, 30.5, 3, 3)
    for _ in range(40):
        game._update_and_render_projectiles(TICK)
        if not game.active_projectiles:
            break
    assert game.active_projectiles == []
    assert hurts == [(3, 1.0, 0.0)]
    assert game.client.active_explosions      # makeFlyingExplosion raised a blast
