"""Script-fired flying objects (shootfireblast / shootnuke): the hit rules of
TServerFlying::animate, Preagonal/FourPlay/quattroplay/src/TServerFlying.cpp.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.client_combat import CombatMixin
from pyreborn.flyingobjects import (
    BOUNCE_COUNTER, FLYING_TICK_SECONDS, NOT_BOUNCING,
)
from pyreborn.game.callbacks.gs1_callbacks import wire_gs1_callbacks
from pyreborn.game.flying import FlyingObjectsMixin
from pyreborn.gs1_client import ClientGS1
from pyreborn.npc_handler import NPCHandler

from .test_gs1_npc_host_gaps import _client, _this

TICK = FLYING_TICK_SECONDS


class _Sound:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class _Harness(FlyingObjectsMixin):
    """The state flying.py reads, with recorders for what it does."""

    def __init__(self, player_xy=(30.0, 30.0), immune=False):
        self.hurts, self.blasts, self.shots = [], [], []
        self.probes = []
        self.walls = set()
        self.npc_cells = {}
        self.sound_mgr = _Sound()
        self.client = SimpleNamespace(
            player=SimpleNamespace(x=player_xy[0], y=player_xy[1]),
            players={},
            in_gmap_segment=False,
            can_receive_local_hit=lambda *a, **k: not immune,
            hurt_local_by_flying=lambda *a: self.hurts.append(a) or True,
            make_explosion=lambda *a: self.blasts.append(a),
        )
        self.npc_handler = SimpleNamespace(
            npc_at_point=lambda x, y: self.npc_cells.get((int(x), int(y))))
        self.gs1 = SimpleNamespace(
            trigger_npc_wasshot=lambda i, by: self.shots.append(('gs1', i, by)))
        self.gs2 = SimpleNamespace(
            trigger_npc_wasshot=lambda i, by: self.shots.append(('gs2', i, by)))

    def _is_blocked_at(self, x, y, check_players=True):
        self.probes.append(('wall', x, y, check_players))
        if check_players:
            players = [self.client.player, *self.client.players.values()]
            if any(p.x + 0.5 <= x < p.x + 3.0 and
                   p.y + 1.0 <= y < p.y + 3.0 for p in players):
                return True
        return (int(x), int(y)) in self.walls

    def _flying_hits_player(self, proj, x, y):
        self.probes.append(('player', x, y))
        return super()._flying_hits_player(proj, x, y)

    def _flying_npc_at(self, x, y):
        self.probes.append(('npc', x, y))
        return super()._flying_npc_at(x, y)

    def fly(self, x, y, direction, power, from_player=False):
        step = 20.0
        dx, dy = ((0, -step), (-step, 0), (0, step), (step, 0))[direction]
        return {'x': x, 'y': y, 'dx': dx, 'dy': dy, 'direction': direction,
                'power': power, 'from_player': from_player, 'lx': x, 'ly': y,
                'tick_acc': 0.0, 'bounce': NOT_BOUNCING}

    def run(self, proj, ticks):
        """Advance whole ticks; returns the tick on which it finished."""
        for n in range(1, ticks + 1):
            if not self._advance_flying(proj, TICK):
                return n
        return None


def test_a_level_npcs_fireblast_hurts_the_player_and_explodes():
    h = _Harness(player_xy=(30.0, 20.0))
    proj = h.fly(20.0, 20.5, 3, 2)
    done = h.run(proj, 30)
    assert done == 9
    assert h.hurts == [(2, 1.0, 0.0)]      # power, unit travel direction
    assert len(h.blasts) == 1
    x, y, radius, kind, owner, from_player = h.blasts[0]
    assert (radius, kind, owner, from_player) == (2, 1, 0, False)
    # TServerFlying.cpp:102-103: (28 + 0.9375 - 1, 20.5 + 0.3125 - 1).
    assert (x, y) == (27.9375, 19.8125)
    assert h.sound_mgr.played == ['bomb.wav']       # :105


def test_a_weapon_scripts_shot_never_hurts_its_own_player():
    h = _Harness(player_xy=(30.0, 20.0))
    proj = h.fly(20.0, 20.5, 3, 3, from_player=True)
    assert h.run(proj, 30) is None          # flew straight through (:127)
    assert h.hurts == [] and h.blasts == []


def test_a_player_who_cannot_be_hurt_still_blocks_the_wall_probe():
    h = _Harness(player_xy=(30.0, 20.0), immune=True)
    assert h.run(h.fly(20.0, 20.75, 3, 2), 30) == 10
    assert h.hurts == []
    assert h.blasts == [(28.9375, 20.0625, 2, 1, 0, False)]


def test_a_remote_player_blocks_a_nukes_centre_probe():
    # The wall query includes players (TServerFlying.cpp:276-279;
    # TServerLevel.cpp:2650), even though only the local player can be hurt.
    h = _Harness(player_xy=(0.0, 0.0))
    h.client.players[2] = SimpleNamespace(x=30.0, y=20.0)
    assert h.run(h.fly(20.0, 20.75, 3, 3), 30) == 10
    assert h.hurts == []
    assert h.probes[-1] == ('wall', 30.9375, 21.0625, True)
    assert h.blasts == [(28.9375, 20.0625, 2, 1, 0, False)]


def test_a_wall_explodes_a_nuke_where_it_was_one_tick_earlier():
    h = _Harness(player_xy=(0.0, 0.0))
    h.walls = {(25, 20)}
    proj = h.fly(20.0, 20.0, 3, 3)
    done = h.run(proj, 40)
    assert done is not None
    assert h.hurts == []
    assert len(h.blasts) == 1 and h.blasts[0][2:4] == (2, 1)


def test_power_one_ignores_walls():
    # handleFlyingWallCollision returns at once for power <= 1 (:273); the
    # script callbacks only fire powers 2 and 3, so drive the rule directly.
    h = _Harness(player_xy=(0.0, 0.0))
    h.walls = {(25, 20)}
    proj = h.fly(20.0, 20.0, 3, 1)
    assert h.run(proj, 10) is None and h.blasts == []
    assert all(probe[0] != 'wall' for probe in h.probes)


@pytest.mark.parametrize('direction, start, done', [
    (0, (-0.3125, 1.0625), 2),
    (1, (1.0625, -0.3125), 2),
    (2, (-0.3125, 61.0625), 3),
    (3, (61.0625, -0.3125), 3),
])
def test_leaving_the_level_checks_top_left_and_motion(direction, start, done):
    # Launch offsets leave the perpendicular axis negative. Only travel toward
    # that edge transfers, before all probes (TServerFlying.cpp:378-388).
    h = _Harness(player_xy=(30.0, 30.0))
    proj = h.fly(*start, direction, 3)
    for tick in range(1, done + 1):
        h.probes.clear()
        assert h._advance_flying(proj, TICK) is (tick < done)
        assert [p[0] for p in h.probes] == (
            ['player', 'npc', 'wall'] if tick < done else [])
    assert h.blasts == [] and h.hurts == []


def test_a_bounce_uses_motion_for_the_level_edge_gate():
    h = _Harness(player_xy=(0.0, 0.0))
    proj = h.fly(0.0625, 20.0, 3, 3)
    proj.update(dx=-20.0, bounce=BOUNCE_COUNTER)
    assert h.run(proj, 1) == 1
    assert h.probes == [] and proj['bounce'] == BOUNCE_COUNTER


def test_negative_gmap_world_coordinates_obey_the_direction_gate():
    h = _Harness(player_xy=(30.0, 30.0))
    h.client.in_gmap_segment = True
    h.client.gmap_width, h.client.gmap_height = 2, 2
    proj = h.fly(-2.9375, 20.75, 3, 1)
    assert h.run(proj, 3) is None
    assert proj['lx'] == 0.0625
    assert [p[0] for p in h.probes] == ['player', 'npc'] * 3
    proj['dx'] = -20.0
    h.probes.clear()
    assert h.run(proj, 1) == 1
    assert h.probes == [] and h.blasts == []


def test_several_ticks_in_a_slow_frame_match_one_tick_per_frame():
    h = _Harness(player_xy=(30.0, 20.0))
    slow = _Harness(player_xy=(30.0, 20.0))
    proj = h.fly(20.0, 20.5, 3, 3)
    slow_proj = slow.fly(20.0, 20.5, 3, 3)
    assert h.run(proj, 8) is None
    assert slow._advance_flying(slow_proj, 8 * TICK)
    assert slow.probes == h.probes
    assert h.run(proj, 1) == 1
    assert not slow._advance_flying(slow_proj, 3 * TICK)
    assert slow.probes == h.probes
    assert slow.hurts == h.hurts == [(3, 1.0, 0.0)]
    assert slow.blasts == h.blasts == [(27.9375, 19.8125, 2, 1, 0, False)]
    assert (slow_proj['lx'], slow_proj['ly']) == (proj['lx'], proj['ly'])


@pytest.mark.parametrize("from_player", [False, True])
def test_an_npc_hit_fires_wasshot_then_bounces_back_for_four_ticks(from_player):
    h = _Harness(player_xy=(0.0, 0.0))
    h.npc_cells = {(24, 20): 7}
    proj = h.fly(20.0, 20.0, 3, 3, from_player=from_player)
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


def test_a_bouncing_object_no_longer_tests_player_or_npc():
    h = _Harness(player_xy=(0.0, 0.0))
    h.npc_cells = {(24, 20): 7, (23, 20): 7, (22, 20): 7}
    proj = h.fly(20.0, 20.0, 3, 2)
    h.run(proj, 30)
    assert len([s for s in h.shots if s[0] == 'gs1']) == 1


def test_sprite_position_tracks_the_partial_tick():
    h = _Harness(player_xy=(0.0, 0.0))
    proj = h.fly(10.0, 10.0, 3, 2)
    h._advance_flying(proj, TICK * 1.5)
    assert proj['lx'] == pytest.approx(11.0)
    assert proj['x'] == pytest.approx(11.0 + 20.0 * 0.5 * TICK)


# -- the client-side damage ----------------------------------------------------

def _victim(hearts_ok=True):
    log = SimpleNamespace(hurt=[], cb=[])
    victim = SimpleNamespace(
        can_receive_local_hit=lambda *a, **k: True,
        respond_to_hurt=lambda dmg, gani, knockback=None: log.hurt.append(
            (dmg, knockback)) or hearts_ok,
        hurt_animation="hurt",
        on_hurt=lambda *a: log.cb.append(a))
    return victim, log


@pytest.mark.parametrize("power, damage", [(2, 0.5), (3, 1.0)])
def test_flying_damage_is_the_arrow_damage_for_the_power(power, damage):
    victim, log = _victim()
    # TServerFlying.cpp:222: powers 1 and 3 hit for a heart, the rest half.
    assert CombatMixin.hurt_local_by_flying(victim, power, 1.0, 0.0)
    assert log.hurt == [(damage, (1.0, 0.0))]
    assert log.cb == [(0, damage, 2, 1.0, 0.0)]


def test_flying_damage_respects_immunity():
    victim, log = _victim()
    victim.can_receive_local_hit = lambda *a, **k: False
    assert not CombatMixin.hurt_local_by_flying(victim, 2, 0.0, 1.0)
    assert log.hurt == []


# -- wiring ----------------------------------------------------------------------

def _game():
    client = SimpleNamespace(player=SimpleNamespace(id=1, account="a"),
                             _ARROW_SPEED=20.0, _ARROW_MAX_DISTANCE=128.0)
    game = SimpleNamespace(
        gs1=ClientGS1(None), client=client, player_anim=SimpleNamespace(),
        active_bombs=[], thrown_objects=[], other_thrown_objects=[],
        active_projectiles=[])
    wire_gs1_callbacks(game)
    return game


def test_on_flying_queues_a_ticked_projectile_with_its_shooter():
    game = _game()
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

def test_the_render_loop_runs_a_nuke_into_the_player(monkeypatch):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    pygame.display.set_mode((64, 64))
    from pyreborn import Client
    from pyreborn.pygame_game import GameClient

    game = GameClient(Client('127.0.0.1', 14900, version='6.037'))
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
