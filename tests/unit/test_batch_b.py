"""Batch B classic mechanics: chest reveal/sign, AP nick colour, footsteps, swamp."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from pyreborn.alignment import alignment_color
from pyreborn.classic_sprites import (
    SPRITE_COUNT, draw_sprite, sprite_rect, swamp_index, swamp_sprite,
)
from pyreborn.game.render_objects import (
    _CHEST_REVEAL_DURATION_MS, LevelObjectsRenderMixin,
)
from pyreborn.tiletypes import TileType
from offline_game import spy
from .test_lift_oracle import game  # noqa: F401


# -- chest reveal ------------------------------------------------------------

def test_chest_reveal_lasts_24_ticks_without_rise_or_fade():
    assert _CHEST_REVEAL_DURATION_MS == 24 * 50
    reveal = {"started_ms": 1000}
    visual = LevelObjectsRenderMixin._chest_reveal_visual
    assert visual(reveal, 1000) == (0.0, 255)
    assert visual(reveal, 2199) == (0.0, 255)
    assert visual(reveal, 2200) is None


def _chest_game(game, monkeypatch, sign_index, signs):
    game.client.chest_signs = {'throw.nw': {(8, 10): sign_index}}
    game.client.signs = {'throw.nw': signs}
    game.dialogues = spy(monkeypatch, game, '_show_dialogue')
    game.is_moving = True
    game._move_accum = 0.4
    return game


def test_chest_sign_index_opens_matching_sign_and_stops_walking(game, monkeypatch):
    game = _chest_game(game, monkeypatch, 1, {(1, 1): 'first', (2, 2): 'second'})
    assert game._open_chest_sign('throw.nw', 8, 10)
    assert game.dialogues == [(('second',), {'classic_font': True})]
    assert not game.is_moving and game._move_accum == 0.0


@pytest.mark.parametrize('index', [-1, 2, 255])
def test_chest_sign_index_invalid_opens_nothing(game, monkeypatch, index):
    game = _chest_game(game, monkeypatch, index, {(1, 1): 'first', (2, 2): 'second'})
    assert not game._open_chest_sign('throw.nw', 8, 10)
    assert game.dialogues == []
    assert game.is_moving


# -- alignment colour --------------------------------------------------------

@pytest.mark.parametrize('ap,rgb', [
    (-5, (64, 0, 0)),
    (0, (64, 0, 0)),
    (1, (128, 64, 64)),
    (26, (255, 0, 0)),
    (27, (255, 10, 10)),
    (49, (255, 245, 245)),
    (50, (255, 255, 255)),
    (55, (255, 255, 255)),
    (56, (230, 255, 230)),
    (60, (128, 255, 128)),
    (61, (128, 255, 128)),
    (70, (12, 255, 243)),
    (71, (0, 247, 255)),
    (99, (0, 0, 255)),
    (100, (224, 192, 0)),
    (250, (224, 192, 0)),
])
def test_alignment_band_colours(ap, rgb):
    assert alignment_color(ap) == rgb


def test_alignment_default_is_ap_zero():
    assert alignment_color(None) == alignment_color(0)


# -- footsteps ---------------------------------------------------------------

def _walker(game, tile_type=TileType.NONBLOCK, steps2_in_gani=False, action_mode=0):
    game.client.player.action_mode = action_mode
    game._effective_tile_type = lambda x, y: tile_type
    game._gani_plays_sound = lambda name: steps2_in_gani
    return game


def _played(game):
    return [args[0] for args, _ in game.sound_calls]


def test_footsteps_first_tick_then_steps2_every_fifth_tick(game):
    game = _walker(game)
    for tick in range(100, 111):
        game._play_footsteps(tick)
    assert _played(game) == ['steps.wav', 'steps2.wav', 'steps2.wav', 'steps2.wav']


def test_footsteps_once_per_tick(game):
    game = _walker(game)
    game._play_footsteps(100)
    game._play_footsteps(100)
    assert _played(game) == ['steps.wav', 'steps2.wav']


def test_footsteps_restart_after_pause_replays_steps(game):
    game = _walker(game)
    game._play_footsteps(101)
    game._play_footsteps(102)
    game._play_footsteps(120)
    assert _played(game) == ['steps.wav', 'steps.wav', 'steps2.wav']


def test_footsteps_water_uses_water_wav_every_15_ticks(game):
    game = _walker(game, TileType.WATER)
    for tick in range(100, 121):
        game._play_footsteps(tick)
    assert _played(game) == ['water.wav', 'water.wav', 'water.wav']  # tick 100 (walk start), 105, 120
    assert 'steps.wav' not in _played(game)


def test_footsteps_do_not_double_gani_steps2(game):
    game = _walker(game, steps2_in_gani=True)
    for tick in range(100, 111):
        game._play_footsteps(tick)
    assert _played(game) == ['steps.wav']


def test_footsteps_silent_in_ghost_mode_and_wrong_action_mode(game):
    game = _walker(game)
    game.client.ghost_mode = 1
    game._play_footsteps(100)
    assert _played(game) == []
    game.client.ghost_mode = 0
    game._footstep_tick = None        # a walker that has not stepped yet
    other = _walker(game, action_mode=5)
    other._play_footsteps(100)
    assert _played(other) == ['steps.wav']  # first step only, no 5-tick cadence


def test_footsteps_toggle_swamp_parity_each_tick(game):
    game = _walker(game)
    game._play_footsteps(100)
    assert game._step_parity == 1
    game._play_footsteps(101)
    assert game._step_parity == 0


# -- classic sprite table / swamp -------------------------------------------

def test_sprite_table_shape_and_swamp_rects():
    assert SPRITE_COUNT == 356
    assert sprite_rect(22) == (0, 274, 32, 16)
    assert sprite_rect(23) == (0, 290, 32, 16)
    assert sprite_rect(150) == (0, 306, 32, 16)
    assert sprite_rect(151) == (0, 322, 32, 16)
    assert sprite_rect(352) == (32, 274, 32, 16)
    assert sprite_rect(355) == (32, 322, 32, 16)
    assert sprite_rect(356) is None and sprite_rect(-1) is None


def test_swamp_slot_per_tile_type():
    assert [swamp_index(t) for t in (5, 6, 7, 8, 9, 10)] == [-1, 0, 1, 2, 3, -1]


def test_swamp_sprite_pairs_and_alternation():
    assert swamp_sprite(-1, 0, 0) is None
    assert (swamp_sprite(0, 0, 7), swamp_sprite(0, 1, 7)) == (22, 23)
    assert (swamp_sprite(1, 0, 7), swamp_sprite(1, 1, 7)) == (352, 353)
    # slots 2/3 blink every 2 ticks regardless of step parity
    assert [swamp_sprite(2, 0, t) for t in range(6)] == [150, 150, 151, 151, 150, 150]
    assert [swamp_sprite(3, 1, t) for t in range(6)] == [354, 354, 355, 355, 354, 354]


def test_draw_sprite_uses_sprites_sheet_rect():
    mgr = Mock()
    mgr.get_sprite.return_value = 'surf'
    assert draw_sprite(mgr, 22) == 'surf'
    mgr.get_sprite.assert_called_once_with('sprites.png', 0, 274, 32, 16)
    assert draw_sprite(mgr, 999) is None


def test_gani_plays_sound_detects_walk_gani_playsound(game):
    text = 'LOOP\nANI\n0 0 0\nPLAYSOUND steps2.wav 1.5 2\n\n0 0 0\nANIEND\n'
    game.gani_parser.put_cache('walk', game.gani_parser.parse_content(text, 'walk'))
    game.player_anim.set_animation('walk')
    assert game._gani_plays_sound('steps2.wav')
    assert not game._gani_plays_sound('water.wav')
    game.player_anim.set_animation('idle')
    assert not game._gani_plays_sound('steps2.wav')
