"""Hiding under a carried bush/stone (TPlayer actionMode 14), on a real game."""

from collections import defaultdict
from unittest.mock import Mock

import pygame
import pytest

from offline_game import key_event
from pyreborn import hiding
from pyreborn.game import constants as c


@pytest.fixture
def new_game(make_game, monkeypatch):
    """``new_game(carrying)``: a real offline game whose player carries it."""
    def build(carrying="bush"):
        game = make_game()
        game.frames(1)
        monkeypatch.setattr(game, "_spawn_leaps", Mock())
        if carrying:
            game.client.player.pickup_object(carrying, (1, 2, 3, 4), (0, 0))
            game.current_anim_name = "carry"
        return game
    return build


def _hold(monkeypatch, key):
    monkeypatch.setattr(pygame.key, 'get_pressed',
                        lambda: defaultdict(bool, {key: True}))


def test_hidable_set_matches_hidablesprites():
    assert hiding.HIDABLE_SPRITES == (0x105, 0x107, 0xef)  # TInitStatics.cpp:1143
    assert hiding.HIDABLE_OBJECTS == ("bush", "stone", "blackstone")
    assert hiding.HIDDEN_ACTION_MODE == 14  # TPlayer.cpp:2131


@pytest.mark.parametrize("kind", ["bush", "stone", "blackstone"])
def test_d_hides_hidable_object(kind, new_game):
    game = new_game(kind)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 14
    assert game.current_anim_name == "hiddenstill"
    assert game._is_hidden()


@pytest.mark.parametrize("kind", ["sign", "vase"])
def test_d_ignores_other_objects(kind, new_game):
    game = new_game(kind)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0
    assert not game._is_hidden()


def test_d_without_carrying_does_not_hide(new_game):
    game = new_game(None)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0


def test_d_again_unhides_and_keeps_object(new_game):  # TPlayer.cpp:2122-2126
    game = new_game()
    game._hide_or_unhide()
    game._hide_or_unhide()
    player = game.client.player
    assert player.action_mode == 0 and player.is_carrying()
    assert game.current_anim_name == "carrystill"


def test_a_unhides_without_throwing(new_game):  # TPlayer.cpp:2069-2073
    game = new_game()
    game._hide_or_unhide()
    game._try_grab()
    player = game.client.player
    assert player.action_mode == 0 and player.is_carrying()
    assert not game.thrown_objects


@pytest.mark.parametrize('kind', ['bush', 'stone', 'blackstone'])
def test_unhide_only_bush_throws_leaves(kind, new_game):
    # TPlayer.cpp:6414-6426: clear mode, bush leaves, then standing carry.
    game = new_game(kind)
    game._hide_or_unhide()
    game._unhide()
    assert game.client.player.action_mode == 0
    assert game.client.player.carried_object_type == kind
    assert game.current_anim_name == 'carrystill'
    if kind == 'bush':
        # TPlayer.cpp:6420-6422; corrected X per companion burst :6039.
        game._spawn_leaps.assert_called_once_with(0, 30.5, 30.3125)
    else:
        game._spawn_leaps.assert_not_called()


def test_s_throw_ends_hiding(new_game):  # TPlayer.cpp:2032
    game = new_game()
    game._hide_or_unhide()
    game._throw_object()
    player = game.client.player
    assert player.action_mode == 0 and not player.is_carrying()


def test_hidden_player_is_hittable(new_game):  # getNoHurt/getNoHit have no mode 14 clause
    game = new_game()
    game._hide_or_unhide()
    assert not game.client.player.no_hurt()


def test_hidden_player_cannot_hide_while_swimming(new_game):
    game = new_game()
    game.is_swimming = True
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0


# One tick of held movement: 0.5 tile walking, 0.1 hidden.
@pytest.mark.parametrize("hidden,expected", [(False, 0.5), (True, 0.1)])
def test_hidden_crawl_speed(monkeypatch, new_game, hidden, expected):
    game = new_game()
    if hidden:
        game._hide_or_unhide()
    else:
        game.client.player.throw_object()
    _hold(monkeypatch, pygame.K_RIGHT)
    start = game.client.x
    game.ticks(10)
    # 0.1 tiles/tick x 20 ticks/s = 2 tiles/s vs 10 tiles/s walking.
    assert (game.client.x - start) / 10 == pytest.approx(expected, abs=1e-6)


def test_d_while_carrying_hides_instead_of_firing_weapon(monkeypatch, new_game):
    game = new_game()
    game._use_weapon = Mock()
    game.ticks(1, events=[key_event(pygame.K_d)])
    assert game.client.player.action_mode == 14
    game._use_weapon.assert_not_called()
