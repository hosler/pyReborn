"""The timershow countdown, the `take` pickup icon and a carrying character
NPC go through the real NPC renderer (offline, SDL dummy)."""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn.pygame_game import GameClient
from pyreborn.throwing import carry_code

pygame.init()
pygame.display.set_mode((64, 64))


@pytest.fixture(scope="module")
def game():
    return GameClient(Client('127.0.0.1', 14900, version='6.037'))


def _draw(game, npc, at=(100.0, 100.0)):
    game.client.npcs.clear()
    game.client.npcs[1] = npc
    game.camera.set_center(32.0, 32.0)
    game.visual_x = game.visual_y = 32.0
    game._player_render_pos = (32.0, 32.0)
    texts = []
    real = game._render_text_outlined_cached

    def spy(font, text, color, *args, **kwargs):
        texts.append(text)
        return real(font, text, color, *args, **kwargs)

    game._render_text_outlined_cached = spy
    try:
        game._render_npc(at[0], at[1], npc, 1)
    finally:
        del game._render_text_outlined_cached
    return texts


def test_timershow_draws_the_remaining_seconds(game):
    texts = _draw(game, {'x': 32.0, 'y': 32.0, 'image': 'sign.png',
                         'timershow': True, '_timeout': 4.6})
    assert texts == ['4']


def test_no_timershow_draws_nothing(game):
    assert _draw(game, {'x': 32.0, 'y': 32.0, 'image': 'sign.png',
                        '_timeout': 4.6}) == []


def test_take_icon_and_total_replace_the_timer(game, monkeypatch):
    import pyreborn.game.render_entities as entities
    from pyreborn.game.constants import TILE_SIZE
    asked = []

    def fake_sprite(mgr, index):
        asked.append(index)
        icon = pygame.Surface((8, 8))
        icon.fill((255, 0, 255))
        return icon

    monkeypatch.setattr(entities, 'draw_sprite', fake_sprite)
    game.screen.fill((0, 0, 0))
    texts = _draw(game, {'x': 32.0, 'y': 32.0, 'image': 'sign.png',
                         'timershow': True, '_timeout': 4.6, 'take_item': 0,
                         'take_until': time.monotonic() + 1.0,
                         'take_value': 12.0}, at=(20.0, 40.0))
    assert texts == ['12'] and asked == [136]        # giveitems[0], green rupee
    # the icon sits one tile above the NPC, centred on x + 1 tile
    cx, top = 20 + TILE_SIZE, 40 - TILE_SIZE - 8
    assert game.screen.get_at((cx, top + 4))[:3] == (255, 0, 255)
    assert game.screen.get_at((cx + 20, top + 4))[:3] == (0, 0, 0)


_CARRYSTILL = """SPRITE 0 body.png 0 0 32 32
ANI
LOOP
SETBACKTO idle
WAIT 1
ANIEND
"""


def test_carrying_character_npc_draws_its_object(game):
    # Seed the gani instead of relying on a download cache entry.
    game.gani_parser.put_cache(
        'carrystill', game.gani_parser.parse_content(_CARRYSTILL, 'carrystill'))
    calls = []
    real = game._draw_carried_object

    def spy(x, y, code, direction, *args, **kwargs):
        calls.append((x, y, code, direction))
        return real(x, y, code, direction, *args, **kwargs)

    game._draw_carried_object = spy
    try:
        _draw(game, {'x': 32.0, 'y': 32.0, 'image': '#c#', 'is_character': True,
                     'gani': 'carrystill,', 'direction': 1,
                     'carry_sprite': carry_code(0x109)}, at=(20.0, 40.0))
    finally:
        del game._draw_carried_object
        game.gani_parser.cache.pop('carrystill', None)
    assert calls == [(20.0, 40.0, carry_code(0x109), 1)]


def test_npc_without_a_carry_sprite_draws_no_object(game):
    calls = []
    game._draw_carried_object = lambda *a, **k: calls.append(a)
    try:
        _draw(game, {'x': 32.0, 'y': 32.0, 'image': '#c#', 'is_character': True,
                     'gani': 'idle,', 'carry_sprite': -1})
    finally:
        del game._draw_carried_object
    assert calls == []


def _reset_throws(game):
    game.client.npcs.clear()
    game.camera.set_center(32.0, 32.0)
    game.visual_x = game.visual_y = 32.0
    for name in ('thrown_objects', 'other_thrown_objects', 'active_bombs',
                 'break_effects'):
        getattr(game, name).clear()


def test_npc_thrown_vase_flies_then_bursts_at_its_landing_point(game):
    _reset_throws(game)
    game.gs1.on_throwcarry({'x': 30.0, 'y': 30.0, 'direction': 2}, carry_code(0x109))
    assert len(game.other_thrown_objects) == 1
    obj = game.other_thrown_objects[0]
    start_y = obj['y']
    for _ in range(4):
        game._update_and_render_thrown(0.05)
    assert game.other_thrown_objects == [obj] and obj['ticks'] == 4
    assert obj['y'] == pytest.approx(start_y + 4)        # one tile per tick, down
    assert obj['z'] < 2.375                              # falling
    for _ in range(6):
        game._update_and_render_thrown(0.05)
    assert game.other_thrown_objects == []
    assert len(game.break_effects) == 1                   # landed and burst
    assert game.break_effects[0]['tiles'] == obj['tiles']


@pytest.mark.parametrize("sprite, power", [(0x41, 1), (0x42, 1), (0x141, 2),
                                           (0x15b, 3), (0x15c, 3)])
def test_npc_thrown_bomb_keeps_its_power_and_lands_as_a_level_bomb(game, sprite, power):
    _reset_throws(game)
    game.gs1.on_throwcarry({'x': 30.0, 'y': 30.0, 'direction': 2}, carry_code(sprite))
    bomb = game.active_bombs[0]
    assert bomb['power'] == power and bomb['in_flight'] is True
    assert game.thrown_objects[0]['bomb'] is bomb
    game._update_and_render_thrown(0.05)
    assert bomb['in_flight'] is True and bomb['y'] > 30.0   # moving with the arc
    for _ in range(9):
        game._update_and_render_thrown(0.05)
    assert game.thrown_objects == []
    assert bomb['in_flight'] is False and bomb in game.active_bombs


def test_script_spawns_are_capped(game):
    from pyreborn.game.callbacks.gs1_callbacks import MAX_SCRIPT_OBJECTS
    _reset_throws(game)
    game.active_projectiles.clear()
    for _ in range(MAX_SCRIPT_OBJECTS + 50):
        game.gs1.on_throwcarry({'x': 1.0, 'y': 1.0, 'direction': 2}, carry_code(0x109))
        game.gs1.on_throwcarry({'x': 1.0, 'y': 1.0, 'direction': 2}, carry_code(0x41))
        game.gs1.on_flying(1.0, 1.0, 2, 3)
    assert len(game.other_thrown_objects) == MAX_SCRIPT_OBJECTS
    assert len(game.thrown_objects) == MAX_SCRIPT_OBJECTS
    assert len(game.active_bombs) == MAX_SCRIPT_OBJECTS
    assert len(game.active_projectiles) == MAX_SCRIPT_OBJECTS


def test_flying_object_is_drawn_and_expires(game):
    game.active_projectiles.clear()
    game.gs1.on_flying(30.0, 30.0, 2, 3)
    game._update_and_render_projectiles(0.05)
    assert game.active_projectiles and game.active_projectiles[0]['gani'] == 'nukeshot'
