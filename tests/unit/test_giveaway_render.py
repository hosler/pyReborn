"""Offline giveaway icon geometry, local rendering and selection state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from offline_game import spy
from pyreborn.clock import Clock
from pyreborn import ground_items as gi
from pyreborn.classic_sprites import SPRITE_RECTS
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.player import Player


def test_giveaway_sprite_table_matches_reference():
    # Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1197-1201.
    assert gi.GIVE_SPRITES == (
        136, 137, 138, 67, 143, 139, 145, 351, 65, 350,
        314, 315, 321, 323, 322, 324, 325, 328, 329, 330,
        331, 332, 333, 334, 349,
    )


@pytest.mark.parametrize('size,chat_y,horse,expected', [
    ((16, 32), 0.0, False, (1.0, -1.0)),
    ((28, 32), 0.0, False, (0.625, -1.0)),
    ((14, 14), 0.75, False, (1.0625, 0.3125)),
    ((16, 32), 0.0, True, (1.0, -2.0)),
    ((14, 14), 3.0, True, (1.0625, -1.4375)),
])
def test_giveaway_icon_offset(size, chat_y, horse, expected):
    assert gi.giveaway_icon_offset(size, chat_y, horse) == expected


def _renderer(player, selected, sprite):
    # Like the carry harness, run the real renderer with an offline screen
    # recording blits; unrelated body, chat and swamp passes are stubbed.
    return SimpleNamespace(
        client=SimpleNamespace(player=player), screen=Mock(), clock=Clock(),
        sprite_mgr=SimpleNamespace(get_sprite=Mock(return_value=sprite)),
        _giveaway_item=selected, _PLAYER_ANCHOR_FIX=8, debug_mode=False,
        camera=SimpleNamespace(),
        combat_presentation=SimpleNamespace(player_alpha=lambda now, base: base),
        _attr_equipment=EntityRenderMixin._attr_equipment,
        _render_animated_entity=Mock(), _render_swamp_overlay=Mock(),
        _render_player_chat=Mock(), _status_label=lambda status: '',
        _hidden_alpha=EntityRenderMixin._hidden_alpha,
        _nameplate_label=Mock(return_value=''), _draw_nameplate=Mock(),
        _nameplate_top=Mock(return_value=0),
    )


@pytest.mark.parametrize('selected,horse,chat_y,position', [
    (None, False, 0.0, None),
    (0, False, 0.0, (116.5, 184.25)),
    (0, True, 2.0, (116.5, 168.25)),
    (0, False, 0.75, (116.5, 196.25)),
    (3, False, 0.0, (110.5, 184.25)),
])
def test_local_player_giveaway_icon_blit(selected, horse, chat_y, position):
    player = Player(horse_image='horse.png' if horse else '')
    player.chat_offset = (7.0, chat_y)  # X is deliberately ignored by the oracle.
    size = SPRITE_RECTS[gi.GIVE_SPRITES[selected or 0]][2:]
    icon = pygame.Surface(size)
    game = _renderer(player, selected, icon)
    EntityRenderMixin._render_player(game, 100.5, 200.25, player, Mock(),
                                    frame=SimpleNamespace())
    if position is None:
        game.screen.blit.assert_not_called()
        game.sprite_mgr.get_sprite.assert_not_called()
    else:
        game.sprite_mgr.get_sprite.assert_called_once_with(
            'sprites.png', *SPRITE_RECTS[gi.GIVE_SPRITES[selected]])
        game.screen.blit.assert_called_once_with(icon, position)


def test_giveaway_missing_sprite_skips_blit():
    player = Player()
    game = _renderer(player, 0, None)
    EntityRenderMixin._render_player(game, 100, 200, player, Mock(),
                                    frame=SimpleNamespace())
    game.screen.blit.assert_not_called()


@pytest.fixture
def selection_game(make_game, monkeypatch):
    """A real offline game holding 40 rupees; call-through spies on the three
    things a selection touches (``game.calls['anim' | 'sent' | 'sound']``)."""
    game = make_game(me={"rupees": 40})
    game.client.player.direction = 2
    game.calls = {
        'anim': spy(monkeypatch, game.player_anim, 'set_animation'),
        'sent': spy(monkeypatch, game.client, 'set_animation'),
        'sound': spy(monkeypatch, game.sound_mgr, 'play'),
    }
    return game


def test_giveaway_select_enters_mode_nine_with_idle_and_cycles(selection_game):
    game = selection_game
    assert game.client.player.rupees == 40
    for item in (0, 1, 2):
        game._giveaway_select()
        assert game._giveaway_item == item
        assert game.client.player.action_mode == 9
        assert game.current_anim_name == 'idle'
        assert game.calls['anim'][-1] == (('idle', 2), {'force': True})
        assert game.calls['sent'][-1] == (('idle',), {})
        assert game.calls['sound'][-1] == (('item2.wav',), {})


def test_giveaway_without_available_items_clears_selection_mode(selection_game):
    game = selection_game
    game._giveaway_select()
    player = game.client.player
    player.rupees = player.bombs = player.arrows = 0
    player.hearts = 1.0
    game._giveaway_select()
    assert game._giveaway_item is None
    assert game.client.player.action_mode == 0
