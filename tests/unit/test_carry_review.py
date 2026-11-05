"""Regressions for carry-state and thrown-bomb review findings."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from reborn_protocol import PLPROP

from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.gs1_client.host_builtins import BuiltinsMixin
from pyreborn.gs2_client.host_objects import HostObjectsMixin
from pyreborn.packets import PacketID, build_explosion_add
from .test_lift_oracle import Game


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr('time.time', lambda: 100.0)
    return Game()


@pytest.mark.parametrize('code,kind', [(-1, None), (0, None), (200, None),
    (1, 'bush'), (3, 'stone'), (5, 'vase'), (7, 'sign'), (201, 'blackstone')])
def test_client_carry_builtins_use_decoded_codes(game, code, kind):
    game.client.player.carry_sprite = code
    gs1 = SimpleNamespace(_player=game.client.player)
    gs2 = SimpleNamespace(rt2=SimpleNamespace(client=game.client))
    assert BuiltinsMixin._pb_carrying(gs1, 'carrying', [], None) is (code != -1)
    assert HostObjectsMixin._obj_iscarrying(gs2, 'iscarrying') is (code != -1)
    for name in ('bush', 'stone', 'vase', 'sign', 'blackstone'):
        flag = 'carries' + name
        assert BuiltinsMixin._pb_carrying(gs1, flag, [], None) is (kind == name)
        assert HostObjectsMixin._obj_carry_kind(gs2, flag) is (kind == name)


@pytest.mark.parametrize('alias,code,flag', [('rock', 3, 'carriesstone'), ('pot', 5, 'carriesvase')])
def test_legacy_pickup_aliases_assign_decoded_carry_codes(game, alias, code, flag):
    game.client.player.pickup_object(alias, (1, 2, 3, 4), (10, 10))
    assert game.client.player.carry_sprite == code
    gs1 = SimpleNamespace(_player=game.client.player)
    assert BuiltinsMixin._pb_carrying(gs1, flag, [], None)


@pytest.mark.parametrize('code', [-1, 0, 200, 1, 201])
@pytest.mark.parametrize('owned', [False, True])
def test_canspin_tracks_ability_instead_of_carry_sprite(game, code, owned):
    game.client.player.carry_sprite = code
    game.client.player.status = 0x40 if owned else 0
    host = SimpleNamespace(rt2=SimpleNamespace(client=game.client))
    assert HostObjectsMixin._obj_window_state(host, 'canspin') is owned


@pytest.mark.parametrize('in_flight', [False, True])
def test_held_bomb_detonation_reports_explosion_once(game, in_flight):
    bomb = game.bomb()
    assert game._lift_in_front(3)
    if in_flight:
        game._throw_object()
        game._render_world_object = Mock()
        game._update_and_render_thrown(.05)
    else:
        game._render_bombs()
    point = bomb['x'], bomb['y']
    assert game._detonate_bomb(bomb)
    assert not game._detonate_bomb(bomb)
    reports = [c for c in game.client._protocol.send_packet.call_args_list
               if c.args[0] == PacketID.PLI_EXPLOSION]
    assert len(reports) == 1
    assert reports[0].args[1] == build_explosion_add(2, *point, 1)


def test_quantized_held_blast_removes_remote_carry_visual(game):
    bomb = game.bomb()
    bomb.update(x=20.5, y=18.625, carried_by=8)
    game.client.players[8] = {'carry_sprite': 0, '_carried_bomb': bomb}
    game._detonate_bomb_at(20.5, 18.5)
    game._detonate_bomb_at(20.5, 18.5)
    assert game.active_bombs == [bomb]
    assert game.client.players[8]['carry_sprite'] == -1
    assert '_carried_bomb' not in game.client.players[8]
    game.sound_mgr.play.assert_called_once_with('explode.wav')


def test_authoritative_bomb_drop_clears_local_carry_and_registry(game):
    game.bomb()
    assert game._lift_in_front(3)
    game.client.player.update_from_props({'carry_sprite': -1})
    game._render_bombs()
    assert not game.client.player.is_carrying()
    assert game.active_bombs == []
    assert not game.thrown_objects


@pytest.mark.parametrize('linked', [False, True])
def test_remote_bomb_waits_for_quantized_relay_without_double_burst(game, linked):
    wire_client_callbacks(game)
    game._start_camera_shake = Mock()
    if linked:
        game.bomb()
    game.client.players[8] = {'x': 8.5, 'y': 10, 'direction': 0, 'carry_sprite': 0}
    if linked:
        game.client.on_bomb_del(10, 10)
    game.client.on_throwcarried(8)
    game._update_and_render_other_thrown(.45)
    assert game.active_bombs == []
    assert game.break_effects == []
    bomb = game._add_remote_bomb({'x': 9, 'y': 2.5, 'timer_ms': 2000}, now=100.45)
    assert game.active_bombs == [bomb]
    game._detonate_bomb_at(9, 2.5)
    game._detonate_bomb_at(9, 2.5)
    game.sound_mgr.play.assert_called_once_with('explode.wav')
    game._start_camera_shake.assert_called_once()


def test_heart_giveaway_charges_health_during_immunity(game):
    player = game.client.player
    player.hurt.start(1, 0, 100)
    game._giveaway_item = 5
    game.client._send_appearance_prop = Mock()
    game.client.send_item_add = Mock()
    assert game._giveaway_drop()
    assert player.hearts == 2
    game.client._send_appearance_prop.assert_called_once_with(PLPROP.CURPOWER, 4)
    game.client.send_item_add.assert_called_once()
    assert len(game.client.items['throw.nw']) == 1


@pytest.mark.parametrize('auto,damage', [(False, .5), (True, 0)])
def test_hurt_without_generation_advance_still_presents_and_throws(game, auto, damage):
    wire_client_callbacks(game)
    game.client.auto_respond_hurt = auto
    game.carry()
    game.client.on_hurt(8, damage, 'bush', -1, 0)
    assert game.current_anim_name == 'hurt'
    game.sound_mgr.play.assert_called_once_with('hurt.wav')
    assert len(game.thrown_objects) == 1
    assert len(game.damage_numbers) == 1


def test_hurt_dedupes_only_same_advanced_generation_and_timestamp(game, monkeypatch):
    wire_client_callbacks(game)
    assert game.client.respond_to_hurt(.5)
    game.client.on_hurt(8, .5, 'bush', 0, 0)
    game.client.on_hurt(8, .5, 'bush', 0, 0)
    assert len(game.damage_numbers) == 1
    monkeypatch.setattr('time.time', lambda: 100.5)
    game.client.on_hurt(8, .5, 'bush', 0, 0)
    assert len(game.damage_numbers) == 2
