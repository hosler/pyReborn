"""Lift gating, carry geometry, animation/audio and live bomb regressions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from pyreborn.carrying import bomb_sprite, carry_position, carry_tiles, standing_carry
from pyreborn.gani import AnimationState, GaniParser
from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.game.render import RenderMixin
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.hiding import can_hide
from pyreborn.liftobjects import LIFT_NAMES, LIFT_OBJECTS
from pyreborn.packets import PacketID, build_bomb_add, build_bomb_del, parse_other_player, parse_player_props
from reborn_protocol import PacketBuilder
from offline_game import spy
from .test_throwing_oracle import (  # noqa: F401
    BlitRecorder, build_throw_game, carry, record_blits, tile_of)


LIFT = '''SETBACKTO carrystill
ANI
0 12 36
0 12 36
0 12 36
0 12 36
PLAYSOUND lift.wav 1.5 2
WAIT 5
ANIEND
'''


def place_object(game, index=0):
    game._lift_probe_tile = lambda direction: (10, 10)
    for (x, y), tile in zip(((10, 10), (10, 11), (11, 10), (11, 11)), LIFT_OBJECTS[index]):
        game.client.tiles[y * 64 + x] = tile
    game._replace_lifted_tiles = Mock()


def place_bomb(game, sprite=0x41, fuse=3.0):
    bomb = {'x': 10, 'y': 10, 'time': 99.0, 'fuse_time': fuse,
            'power': 1, 'sprite': sprite, 'exploded': False}
    game.active_bombs.append(bomb)
    game.client.bombs['throw.nw'] = {0: dict(bomb)}
    game._lift_probe_tile = lambda direction: (10, 10)
    return bomb


@pytest.fixture
def game(sim_time, make_game, monkeypatch):
    """The throw game with the lift/carry ganis of this file in its parser
    (a 4-frame lift with a sound, one-frame loops for the rest), and the
    camera shake and blast helpers stubbed (their calls are what is read)."""
    sim_time(100.0)
    g = build_throw_game(make_game, monkeypatch)
    g.active_bombs = []
    g._start_camera_shake = g._break_bushes_in_blast = Mock()
    for name in ('lift', 'carry', 'carrystill', 'hidden', 'hiddenstill', 'idle'):
        text = LIFT
        if name != 'lift':
            text = 'LOOP\nANI\n0 0 0\n0 0 0\n0 0 0\n0 0 0\nANIEND\n'
        g.gani_parser.put_cache(name, g.gani_parser.parse_content(text, name))
    g.player_anim.set_animation('idle')
    g.current_anim_name = 'idle'
    g.gani_sound_calls = spy(monkeypatch, g.sound_mgr, 'play_from_gani')
    return g


@pytest.mark.parametrize('mode', [4, 5, 10])
def test_a_refuses_lift_pull_and_swim_modes(game, mode):
    game.client.player.action_mode = mode
    game._find_chest_in_front = Mock()
    game._try_grab()
    game._find_chest_in_front.assert_not_called()
    place_object(game)
    assert not game._lift_in_front(3)
    assert not game.client.player.is_carrying()
    game._pickup_ground_item = Mock()
    game._try_pickup(1, 0)
    game._pickup_ground_item.assert_not_called()


def test_successful_lift_sets_mode_and_plays_gani_sound_once(game):
    place_object(game)
    assert game._lift_in_front(3)
    assert game.client.player.action_mode == 4
    assert game.current_anim_name == 'lift'
    assert game.sound_calls == []
    game._update_animations(.05)
    assert game.gani_sound_calls == [((('lift.wav', 1.5, 2.0),), {})]
    assert game.current_anim_name == 'carrystill'
    assert game.client.player.action_mode == 0
    game._update_animations(.05)
    assert len(game.gani_sound_calls) == 1


@pytest.mark.parametrize('direction,positions', [
    (0, ((.5, -1), (.5, -1), (.5, -1), (.5, -1), (.5, -1))),
    (1, ((-1.5, 1), (-1.3, .1), (-1, -.5), (-.4, -.8), (.5, -1))),
    (2, ((.5, 3), (.5, 1.9), (.5, 1), (.5, .1), (.5, -1))),
    (3, ((2.5, 1), (2.3, .1), (2, -.5), (1.4, -.8), (.5, -1))),
])
def test_all_lift_subframe_offsets(direction, positions):
    for counter, expected in enumerate(positions):
        assert carry_position(direction, counter)[:2] == pytest.approx(expected)
    assert carry_position(direction) == (.5, -1.375, None)


def test_lift_counter_is_subframe_not_gani_frame():
    anim = SimpleNamespace(frame=4, frame_time=0.0)
    assert EntityRenderMixin._lift_subframe(anim) == 0


@pytest.mark.parametrize('code,index', [(1, 0), (7, 1), (5, 2), (3, 3), (201, 4)])
def test_remote_carry_tiles_and_rest_render(game, monkeypatch, code, index):
    record_blits(game, monkeypatch)
    tl, bl, tr, br = LIFT_OBJECTS[index]
    assert carry_tiles(code) == (tl, tr, bl, br)
    game._render_animated_entity = Mock()
    game._render_other_player(100, 200, {'carry_sprite': code}, 8)
    assert [source for source, _ in game.screen.blits] == [tl, tr, bl, br]
    assert game.screen.blits[0][1] == (108, 178)


@pytest.mark.parametrize('code', [0, 200])
def test_remote_bombs_render_bomb_graphic(game, monkeypatch, code):
    record_blits(game, monkeypatch)
    game._render_animated_entity = Mock()
    game._get_effect_sprite = Mock(return_value='bomb-image')
    game._render_other_player(100, 200, {'carry_sprite': code}, 8)
    assert game.screen.blits == [('bomb-image', (108, 178))]


@pytest.mark.parametrize('code', [-1, 0, 1, 3, 5, 7, 200, 201])
def test_carry_property_parsers_keep_empty_distinct_from_bomb(code):
    data = bytes([51, code + 32])
    assert parse_player_props(data)['carry_sprite'] == code
    remote = PacketBuilder().write_gshort(8).build() + data
    assert parse_other_player(remote)['carry_sprite'] == code


def test_remote_lift_setback_does_not_restart_on_each_draw(game, monkeypatch):
    monkeypatch.setattr(pygame.draw, 'ellipse', Mock())
    game._render_animated_entity = Mock()
    game.client.players[8] = {'ani': 'lift', 'carry_sprite': 1}
    game._render_other_player(100, 200, game.client.players[8], 8)
    game._update_animations(.05)
    assert game.other_player_anims[8].gani.name == 'carrystill'
    game._render_other_player(100, 200, game.client.players[8], 8)
    assert game.other_player_anims[8].gani.name == 'carrystill'


def test_remote_bomb_pickup_pauses_fuse_and_transfers_it_to_throw(game):
    bomb = place_bomb(game)
    game.client.players[8] = {'x': 8.5, 'y': 10, 'direction': 0, 'carry_sprite': 0}
    game.client.on_bomb_del(10, 10)
    assert game.client.players[8]['_carried_bomb'] is bomb
    assert bomb['fuse_remaining'] == 2
    game.client.on_throwcarried(8)
    assert game.other_thrown_objects[0]['bomb'] is bomb
    assert bomb['in_flight']


def test_remote_animation_retries_after_its_asset_arrives(game):
    game._render_animated_entity = Mock()
    pdata = {'ani': 'downloaded'}
    game._render_other_player(100, 200, pdata, 8)
    assert game.other_player_anims[8].gani is None
    gani = game.gani_parser.parse_content('SINGLEDIRECTION\nANI\n0 0 0\nANIEND', 'downloaded')
    game.gani_parser.put_cache('downloaded', gani)
    game._render_other_player(100, 200, pdata, 8)
    assert game.other_player_anims[8].gani is gani


@pytest.mark.parametrize('index,wire', [(0, 33), (1, 39), (2, 37), (3, 35), (4, 233)])
@pytest.mark.parametrize('hurt', [False, True])
def test_carry_property_lift_throw_and_hurt_drop(game, index, wire, hurt):
    game.client.player.glove_power = 3
    place_object(game, index)
    assert game._lift_in_front(3)
    calls = game.sent
    assert (PacketID.PLI_PLAYERPROPS, bytes([51, wire])) in calls
    if hurt:
        game.client.respond_to_hurt(.5)
        game.client.on_hurt(8, .5, 'bush', -1, 0)
    else:
        game._throw_object()
    assert game.client.player.carry_sprite == -1
    assert (PacketID.PLI_PLAYERPROPS, bytes([51, 31])) in calls
    ids = [pid for pid, _ in calls]
    clear = calls.index((PacketID.PLI_PLAYERPROPS, bytes([51, 31])))
    assert ids.index(PacketID.PLI_THROWCARRIED) < clear


@pytest.mark.parametrize('moving,hidden,expected', [
    (False, False, 'carrystill'), (True, False, 'carry'),
    (False, True, 'hiddenstill'), (True, True, 'hidden'),
])
def test_carry_idle_and_walk_animations(game, moving, hidden, expected):
    carry(game)
    game.is_moving = moving
    game.client.player.action_mode = 14 if hidden else 0
    game._update_animations(0)
    assert game.current_anim_name == expected


def test_missing_carrystill_falls_back(game):
    game.gani_parser.parse = lambda name: None
    assert standing_carry(game) == 'carry'


def test_carrying_refuses_sit_sleep_and_bomb_hiding(game):
    carry(game)
    game._effective_tile_type = lambda x, y: 3
    game._update_sitting_state()
    assert not game.client.player.is_sitting
    assert not game.client.player.sit_down()
    game._effective_tile_type = lambda x, y: 4
    game._test_sleeping()
    assert game.current_anim_name != 'sleep'
    assert not can_hide('bomb')


@pytest.mark.parametrize('sprite,wire', [(0x41, 32), (0x42, 232)])
def test_bomb_pickup_and_landing_preserve_fuse(game, sim_time, sprite, wire):
    bomb = place_bomb(game, sprite)
    assert game._lift_in_front(3)
    assert game.client.player.carried_bomb is bomb
    assert bomb['time'] == 99
    assert not game.client.bombs['throw.nw']
    calls = game.sent
    assert (PacketID.PLI_BOMBDEL, build_bomb_del(10, 10)) in calls
    assert (PacketID.PLI_PLAYERPROPS, bytes([51, wire])) in calls
    game._throw_object()
    sim_time(100.45)
    game._update_and_render_thrown(.45)
    assert not game.thrown_objects
    assert (bomb['x'], bomb['y']) == pytest.approx((29.5, 21.925))
    assert bomb['time'] == 100.45 and bomb['fuse_time'] == 2
    expected = build_bomb_add(29.5, 21.925, 1, 1750, True)  # ticks-5
    assert (PacketID.PLI_BOMBADD, expected) in calls
    assert game.break_effects == []


def test_bomb_fuse_pauses_while_carried(game, sim_time):
    bomb = place_bomb(game, fuse=1.1)
    assert game._lift_in_front(3)
    sim_time(100.11)
    game._advance_bombs()
    assert not bomb['exploded']
    assert game.client.player.is_carrying()
    assert bomb['fuse_remaining'] == pytest.approx(.1)


def test_tile_pattern_precedes_bomb_pickup(game):
    bomb = place_bomb(game)
    place_object(game)
    assert game._lift_in_front(3)
    assert game.client.player.carried_object_type == 'bush'
    assert bomb.get('carried_by') is None


def test_hot_bomb_sprite_is_taken_from_current_fuse_phase():
    bomb = {'time': 99, 'fuse_time': 3, 'power': 1}
    assert bomb_sprite(bomb, 100) == 0x41
    assert bomb_sprite(bomb, 100.55) == 0x41
    assert bomb_sprite(bomb, 100.6) == 0x42


def test_bomb_water_landing_splashes_instead_of_replacing(game):
    bomb = place_bomb(game)
    assert game._lift_in_front(3)
    game._throw_object()
    game._check_water_at_position = lambda x, y: True
    game._update_and_render_thrown(.45)
    assert bomb not in game.active_bombs
    assert game.break_effects[0]['leap_type'] == 5
    assert not any(pid == PacketID.PLI_BOMBADD for pid, _ in game.sent)


@pytest.mark.parametrize('probe,hit', [((10, 10), True), ((11, 11), True),
                                     ((12, 10), False), ((10, 12), False), ((9, 10), False)])
def test_bomb_pickup_uses_half_open_two_tile_box(game, probe, hit):
    place_bomb(game)
    game._lift_probe_tile = lambda direction: probe
    assert game._lift_in_front(3) is hit
