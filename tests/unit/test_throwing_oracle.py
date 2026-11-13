"""Reference flight, landing, carry transitions and damage authority."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pygame
import pytest
from reborn_protocol import PLPROP, PacketBuilder

from offline_game import BlitRecorder, spy
from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.handlers.combat import handle_hurt_player
from pyreborn.liftobjects import LIFT_NAMES, LIFT_OBJECTS, LIFT_SPRITES
from pyreborn.packets import PacketID
from pyreborn.throwing import (
    LEAP_FRAMES, advance_throw, carry_code, carry_object, make_throw,
    remote_throw, throw_hits,
)
from pyreborn.tiletypes import TILE_TYPES


def tile_of(kind):
    return next(i for i, t in enumerate(TILE_TYPES) if t == kind)


LEVEL = 'throw.nw'


def carry(game, index=0):
    tl, bl, tr, br = LIFT_OBJECTS[index]
    game.client.player.pickup_object(LIFT_NAMES[index], (tl, tr, bl, br), (10, 10))


def build_throw_game(make_game, monkeypatch, **knobs):
    """A real offline game on an all-type-0 board 'throw.nw', player at
    (20, 20) facing right and carrying nothing (``current_anim_name`` is
    'carry', as the tests were written). Call-through spies: ``player_calls``
    (player_anim.set_animation), ``sound_calls`` (sound_mgr.play),
    ``parse_calls`` (gani_parser.parse), ``sent`` (what the client sent).
    Shared by the lift, batch and carry tests."""
    knobs.setdefault('level', LEVEL)
    knobs.setdefault('player_xy', (20.0, 20.0))
    knobs.setdefault('tiles', lambda tx, ty: tile_of(0))
    g = make_game(**knobs)
    g.client.player.direction = 3
    g.current_anim_name = 'carry'
    g.player_calls = spy(monkeypatch, g.player_anim, 'set_animation')
    g.sound_calls = spy(monkeypatch, g.sound_mgr, 'play')
    g.parse_calls = spy(monkeypatch, g.gani_parser, 'parse')
    g.sent = g.client._protocol.sent
    return g


@pytest.fixture
def game(make_game, monkeypatch):
    return build_throw_game(make_game, monkeypatch)


@pytest.mark.parametrize('direction,delta,sprite_dy', [
    (0, (0, -1), -.8), (1, (-1, 0), .2),
    (2, (0, 1), 1.2), (3, (1, 0), .2),
])
def test_linear_height_and_nine_tick_range(game, direction, delta, sprite_dy):
    obj = make_throw(20, 20, direction, 'bush', (1, 2, 3, 4))
    assert obj['y'] - obj['z'] == 18.625
    for tick in range(1, 10):
        landed = advance_throw(game, obj, .05)
        assert landed is (tick == 9)
        assert obj['x'] == 20.5 + delta[0] * tick
        assert obj['y'] == 21 + delta[1] * tick
        assert obj['z'] == pytest.approx(2.375 - .2 * tick)
        assert obj['y'] - obj['z'] == pytest.approx(18.625 + sprite_dy * tick)


def test_release_is_silent_idle_and_sends_throw_packet(game):
    carry(game)
    game._throw_object()
    assert not game.client.player.is_carrying()
    assert game.client.player.carry_sprite == -1
    assert game.player_calls == [(('idle', 3), {'force': True})]
    assert game.current_anim_name == 'idle'
    assert game.sound_calls == []
    assert game.parse_calls == [(('idle',), {})]   # only the idle gani is looked up
    assert any(pid == PacketID.PLI_THROWCARRIED for pid, _ in game.sent)


@pytest.mark.parametrize('index,leap', [(0, 0), (1, 3), (2, 2), (3, 2), (4, 2)])
@pytest.mark.parametrize('water', [False, True])
def test_landing_type_sound_and_sprite_water_probe(game, monkeypatch, index, leap, water):
    carry(game, index)
    game._throw_object()
    obj, = game.thrown_objects
    probe = Mock(return_value=water)
    monkeypatch.setattr(game, '_check_water_at_position', probe)
    assert advance_throw(game, obj, .45)
    game._spawn_break_effect(obj)
    burst, = game.particles.breaks
    assert burst['leap_type'] == (5 if water else leap)
    assert (burst['x'], burst['y']) == (obj['x'], obj['y'])
    assert burst['tiles'] == obj['tiles']
    probe.assert_called_once_with(obj['x'] + 1, obj['y'] - obj['z'] + 1)
    assert game.sound_calls == [(('water.wav' if water else 'crush.wav',), {})]
    assert not game.particles.leaves


@pytest.mark.parametrize('water_type', [11, 12])
@pytest.mark.parametrize('water_row,leap', [(21, 5), (22, 0)])
def test_water_samples_sprite_row_instead_of_ground_row(game, water_type, water_row, leap):
    obj = make_throw(20, 20, 3, 'bush', (1, 2, 3, 4))
    game.client.tiles[water_row * 64 + 30] = tile_of(water_type)
    assert advance_throw(game, obj, .45)
    game._spawn_break_effect(obj)
    assert game.particles.breaks[0]['leap_type'] == leap


@pytest.mark.parametrize('code,index', [(1, 0), (7, 1), (5, 2), (3, 3), (201, 4)])
def test_remote_carry_tiles_and_callback_launch(game, code, index):
    game.client.players[8] = {
        'x': 5, 'y': 7, 'direction': 0, 'carry_sprite': code,
        'world_x': None, 'world_y': None,
    }
    game.client.on_throwcarried(8)
    obj, = game.other_thrown_objects
    tl, bl, tr, br = LIFT_OBJECTS[index]
    assert obj['tiles'] == (tl, tr, bl, br)
    assert obj['type'] == LIFT_NAMES[index]
    assert (obj['x'], obj['y'], obj['z'], obj['dx'], obj['dy']) == (5.5, 8, 2.375, 0, -1)
    assert obj['remote'] and obj['owner_id'] == 8
    assert game.client.players[8]['carry_sprite'] == -1
    assert game.client.players[8]['animation'] == 'idle'


def test_carry_special_codes_and_unknown_objects():
    assert [carry_code(s) for s in LIFT_SPRITES] == [1, 7, 5, 3, 201]
    assert carry_code(0x41) == 0
    assert carry_code(0x42) == 200
    assert carry_object(-1) is carry_object(251) is None


def test_remote_spawn_uses_owner_segment(game):
    game.client.gmap_width = 3
    game.client.gmap_grid = {(0, 0): 'throw.nw', (2, 1): 'other.nw'}
    game.client.players[8] = {'x': 5, 'y': 7, 'direction': 3,
                              'gmaplevelx': 2, 'gmaplevely': 1, 'carry_sprite': 1}
    obj = remote_throw(game.client, 8)
    assert (obj['x'], obj['y']) == (133.5, 72)


@pytest.mark.parametrize('damage', [.5, 3])
def test_hurt_and_lethal_hurt_release_once_in_facing_direction(game, damage):
    carry(game)
    assert game.client.respond_to_hurt(damage, knockback=(-1, 0))
    game.client.on_hurt(8, damage, 'bush', -1, 0)
    game.client.on_hurt(8, damage, 'bush', -1, 0)
    obj, = game.thrown_objects
    assert (obj['x'], obj['y'], obj['dx'], obj['dy']) == (20.5, 21, 1, 0)
    assert not game.client.player.is_carrying()
    assert game.current_anim_name == ('dead' if damage == 3 else 'hurt')


def test_authoritative_death_without_hurt_packet_also_throws(game):
    carry(game)
    game.client.player.update_from_props({'hearts': 0})
    game._update_death_state(100)
    game._update_death_state(100.05)
    assert len(game.thrown_objects) == 1
    assert game.current_anim_name == 'dead'


def test_swim_entry_uses_normal_throw(game, monkeypatch):
    carry(game)
    monkeypatch.setattr(game, '_check_water_at_position', lambda x, y: True)
    monkeypatch.setattr(game, '_effective_tile_type', lambda x, y: 11)
    game._update_swimming_state()
    assert len(game.thrown_objects) == 1
    assert not game.client.player.is_carrying()
    assert game.current_anim_name == 'swim'


def test_lifting_publishes_carry_property_before_throw(game, monkeypatch):
    monkeypatch.setattr(game, '_replace_lifted_tiles', Mock())
    monkeypatch.setattr(game, '_lift_probe_tile', lambda direction: (10, 10))
    tl, bl, tr, br = LIFT_OBJECTS[1]
    for x, y, tile in ((10, 10, tl), (10, 11, bl), (11, 10, tr), (11, 11, br)):
        game.client.tiles[y * 64 + x] = tile
    assert game._lift_in_front(3)
    assert game.client.player.carry_sprite == 7
    prop = bytes([PLPROP.CARRYSPRITE + 32, 7 + 32])
    assert (PacketID.PLI_PLAYERPROPS, prop) in game.sent


@pytest.mark.parametrize('bx,by,hit', [
    (22.25, 22, True), (22.251, 22, False),
    (19.5, 22, False), (19.501, 22, True),
    (22, 22.001, False), (22, 20, False), (22, 20.001, True),
])
def test_bomb_point_rectangle_boundaries(game, bx, by, hit):
    game.client.bombs['throw.nw'] = {1: {'x': bx, 'y': by}}
    obj = make_throw(20, 20, 3, 'bush', (1, 2, 3, 4))
    assert advance_throw(game, obj, .05) is hit


def test_type_twenty_passes_bombs_chests_and_nonblocking_npcs(game, monkeypatch):
    game.client.bombs['throw.nw'] = {1: {'x': 22, 'y': 22}}
    game.client.chests['throw.nw'] = {(22, 22): {}}
    game.client.npcs[1] = {'x': 22, 'y': 22, 'tiletype': 20, 'blocking': False}
    monkeypatch.setattr(game, '_get_tile_at', lambda x, y: tile_of(20))
    obj = make_throw(20, 20, 3, 'bush', (1, 2, 3, 4))
    assert not advance_throw(game, obj, .05)
    game.client.npcs[1]['tiletype'] = 0
    assert advance_throw(game, obj, 0.05)
    assert game.client.npcs[1]['pelt_kind'] == 'bush'
    assert game.client.npcs[1]['protected_object'] == 15


@pytest.mark.parametrize('start_x,handoff_tick', [(62.5, 1), (54.5, 9)])
def test_level_handoff_skips_collision_and_preserves_world_flight(game, monkeypatch, start_x, handoff_tick):
    game.client.gmap_width = 2
    game.client.gmap_grid = {(0, 0): 'throw.nw', (1, 0): 'other.nw'}
    obj = make_throw(start_x, 20, 3, 'bush', (1, 2, 3, 4))
    monkeypatch.setattr(game, '_get_tile_at', Mock(return_value=tile_of(0)))
    assert not advance_throw(game, obj, handoff_tick * .05)
    assert obj['segment'] == (1, 0)
    assert obj['x'] == 64
    assert game._get_tile_at.call_count == handoff_tick - 1
    monkeypatch.setattr(game, '_get_tile_at', Mock(return_value=tile_of(22)))
    assert advance_throw(game, obj, .05)
    assert obj['x'] == 65


@pytest.mark.parametrize('known', [False, True])
def test_nopk_known_thrower_forces_landing_without_damage(game, known):
    game.client.level_nopk = True
    if known:
        game.client.players[8] = {'x': 19, 'y': 20}
    obj = make_throw(19, 20, 3, 'bush', (1, 2, 3, 4), owner_id=8)
    assert advance_throw(game, obj, .05)
    assert bool(game.client._pending_arrow_hits) is (not known)
    assert game.client.player.hearts == 3


@pytest.mark.parametrize('hearts,damage', [(.5, .5), (1, .5), (1.5, 1), (3, 1)])
def test_remote_damage_facing_knockback_and_type(game, hearts, damage):
    game.client.player.hearts = hearts
    obj = make_throw(19, 20, 3, 'sign', (1, 2, 3, 4), owner_id=8)
    assert advance_throw(game, obj, .05)
    hit, = game.client._pending_arrow_hits
    assert (hit['damage'], hit['dx'], hit['dy'], hit['damage_type']) == (damage, 1, 0, 'bush')


def test_nohurt_passes_through_and_own_throw_cannot_hurt_self(game):
    obj = make_throw(19, 20, 3, 'bush', (1, 2, 3, 4), owner_id=8)
    game.client.player.status = 1
    assert not advance_throw(game, obj, .05)
    game.client.player.status = 0
    obj = make_throw(19, 20, 3, 'bush', (1, 2, 3, 4))
    assert not advance_throw(game, obj, .05)
    assert game.client._pending_arrow_hits == []


@pytest.mark.parametrize('x,y,hit', [(22.499, 21, True), (22.5, 21, False),
                                    (20.5, 22.999, True), (20.5, 23, False)])
def test_strict_victim_box(x, y, hit):
    assert throw_hits(x, y, 20, 20) is hit


@pytest.mark.parametrize('server_first', [False, True])
def test_victim_report_and_server_notification_apply_damage_once(game, server_first):
    obj = make_throw(19, 20, 3, 'bush', (1, 2, 3, 4), owner_id=8)
    assert advance_throw(game, obj, .05)
    b = PacketBuilder()
    b.write_gshort(8)
    for value in (1, 0, 2):
        b.write_gchar(value)
    if server_first:
        handle_hurt_player(game.client, b.build())
    game.client._tick_arrow_sims(100 + game.client._ARROW_HIT_GRACE)
    if not server_first:
        handle_hurt_player(game.client, b.build())
    assert game.client.player.hearts == 2


@pytest.mark.parametrize('report_first', [False, True])
def test_server_simulation_and_thrower_report_apply_damage_once(monkeypatch, report_first):
    monkeypatch.setattr('time.time', lambda: 100.0)        # pygserver's clock
    # Exercise the actual server implementation without modifying its package.
    server_path = str(Path(__file__).resolve().parents[3] / 'pygserver')
    sys.path.insert(0, server_path)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from pygserver.combat import CombatManager, ThrownObject
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(server_path)
    level = SimpleNamespace(name='throw.nw')
    attacker = SimpleNamespace(id=8, x=19, y=20, level=level)
    victim = SimpleNamespace(id=9, x=20, y=20, level=level, hearts=3,
                             send_raw=AsyncMock(), send_props=AsyncMock())
    server = SimpleNamespace(
        get_player=lambda pid: victim,
        audience=SimpleNamespace(players_on_level=lambda *args, **kwargs: [victim]))
    manager = CombatManager(server)
    manager._is_throw_wall = lambda thrown: False
    thrown = ThrownObject(attacker, level, 19.5, 21, 3, None)

    async def exercise():
        if report_first:
            await manager.handle_hurt_player(attacker, 9, 2, 1, 0)
        await manager._update_throw(thrown)
        if not report_first:
            await manager.handle_hurt_player(attacker, 9, 2, 1, 0)
    asyncio.run(exercise())
    assert victim.hearts == 2
    victim.send_raw.assert_awaited_once()
    assert manager._invincible[9] == 102


def record_blits(game, monkeypatch):
    """A blit recorder for the screen, tile ids for tile art and a draw
    wrapper that draws at once: what is blitted where is the thing asserted."""
    game.screen = BlitRecorder(game.screen)
    monkeypatch.setattr(game.tileset_mgr, 'get_tile_or_color', lambda tile: tile)
    monkeypatch.setattr(game, '_render_world_object',
                        lambda frame, y, draw, **kwargs: draw())
    return game


@pytest.fixture
def drawn(game, monkeypatch):
    """``record_blits`` plus a unit camera (16 px per tile, origin at the
    world origin) so the exact pixel positions are the geometry under test."""
    record_blits(game, monkeypatch)
    monkeypatch.setattr(game.camera, 'world_to_screen',
                        lambda x, y: (x * 16, y * 16))
    return game


@pytest.mark.parametrize('remote', [False, True])
def test_shared_render_path_draws_real_tiles_and_ground_shadow(drawn, monkeypatch, remote):
    game = drawn
    ellipse = Mock()
    monkeypatch.setattr(pygame.draw, 'ellipse', ellipse)
    obj = make_throw(20, 20, 3, 'sign', (10, 11, 12, 13), owner_id=8 if remote else None)
    assert game._advance_throws([obj], 0, remote=remote) == [obj]
    game._render_throws([obj], None)
    assert [source for source, _ in game.screen.blits] == [10, 11, 12, 13]
    assert game.screen.blits[0][1] == (20.5 * 16, 18.625 * 16)
    assert ellipse.call_args.args[2][:2] == (20.75 * 16, 23.5 * 16)


@pytest.mark.parametrize('leap,count', [(0, 7), (2, 4), (3, 4), (5, 8)])
def test_burst_uses_each_table_frame_once_and_expires(drawn, monkeypatch, leap, count):
    game = drawn
    rect = Mock()
    monkeypatch.setattr(pygame.draw, 'rect', rect)
    now = game.clock.frame_now()
    effect = {'x': 10, 'y': 20, 'time': now, 'leap_type': leap, 'tiles': (1, 2, 3, 4)}
    game.particles.breaks = [effect]
    # Sample each frame mid-tick: frame time sits far from zero, and a
    # boundary reading would be at the mercy of float rounding.
    game._fixture_clock.advance(.025)
    for frame in range(count):
        game.screen.blits.clear()
        rect.reset_mock()
        game._render_break_effects()
        assert game.particles.breaks == [effect]
        expected = [((10 + dx / 8) * 16, (20 + dy / 8) * 16)
                    for _sprite, dx, dy in LEAP_FRAMES[leap][frame]]
        if leap == 5:
            assert rect.call_count == 2
            assert [c.args[2][:2] for c in rect.call_args_list] == expected
            assert all(c.args[1] == (150, 215, 255) for c in rect.call_args_list)
            assert game.screen.blits == []
        else:
            assert [source for source, _ in game.screen.blits] == [1, 2, 3, 4]
            assert [dest for _, dest in game.screen.blits] == expected
        game._fixture_clock.advance(.05)
    game._render_break_effects()
    assert game.particles.breaks == []


@pytest.mark.parametrize('kind,last', [
    (0, ((26, -8, 4), (25, -2, -16), (26, 10, 22), (26, 10, 25))),
    (2, ((99, -7, -6), (99, -6, 15), (97, 15, -7), (97, 16, 14))),
    (3, ((103, -7, -6), (103, -6, 15), (101, 15, -7), (101, 16, 14))),
    (5, ((326, -19, -1), (327, 20, -1))),
])
def test_signed_eighth_tile_offsets_match_reference_endpoints(kind, last):
    assert LEAP_FRAMES[kind][-1] == last
