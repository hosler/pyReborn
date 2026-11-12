"""Batch A observer ordering, timed NPC gestures, restart and ghost regressions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLPROP

from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.game.render_collect import EntityCollectMixin
from pyreborn.handlers.combat import handle_bomb_del
from pyreborn.handlers.session import handle_ghost_mode
from pyreborn.gs1_client import ClientGS1
from pyreborn.packets import PacketID, build_bomb_del
from .test_lift_oracle import Game
from .test_push_grab_pull import _harness_facing_wall


@pytest.mark.parametrize('carry_update_first', [False, True])
def test_bomb_pickup_never_explodes_for_observer(sim_time, monkeypatch, carry_update_first):
    sim_time(lambda: 100.0)
    game = Game()
    wire_client_callbacks(game)
    bomb = game._add_remote_bomb({'x': 10, 'y': 10, 'timer_ms': 2000}, now=100)
    game.client.bombs['throw.nw'] = {0: bomb}
    owner = {'x': 8.5, 'y': 10, 'direction': 0, 'carry_sprite': 0 if carry_update_first else -1}
    game.client.players[8] = owner
    handle_bomb_del(game.client, build_bomb_del(10, 10))
    assert not bomb['exploded']
    assert not game.client.bombs['throw.nw']
    game.sound_mgr.play.assert_not_called()
    game._start_camera_shake.assert_not_called()
    if carry_update_first:
        assert owner['_carried_bomb'] is bomb
        assert bomb['carried_by'] == 8
    else:
        assert game.active_bombs == []
        owner['carry_sprite'] = 0
        assert not owner.get('_carried_bomb')


def test_bomb_removal_uses_packet_segment_on_gmap(sim_time, monkeypatch):
    sim_time(lambda: 100.0)
    game = Game()
    wire_client_callbacks(game)
    game.client.gmap_grid = {(1, 0): 'throw.nw'}
    game.client.gmap_width = 2
    game.client.player.x = 84
    bomb = game._add_remote_bomb({'x': 74, 'y': 10, 'timer_ms': 2000}, now=100)
    handle_bomb_del(game.client, build_bomb_del(10, 10))
    assert not game.active_bombs and not bomb['exploded']


def test_push_countdown_and_repeated_directional_event(sim_time, monkeypatch):
    now = [100.0]
    sim_time(lambda: now[0])
    client, game = _harness_facing_wall()
    client.triggeraction = Mock()
    game._update_push_hold(0, -1)
    assert game._push_counter == 38
    now[0] += .999
    game._update_push_hold(0, -1)
    assert game._push_counter == 19 and not game.is_pushing
    client.triggeraction.assert_not_called()
    now[0] = 101
    game._update_push_hold(0, -1)
    assert game._push_counter == 18 and game.current_anim_name == 'push'
    client.triggeraction.assert_called_once_with('push,0', 31.5, 20.0)
    now[0] += 1
    game._update_push_hold(0, -1)
    assert client.triggeraction.call_count == 2  # TPlayer.cpp:7558-7561
    game._clear_push_hold()
    game._update_push_hold(0, -1)
    assert game._push_counter == 38


def test_pull_counter_19_and_local_script_parameters(sim_time, monkeypatch):
    now = [100.0]
    sim_time(lambda: now[0])
    client, game = _harness_facing_wall()
    game.gs1 = ClientGS1(client)
    client.npcs[10001] = {'x': 30, 'y': 19, 'visible': True}
    game.gs1.shapes[10001] = (3, 3, [])
    game.gs1.load_script('pullable', 'if (actionpull) { this.hits++; this.dir=#p(0); }', npc_id=10001)
    client.triggeraction = Mock()
    game._update_grab_pull_state(0, 0)
    assert game._pull_counter == 1 and client.player.action_mode == 5
    game._update_grab_pull_state(0, 1)
    assert game._pull_counter == 2 and game.current_anim_name == 'pull'
    now[0] += .849
    game._update_grab_pull_state(0, 1)
    client.triggeraction.assert_not_called()
    now[0] = 100.85
    game._update_grab_pull_state(0, 1)
    assert game._pull_counter == 19 and game._grab_direction == 0
    client.triggeraction.assert_called_once_with('pull,2', 31.5, 19.5)
    entry = game.gs1._progs['pullable']
    assert entry['scopes']['this']['hits'] == 1
    assert entry['scopes']['this']['dir'] == 2
    game._update_grab_pull_state(0, 1)
    assert client.triggeraction.call_count == 1
    game._clear_grab_state()
    assert client.player.action_mode == 0


def test_grab_accepts_nonblocking_npc_but_never_player(monkeypatch):
    client, game = _harness_facing_wall()
    game._effective_tile_type = lambda x, y: 0
    game.gs1 = ClientGS1(client)
    client.npcs[10001] = {'x': 30, 'y': 19, 'image': 'box.png', 'visible': True, 'dontblock': True}
    assert game._pull_wall_before(0)
    game._player_blocks = lambda x, y: True
    assert not game._pull_wall_before(0)


@pytest.mark.parametrize('ap,maximum,expected', [(0, 10, 3), (19, 10, 3), (20, 10, 5),
    (39, 10, 5), (20, 4, 4), (39, 3, 3), (40, 10, 10), (100, 10, 10)])
def test_client_restart_predicts_alignment_hp(ap, maximum, expected):
    game = Game()
    player = game.client.player
    player.ap, player.max_hearts = ap, maximum
    object.__setattr__(player, 'hearts', 0)
    game.client._send_appearance_prop = Mock()
    game._update_death_state(100)
    assert not player.status & 8
    game._update_death_state(101.399)
    assert not player.status & 8
    game._update_death_state(101.4)
    assert player.status & 8
    keys = {k: True for k in (pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN,
                             pygame.K_RIGHT, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_SPACE)}
    assert not game._revive_on_input(101.499, keys)
    assert game._revive_on_input(101.5, keys)
    assert player.hearts == expected
    assert game.client._send_appearance_prop.call_args.args == (PLPROP.CURPOWER, expected * 2)


@pytest.mark.parametrize('mode', [0, 1, 2, 3])
def test_ghost_packet_retains_integer_mode(mode):
    game = Game()
    wire_client_callbacks(game)
    handle_ghost_mode(game.client, bytes([mode + 32]))
    assert game.client.ghost_mode == mode and game.ghost_mode == mode
    handle_ghost_mode(game.client, b'')
    assert game.client.ghost_mode == mode


@pytest.mark.parametrize('mode', [1, 2])
def test_ghost_blocks_actions_before_mutation_or_packet(mode):
    game = Game()
    game.carry()
    game.client.ghost_mode = mode
    game.client._protocol.send_packet.reset_mock()
    assert not game.client.sword_attack()
    assert not game.client.pickup_item()
    assert not game.client.put_bomb()
    assert not game.client.shoot_arrow()
    assert game._auto_pickup_items() == 0
    assert not game._pickup_ground_item()
    game._throw_object()
    game._try_grab()
    game._try_pickup(1, 0)
    game._use_weapon()
    assert not game._lift_in_front(3)
    assert game.client.player.is_carrying() and not game.thrown_objects
    game.client._protocol.send_packet.assert_not_called()
    game.sound_mgr.play.assert_not_called()


@pytest.mark.parametrize('mode,count', [(0, 1), (1, 1), (2, 0)])
def test_ghost_mode_two_hides_local_player_only(mode, count):
    game = SimpleNamespace(client=SimpleNamespace(ghost_mode=mode, player=object()),
                           camera=SimpleNamespace(world_to_screen=lambda x, y: (x, y)),
                           _player_render_pos=(10, 20), visual_y=20,
                           _depth_sort_key=lambda y, h: y + h)
    entities = []
    EntityCollectMixin._collect_local_player(game, entities, SimpleNamespace())
    assert len(entities) == count


@pytest.mark.parametrize('mode,visible', [(0, True), (1, True), (2, False)])
def test_real_offline_frame_respects_ghost_visibility(mode, visible):
    from pyreborn import Client
    from pyreborn.pygame_game import GameClient
    game = GameClient(Client())
    game.client.ghost_mode = mode
    game._render_player = Mock(wraps=game._render_player)
    game._render()
    assert bool(game._render_player.call_count) is visible
