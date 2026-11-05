"""Literal official-client hurt geometry, timing, and authority regressions."""

from types import SimpleNamespace
import math

import pytest
from reborn_protocol import PacketBuilder, PLPROP

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.handlers.combat import handle_hurt_player
from pyreborn.handlers.entities import handle_player_props
from pyreborn.hurt import HURT_FLY_PROBES, HURT_SECONDS, HurtState, hurt_vector
from pyreborn.gs1_client import ClientGS1
from pyreborn.tiletypes import TILE_TYPES


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr('time.time', lambda: 100.0)
    c = Client('localhost', 14900)
    c.sent = []
    c._protocol = SimpleNamespace(connected=True, send_packet=lambda p, d=b'': c.sent.append((p, d)) or True)
    c._authenticated = True
    c._current_level_name = c._tiles_level_name = 'hurt.nw'
    c.tiles = [0] * 4096
    c.levels['hurt.nw'] = c.tiles
    c.player.x = c.player.y = 20.0
    return c


class Motion(ActionsMixin, CollisionMixin):
    def __init__(self, client):
        self.client = client


def test_hurtflyd_matches_oracle():
    assert HURT_FLY_PROBES == (
        (0.6, 1.1, 1.5, 1.1, 2.4, 1.1),
        (0.6, 1.1, 0.6, 2.0, 0.6, 2.9),
        (0.6, 2.9, 1.5, 2.9, 2.4, 2.9),
        (2.4, 1.1, 2.4, 2.0, 2.4, 2.9))


@pytest.mark.parametrize('vector,expected', [((0, -3), (0, -1)), ((-2, 0), (-1, 0)),
    ((0, 8), (0, 1)), ((9, 0), (1, 0)), ((0, 0), (1, 0)),
    ((3, 4), (0.6, 0.8))])
def test_hit_vector_normalization(vector, expected):
    assert hurt_vector(*vector) == expected


def test_five_displacements_then_sixth_tick_stops(client):
    assert client.respond_to_hurt(0.5, knockback=(1, 0))
    game = Motion(client)
    for tick in range(1, 7):
        game._advance_hurt(0.05)
        assert client.x == 20 + min(tick, 5)
    assert client.player.action_mode == 3
    assert client.player.animation == 'hurt'
    assert client.player.hurt_timeout == 102.0


def test_diagonal_knockback_is_not_snapped_to_an_axis(client):
    client.respond_to_hurt(0.5, knockback=(1, 1))
    Motion(client)._advance_hurt(0.3)
    assert client.x == pytest.approx(20 + 5 / math.sqrt(2))
    assert client.y == pytest.approx(client.x)


def test_fly_wall_probes_stop_knockback(client):
    wall = next(i for i, kind in enumerate(TILE_TYPES) if kind == 22)
    client.tiles[23 + 22 * 64] = wall
    client.respond_to_hurt(0.5, knockback=(1, 0))
    Motion(client)._advance_hurt(0.3)
    assert (client.x, client.y) == (20, 20)


def test_all_twelve_hurt_probes_are_checked(client):
    game = Motion(client)
    probes = []
    game._is_blocked_at = lambda x, y, **kwargs: probes.append((x, y)) or False
    game._move_hurt_step(0, -1)
    assert probes == [(20 + row[i], 19 + row[i + 1])
                      for row in HURT_FLY_PROBES for i in (0, 2, 4)]


def test_fixed_ticks_independent_of_render_rate():
    a, b = HurtState(), HurtState()
    a.start(1, 0, 100)
    b.start(1, 0, 100)
    moves_a, moves_b = [], []
    a.advance(0.3, lambda *v: moves_a.append(v))
    for _ in range(18):
        b.advance(1 / 60, lambda *v: moves_b.append(v))
    assert moves_a == moves_b == [(1, 0)] * 5


def test_immunity_and_input_lock_have_distinct_lengths(client, monkeypatch):
    client.respond_to_hurt(0.5)
    assert HURT_SECONDS == 2.0
    assert client.player.hurt.input_locked(100.54)
    assert not client.player.hurt.input_locked(100.55)
    assert not client.respond_to_hurt(0.5)
    assert client.player.hearts == 2.5
    monkeypatch.setattr('time.time', lambda: 102.0)
    assert client.respond_to_hurt(0.5)
    assert client.player.hearts == 2.0


@pytest.mark.parametrize('state', ['paused', 'swim', 'lava', 'dead', 'action_hurt', 'action_swim'])
def test_no_hurt_states_refuse_local_reports(client, state):
    if state == 'paused':
        client.player.status = 1
    elif state.startswith('action_'):
        client.player.action_mode = 3 if state == 'action_hurt' else 10
    else:
        client.player.animation = state
    assert not client.respond_to_hurt(0.5)
    assert client.player.hearts == 3
    assert not client.sent


@pytest.mark.parametrize('mechanic', ['hurt 1;', 'hitplayer 0,1,10,10;', 'putexplosion 2,20,20;'])
def test_script_damage_cannot_bypass_immunity_with_second_hp_write(client, mechanic):
    gs1 = ClientGS1(client)
    client.npcs[1] = {'x': 20, 'y': 20}
    gs1.load_script('npc_1', 'if (playertouchsme) { ' + mechanic + ' }', npc_id=1)
    assert client.respond_to_hurt(0.5)
    gs1.trigger_npc_event(1, 'playertouchsme')
    assert client.player.hearts == 2.5
    # Script explosions may report the explosion itself, never another HP loss.
    assert client.player.hurt.generation == 1


def test_server_hp_and_forced_damage_apply_inside_window(client):
    client.respond_to_hurt(0.5)
    props = PacketBuilder()
    props.write_gchar(PLPROP.CURPOWER)
    props.write_gchar(4)  # two hearts, forced by the server
    handle_player_props(client, props.build())
    assert client.player.hearts == 2
    hurt = PacketBuilder()
    hurt.write_gshort(99)
    for value in (1, 0, 1):
        hurt.write_gchar(value)
    handle_hurt_player(client, hurt.build())
    assert client.player.hearts == 1.5
    assert client.player.hurt.generation == 1  # no second fly


def test_arrow_local_hit_is_suppressed_during_window(client):
    client.respond_to_hurt(0.5)
    client._resolve_pending_arrow_hit({'owner_id': 99, 'dx': 1, 'dy': 0})
    assert client.player.hearts == 2.5


def test_two_forced_hits_from_same_attacker_both_apply(client):
    packet = PacketBuilder()
    packet.write_gshort(99)
    for value in (1, 0, 1):
        packet.write_gchar(value)
    handle_hurt_player(client, packet.build())
    handle_hurt_player(client, packet.build())
    assert client.player.hearts == 2.0
    assert client.player.hurt.generation == 1


def test_pvp_saint_and_community_gates_do_not_block_environment(client):
    client.player.ap = 100
    assert not client.can_receive_local_hit(99, pvp=True)
    assert client.can_receive_local_hit()
    client.player.ap = 50
    client.player.community = 'friends'
    client.players[99] = {'community': 'friends'}
    assert not client.can_receive_local_hit(99, pvp=True)
    client.player.community = 'others'
    client.player.allies = ('friends',)
    assert not client.can_receive_local_hit(99, pvp=True)
    client.players[99]['community'] = ''
    client.level_nopk = True
    assert not client.can_receive_local_hit(99, pvp=True)


def test_pvp_requires_current_level(client):
    client._current_level_name = ''
    assert not client.can_receive_local_hit(99, pvp=True)


def test_ghost_refuses_local_damage_reports(client):
    client.ghost_mode = True
    assert not client.respond_to_hurt(0.5)
    assert client.player.hearts == 3


def test_knockback_crosses_gmap_seam_with_local_wire_position(client):
    client.gmap_width, client.gmap_height = 2, 1
    client.gmap_grid.update({(0, 0): 'hurt.nw', (1, 0): 'next.nw'})
    client.levels['next.nw'] = [0] * 4096
    client.player.x = 63
    client.respond_to_hurt(0.5, knockback=(1, 0))
    Motion(client)._advance_hurt(0.05)
    assert client.x == 64
    assert client._current_level_name == 'next.nw'


def test_server_max_hp_clamp_is_not_suppressed(client):
    client.respond_to_hurt(0.5)
    client.player.update_from_props({'max_hearts': 1.0})
    assert client.player.hearts == 1.0


def test_composed_game_hurt_and_forced_death_render(client):
    from pyreborn.pygame_game import GameClient
    game = GameClient(client)
    assert client.respond_to_hurt(0.5, knockback=(1, 0))
    client.on_hurt(99, 0.5, 0, 1, 0)
    assert game.current_anim_name == 'hurt'
    game._update_animations(0.05)
    game._render()
    assert client.x == 21
    # A forced second notification inside immunity can still kill us.
    assert client.respond_to_hurt(99, server_forced=True)
    client.on_hurt(99, 99, 0, 0, 0)
    assert game.current_anim_name == 'dead'
    game._update_animations(0.05)
    game._render()


def test_pushaway_replaces_fly_vector_without_damage_or_new_immunity(client):
    from pyreborn.pygame_game import GameClient
    game = GameClient(client)
    assert client.respond_to_hurt(0.5)
    until = client.player.hurt.until
    client.on_pushaway(-0.5, 0)
    game._advance_hurt(0.3)
    assert client.x == 17.5
    assert client.player.hearts == 2.5
    assert client.player.hurt.until == until


def test_hurt_motion_keeps_player_checks_disabled(client):
    # TPlayer.cpp:2907 uses isOnWall(..., false) during knockback.
    client.players[7] = {'x': 22, 'y': 20}
    assert Motion(client)._move_hurt_step(1, 0)
    assert client.x == 21
