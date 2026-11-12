"""Combat checks against the verified client functions and content steps."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLSTATUS

from pyreborn import Client
from pyreborn.arrowflight import ARROW_SIZES, overlaps_player, shield_blocks
from pyreborn.game.input import InputMixin
from pyreborn.packets import PacketID
from pyreborn.sword import SwordState, owns_spin, play_sword_pose
from pyreborn.throwing import advance_throw, throw_hits
from pyreborn.tiletypes import TILE_TYPES


@pytest.fixture
def client(sim_time, monkeypatch):
    sim_time(lambda: 100.0)
    c = Client('localhost', 14900)
    c._authenticated = True
    c._protocol = SimpleNamespace(connected=True, send_packet=Mock(return_value=True),
                                  recv_packets=lambda _: [])
    c._current_level_name = c._tiles_level_name = 'combat.nw'
    c.tiles = [0] * 4096
    c.levels['combat.nw'] = c.tiles
    c.player.x = c.player.y = 30.0
    return c


def test_sword_tests_all_five_ticks_and_late_entry(sim_time, client, monkeypatch):
    client.players[7] = {'x': 40, 'y': 30}
    probe = Mock(wraps=client._sword_hit_players)
    client._sword_hit_players = probe
    assert client.sword_attack(3)
    assert client.player.action_mode == 6
    client.players[7]['x'] = 33
    client.players[7]['y'] = 31
    for now in (100.05, 100.1, 100.15, 100.2, 100.25):
        sim_time(lambda: now)
        client.run_tick()   # one simulation tick of the library
    assert probe.call_count == 5
    assert client.player.action_mode == 0
    hits = [call for call in client._protocol.send_packet.call_args_list
            if call.args[0] == PacketID.PLI_HURTPLAYER]
    assert len(hits) == 1  # victim immunity remains two seconds
    # attack packet direction bytes carry half of the radial delta.
    assert hits[0].args[1][2:4] == bytes((32 + 24, 32 + 8))


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


def test_spin_sweeps_bush_probes_and_npcs(client):
    client.player.status |= 0x40
    client.sword_attack(0)
    client._sword_cut_bushes = Mock()
    client._sword_hit_npcs = Mock()
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


def test_saint_target_blocks_sword_but_saint_attacker_is_not_gated(client):
    client.player.ap = 100
    client.players[7] = {'x': 33, 'y': 30, 'ap': 100}
    client.attack_player = Mock()
    client._sword_hit_players(3)
    client.attack_player.assert_not_called()
    client.players[7]['ap'] = 50
    client._sword_hit_players(3)
    client.attack_player.assert_called_once()


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
    mirrored = [call for call in client._protocol.send_packet.call_args_list
                if call.args[0] == PacketID.PLI_ARROWADD]
    assert len(mirrored) == (1 if shield == 2 else 0)
    client._tick_arrow_sims(.3 + client._ARROW_HIT_GRACE)
    assert client.player.hearts == (2 if shield == 2 else 3)


def test_arrow_survives_twenty_ticks(client):
    client._start_arrow_sim({'x': 0, 'y': 0, 'direction': 3}, now=0)
    client._tick_arrow_sims(1.05)
    assert len(client._arrow_sims) == 1
    assert client._arrow_sims[0]['x'] == pytest.approx(21)


def throw_game(client, tile_type=0):
    tile = next(i for i, kind in enumerate(TILE_TYPES) if kind == tile_type)
    return SimpleNamespace(client=client, _get_tile_at=lambda x, y: tile,
                           _is_tile_blocking=lambda t: TILE_TYPES[t] >= 20,
                           gs1=SimpleNamespace(trigger_npc_event=Mock()))


def obj(direction=3):
    dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[direction]
    return {'x': 10.5, 'y': 11.0, 'dx': dx, 'dy': dy,
            'dist': 0, 'range': 9, 'z': 2.75, 'z0': 2.75, 'type': 'stone'}


def test_throw_takes_nine_ticks_and_passes_type_twenty(client):
    game, flying = throw_game(client, 20), obj()
    assert not advance_throw(game, flying, .049)
    assert flying['x'] == 10.5
    assert not advance_throw(game, flying, .351)
    assert flying['x'] == 18.5
    assert advance_throw(game, flying, .05)
    assert flying['x'] == 19.5
    assert flying['dist'] == 9


def test_throw_cannot_tunnel_through_wall(client):
    game, flying = throw_game(client, 22), obj()
    assert advance_throw(game, flying, .45)
    assert flying['x'] == 11.5


@pytest.mark.parametrize('hearts,damage', [(0.5, .5), (1, .5), (1.5, 1), (3, 1)])
def test_throw_damage_depends_on_victim_hearts(client, hearts, damage):
    game, flying = throw_game(client), obj()
    client.players[8] = {'x': 12, 'y': 10, 'hearts': hearts}
    client.attack_player = Mock()
    assert advance_throw(game, flying, .05)
    client.attack_player.assert_called_once_with(8, damage=damage, knockback_x=1, knockback_y=0)


def test_throw_uses_point_npc_probe_before_player_hit(client):
    game, flying = throw_game(client), obj()
    client.npcs[9] = {'x': 12.4, 'y': 11.9, 'width': .2, 'height': .2}
    client.players[8] = {'x': 12, 'y': 10}
    client.attack_player = Mock()
    assert advance_throw(game, flying, .05)
    game.gs1.trigger_npc_event.assert_called_once_with(9, 'waspelt')
    client.attack_player.assert_not_called()
    assert client.npcs[9]['pelt_kind'] == 'stone'


def test_throw_hit_boundary_is_strict():
    assert throw_hits(12.499, 11, 10, 10)
    assert not throw_hits(12.5, 11, 10, 10)


def test_pause_p_toggles_only_status_bit_and_locks_input(client, monkeypatch):
    class Game(InputMixin):
        pass
    game = Game()
    game.client = client
    game.is_moving = True
    client.player.status = 4
    game._handle_key_press(SimpleNamespace(key=pygame.K_p))
    assert client.player.status == 5
    assert not game.is_moving
    assert not client.sword_attack(0)
    assert client._protocol.send_packet.call_args.args[0] == PacketID.PLI_PLAYERPROPS
    game.typing = game.show_player_list = game.show_server_list = False
    game.dialogue_text = game.pm_target_id = None
    game.inventory_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: SimpleNamespace(visible=False)
    game._admin_overlay_captures_keys = game._gs2_gui_captures_keys = lambda: False
    game._revive_on_input = lambda *args: False
    game._feed_gs1_input = Mock()
    game._auto_pickup_items = Mock()
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_UP: True}))
    game._handle_input(100)
    game._auto_pickup_items.assert_not_called()
    game._handle_key_press(SimpleNamespace(key=pygame.K_p))
    assert client.player.status == 4


@pytest.mark.parametrize('available,pose', [(True, 'spin'), (False, 'idle')])
def test_spin_pose_fallback_keeps_action_state(client, available, pose):
    client.player.animation = 'spin'
    client.player.action_mode = 13
    game = SimpleNamespace(client=client, gani_parser=SimpleNamespace(
        parse=lambda name: object() if available else None),
        _play_action_animation=Mock())
    play_sword_pose(game)
    game._play_action_animation.assert_called_once_with(pose, broadcast=False)
    assert client.player.action_mode == 13


@pytest.mark.parametrize('pose', ['spin', 'idle'])
def test_spin_locks_held_movement_even_during_fallback(client, monkeypatch, pose):
    class Game(InputMixin):
        pass
    game = Game()
    game.client = client
    game.typing = game.show_player_list = game.show_server_list = False
    game.dialogue_text = game.pm_target_id = None
    game.inventory_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: SimpleNamespace(visible=False)
    game._admin_overlay_captures_keys = game._gs2_gui_captures_keys = lambda: False
    game._revive_on_input = lambda *args: False
    game._feed_gs1_input = game._fire_gs1_keypress_queue = Mock()
    game._auto_pickup_items = game._clear_grab_state = game._clear_push_hold = Mock()
    game.gs1 = SimpleNamespace(default_movement=True)
    game.current_anim_name = pose
    game.key_just_pressed = {}
    game._move = Mock()
    client.player.action_mode = 13
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_RIGHT: True}))
    game._handle_input(100)
    game._move.assert_not_called()
    assert game.is_moving is False


def test_remote_throw_uses_shared_hurt_grace_and_duplicate_guard(client):
    game, flying = throw_game(client), obj()
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


def test_throw_checks_bomb_before_npc_or_player(client):
    game, flying = throw_game(client), obj()
    client.bombs['combat.nw'] = {1: {'x': 12, 'y': 12}}
    client.players[8] = {'x': 12, 'y': 10}
    client.attack_player = Mock()
    assert advance_throw(game, flying, .05)
    client.attack_player.assert_not_called()
