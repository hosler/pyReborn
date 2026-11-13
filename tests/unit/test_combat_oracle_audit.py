from collections import defaultdict
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLSTATUS

from offline_game import key_event, spy
from pyreborn.arrowflight import ARROW_SIZES, overlaps_player, shield_blocks
from pyreborn.packets import PacketID
from pyreborn.sword import SwordState, owns_spin, play_sword_pose
from pyreborn.throwing import advance_throw, throw_hits
from pyreborn.tiletypes import TILE_TYPES


@pytest.fixture
def game(sim_time, make_game):
    """A real offline game in 'combat.nw' on an open board, the player at
    (30, 30), simulation time pinned at 100 and nothing sent yet."""
    sim_time(lambda: 100.0)
    g = make_game(level='combat.nw', player_xy=(30.0, 30.0),
                  tiles=lambda tx, ty: 0)
    g.client._protocol.sent.clear()
    return g


@pytest.fixture
def client(game):
    return game.client


def sent_with(client, packet_id):
    """The payloads of every packet of ``packet_id`` the client sent."""
    return [data for pid, data in client._protocol.sent if pid == packet_id]


def test_sword_tests_all_five_ticks_and_late_entry(sim_time, client, monkeypatch):
    client.players[7] = {'x': 40, 'y': 30}
    probe = spy(monkeypatch, client, '_sword_hit_players')
    assert client.sword_attack(3)
    assert client.player.action_mode == 6
    client.players[7]['x'] = 33
    client.players[7]['y'] = 31
    for now in (100.05, 100.1, 100.15, 100.2, 100.25):
        sim_time(lambda: now)
        client.run_tick()   # one simulation tick of the library
    assert len(probe) == 5
    assert client.player.action_mode == 0
    hits = sent_with(client, PacketID.PLI_HURTPLAYER)
    assert len(hits) == 1  # victim immunity remains two seconds
    # attack packet direction bytes carry half of the radial delta.
    assert hits[0][2:4] == bytes((32 + 24, 32 + 8))


def test_spin_uses_item_24_and_a_second_press(client):
    client.sword_attack(0)
    assert not owns_spin(client)
    client.sword_attack(0)
    assert client.player.action_mode == 6
    client.player.status |= 0x40
    client.sword_attack(0)
    assert client.player.action_mode == 13
    assert client.player.animation == 'spin'
    assert client._sword_state.duration == .65
    assert not client.sword_attack(0)


def test_spin_rotates_every_two_steps_and_uses_thirteen_frames():
    state = SwordState(0, 3, spin=True)
    assert [direction for _, direction in state.due(1)] == [3, 3, 0, 0, 1, 1, 2, 2, 3, 3, 3, 3, 3]


def test_spin_sweeps_bush_probes_and_npcs(client, monkeypatch):
    client.player.status |= 0x40
    client.sword_attack(0)
    monkeypatch.setattr(client, '_sword_cut_bushes', Mock())
    monkeypatch.setattr(client, '_sword_hit_npcs', Mock())
    client.sword_attack(0)
    client._tick_sword_attack(100.6)
    sweeps = [call.args[0] for call in client._sword_cut_bushes.call_args_list
              if call.kwargs.get('spinning')]
    assert sweeps == [0, 0, 1, 1, 2, 2, 3, 3, 0, 0, 0, 0, 0]
    assert client._sword_hit_npcs.call_count == 3


def test_held_sword_does_not_charge_or_launch_spin(client):
    client.player.status |= 0x40
    client.sword_attack(0)
    client._tick_sword_attack(101)
    assert client.player.action_mode == 0
    assert client.player.animation != 'spin'


@pytest.mark.parametrize('mode,carry', [(2, 0), (14, 2), (14, 3)])
def test_jump_and_hide_are_not_nohurt_gates_in_this_oracle(client, mode, carry):
    # TPlayer.cpp:3013-3043 tests modes 3 and 10, NOT 2 or 14.
    client.player.action_mode, client.player.carry_sprite = mode, carry
    assert not client.player.no_hurt()


@pytest.mark.parametrize('ap,allowed', [(19, False), (20, False), (39, False), (40, True), (100, True)])
def test_healing_threshold_is_forty(client, ap, allowed):
    client.player.hearts = 1
    client.player.ap = ap
    assert client.send_hearts(2) == allowed
    assert client.player.hearts == (2 if allowed else 1)


def test_saint_target_blocks_sword_but_saint_attacker_is_not_gated(client, monkeypatch):
    client.player.ap = 100
    client.players[7] = {'x': 33, 'y': 30, 'ap': 100}
    attack = Mock()
    monkeypatch.setattr(client, 'attack_player', attack)
    client._sword_hit_players(3)
    attack.assert_not_called()
    client.players[7]['ap'] = 50
    client._sword_hit_players(3)
    attack.assert_called_once()


@pytest.mark.parametrize('direction', range(4))
def test_arrow_rect_edges_and_exact_shield_facing(client, direction):
    w, h = ARROW_SIZES[direction]
    assert not overlaps_player(30.5 - w, 31.5, direction, 30, 30)
    assert overlaps_player(30.501 - w, 31.5, direction, 30, 30)
    assert not overlaps_player(31, 31 - h, direction, 30, 30)
    client.player.shield_power = 3
    for facing in range(4):
        client.player.direction = facing
        assert shield_blocks(client.player, direction, 1) == (facing == (direction + 2) % 4)
        assert not shield_blocks(client.player, direction, 2)
    client.player.animation = 'sword'
    assert not shield_blocks(client.player, direction, 1)


@pytest.mark.parametrize('shield', [1, 2])
def test_shield_deflects_or_mirrors_with_literal_damage_fallthrough(client, shield):
    client.player.shield_power, client.player.direction = shield, 1
    client._start_arrow_sim({'x': 26, 'y': 31.5, 'direction': 3}, now=0)
    client._tick_arrow_sims(.3)
    assert len(client._pending_arrow_hits) == (1 if shield == 2 else 0)
    assert client.player.hearts == 3
    mirrored = sent_with(client, PacketID.PLI_ARROWADD)
    assert len(mirrored) == (1 if shield == 2 else 0)
    client._tick_arrow_sims(.3 + client._ARROW_HIT_GRACE)
    assert client.player.hearts == (2 if shield == 2 else 3)


def test_arrow_survives_twenty_ticks(client):
    client._start_arrow_sim({'x': 0, 'y': 0, 'direction': 3}, now=0)
    client._tick_arrow_sims(1.05)
    assert len(client._arrow_sims) == 1
    assert client._arrow_sims[0]['x'] == pytest.approx(21)


def throw_game(game, tile_type=0):
    """``game`` with its whole board set to the first tile of ``tile_type`` and
    NPC events recorded (``game.gs1.trigger_npc_event`` is a Mock)."""
    tile = next(i for i, kind in enumerate(TILE_TYPES) if kind == tile_type)
    game.client.tiles[:] = [tile] * 4096
    game.gs1.trigger_npc_event = Mock()
    return game


def obj(direction=3):
    dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[direction]
    return {'x': 10.5, 'y': 11.0, 'dx': dx, 'dy': dy,
            'dist': 0, 'range': 9, 'z': 2.75, 'z0': 2.75, 'type': 'stone'}


def test_throw_takes_nine_ticks_and_passes_type_twenty(client, game):
    game, flying = throw_game(game, 20), obj()
    assert not advance_throw(game, flying, .049)
    assert flying['x'] == 10.5
    assert not advance_throw(game, flying, .351)
    assert flying['x'] == 18.5
    assert advance_throw(game, flying, .05)
    assert flying['x'] == 19.5
    assert flying['dist'] == 9


def test_throw_cannot_tunnel_through_wall(client, game):
    game, flying = throw_game(game, 22), obj()
    assert advance_throw(game, flying, .45)
    assert flying['x'] == 11.5


@pytest.mark.parametrize('hearts,damage', [(0.5, .5), (1, .5), (1.5, 1), (3, 1)])
def test_throw_damage_depends_on_victim_hearts(client, hearts, damage, game, monkeypatch):
    game, flying = throw_game(game), obj()
    client.players[8] = {'x': 12, 'y': 10, 'hearts': hearts}
    attack = Mock()
    monkeypatch.setattr(client, 'attack_player', attack)
    assert advance_throw(game, flying, .05)
    attack.assert_called_once_with(8, damage=damage, knockback_x=1, knockback_y=0)


def test_throw_uses_point_npc_probe_before_player_hit(client, game, monkeypatch):
    game, flying = throw_game(game), obj()
    client.npcs[9] = {'x': 12.4, 'y': 11.9, 'width': .2, 'height': .2}
    client.players[8] = {'x': 12, 'y': 10}
    attack = Mock()
    monkeypatch.setattr(client, 'attack_player', attack)
    assert advance_throw(game, flying, .05)
    game.gs1.trigger_npc_event.assert_called_once_with(9, 'waspelt')
    attack.assert_not_called()
    assert client.npcs[9]['pelt_kind'] == 'stone'


def test_throw_hit_boundary_is_strict():
    assert throw_hits(12.499, 11, 10, 10)
    assert not throw_hits(12.5, 11, 10, 10)


def test_pause_p_toggles_only_status_bit_and_locks_input(game, client, monkeypatch):
    game.is_moving = True
    client.player.status = 4
    game._handle_key_press(key_event(pygame.K_p))
    assert client.player.status == 5
    assert not game.is_moving
    assert not client.sword_attack(0)
    assert client._protocol.sent[-1][0] == PacketID.PLI_PLAYERPROPS
    monkeypatch.setattr(game, '_revive_on_input', lambda *args: False)
    pickups = spy(monkeypatch, game, '_auto_pickup_items')
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_UP: True}))
    game._handle_input(100)
    assert pickups == []
    game._handle_key_press(key_event(pygame.K_p))
    assert client.player.status == 4


@pytest.mark.parametrize('available,pose', [(True, 'spin'), (False, 'idle')])
def test_spin_pose_fallback_keeps_action_state(game, client, monkeypatch, available, pose):
    client.player.animation = 'spin'
    client.player.action_mode = 13
    monkeypatch.setattr(game.gani_parser, 'parse',
                        lambda name: object() if available else None)
    play = Mock()
    monkeypatch.setattr(game, '_play_action_animation', play)
    play_sword_pose(game)
    play.assert_called_once_with(pose, broadcast=False)
    assert client.player.action_mode == 13


@pytest.mark.parametrize('pose', ['spin', 'idle'])
def test_spin_locks_held_movement_even_during_fallback(game, client, monkeypatch, pose):
    monkeypatch.setattr(game, '_revive_on_input', lambda *args: False)
    moves = spy(monkeypatch, game, '_move')
    game.current_anim_name = pose
    game.key_just_pressed = {}
    client.player.action_mode = 13
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_RIGHT: True}))
    game._handle_input(100)
    assert moves == []
    assert game.is_moving is False


def test_remote_throw_uses_shared_hurt_grace_and_duplicate_guard(client, game):
    game, flying = throw_game(game), obj()
    client.player.x, client.player.y = 12, 10
    flying['owner_id'] = 8
    assert advance_throw(game, flying, .05, remote=True)
    assert client.player.hearts == 3
    hit, = client._pending_arrow_hits
    assert hit['damage'] == 1
    client._tick_arrow_sims(100.25)
    assert client.player.hearts == 2
    # A repeated local report within the hurt window is suppressed.
    client._resolve_pending_arrow_hit(hit)
    assert client.player.hearts == 2


def test_throw_checks_bomb_before_npc_or_player(client, game, monkeypatch):
    game, flying = throw_game(game), obj()
    client.bombs['combat.nw'] = {1: {'x': 12, 'y': 12}}
    client.players[8] = {'x': 12, 'y': 10}
    attack = Mock()
    monkeypatch.setattr(client, 'attack_player', attack)
    assert advance_throw(game, flying, .05)
    attack.assert_not_called()
