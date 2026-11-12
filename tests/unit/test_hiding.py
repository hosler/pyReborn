"""Hiding under a carried bush/stone (TPlayer actionMode 14)."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from pyreborn import hiding
from pyreborn.game import constants as c
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.input import InputMixin
from pyreborn.clock import Clock
from pyreborn.player import Player


class Game(ActionsMixin, InputMixin):
    def __init__(self, carrying="bush"):
        self.client = SimpleNamespace(player=Player(), set_animation=Mock())
        self.player_anim = Mock()
        self.sound_mgr = Mock()
        self._spawn_leaps = Mock()
        self.gani_parser = SimpleNamespace(parse=lambda _: None)
        self.thrown_objects = []
        self.current_anim_name = "carry"
        self.is_swimming = False
        self.client.x = self.client.y = 30.0
        if carrying:
            self.client.player.pickup_object(carrying, (1, 2, 3, 4), (0, 0))


def test_hidable_set_matches_hidablesprites():
    assert hiding.HIDABLE_SPRITES == (0x105, 0x107, 0xef)  # TInitStatics.cpp:1143
    assert hiding.HIDABLE_OBJECTS == ("bush", "stone", "blackstone")
    assert hiding.HIDDEN_ACTION_MODE == 14  # TPlayer.cpp:2131


@pytest.mark.parametrize("kind", ["bush", "stone", "blackstone"])
def test_d_hides_hidable_object(kind):
    game = Game(kind)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 14
    assert game.current_anim_name == "hiddenstill"
    assert game._is_hidden()


@pytest.mark.parametrize("kind", ["sign", "vase"])
def test_d_ignores_other_objects(kind):
    game = Game(kind)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0
    assert not game._is_hidden()


def test_d_without_carrying_does_not_hide():
    game = Game(None)
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0


def test_d_again_unhides_and_keeps_object():  # TPlayer.cpp:2122-2126
    game = Game()
    game._hide_or_unhide()
    game._hide_or_unhide()
    player = game.client.player
    assert player.action_mode == 0 and player.is_carrying()
    assert game.current_anim_name == "carry"


def test_a_unhides_without_throwing():  # TPlayer.cpp:2069-2073
    game = Game()
    game._hide_or_unhide()
    game._try_grab()
    player = game.client.player
    assert player.action_mode == 0 and player.is_carrying()
    assert not game.thrown_objects


@pytest.mark.parametrize('kind', ['bush', 'stone', 'blackstone'])
def test_unhide_only_bush_throws_leaves(kind):
    # TPlayer.cpp:6414-6426: clear mode, bush leaves, then standing carry.
    game = Game(kind)
    game._hide_or_unhide()
    game._unhide()
    assert game.client.player.action_mode == 0
    assert game.client.player.carried_object_type == kind
    assert game.current_anim_name == 'carry'
    if kind == 'bush':
        # TPlayer.cpp:6420-6422; corrected X per companion burst :6039.
        game._spawn_leaps.assert_called_once_with(0, 30.5, 30.3125)
    else:
        game._spawn_leaps.assert_not_called()


def test_s_throw_ends_hiding():  # TPlayer.cpp:2032
    game = Game()
    game._hide_or_unhide()
    game._throw_object()
    player = game.client.player
    assert player.action_mode == 0 and not player.is_carrying()


def test_hidden_player_is_hittable():  # getNoHurt/getNoHit have no mode 14 clause
    game = Game()
    game._hide_or_unhide()
    assert not game.client.player.no_hurt()


def test_hidden_player_cannot_hide_while_swimming():
    game = Game()
    game.is_swimming = True
    game._hide_or_unhide()
    assert game.client.player.action_mode == 0


# One tick of held movement: 0.5 tile walking, 0.1 hidden.
@pytest.mark.parametrize("hidden,expected", [(False, 0.5), (True, 0.1)])
def test_hidden_crawl_speed(monkeypatch, hidden, expected):
    game = Game()
    game.client.clock = Clock()
    for attr in ('typing', 'show_player_list', 'show_server_list'):
        setattr(game, attr, False)
    game.dialogue_text = game.pm_target_id = None
    game.inventory_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: SimpleNamespace(visible=False)
    game._admin_overlay_captures_keys = lambda: False
    game._gs2_gui_captures_keys = lambda: False
    game._feed_gs1_input = game._fire_gs1_keypress_queue = Mock()
    game._auto_pickup_items = Mock()
    game.gs1 = SimpleNamespace(default_movement=True)
    game._clear_grab_state = Mock()
    game._move = Mock()
    game.key_just_pressed = {}
    game.grab_state = None
    game.walk_speed = c.WALK_SPEED
    game._move_accum = 0
    if hidden:
        game._hide_or_unhide()
    monkeypatch.setattr(pygame.key, 'get_pressed',
                        lambda: defaultdict(bool, {pygame.K_RIGHT: True}))
    game._handle_input(10.0)
    distance = game._move.call_count * c.MOVE_STEP + game._move_accum
    # 0.1 tiles/tick x 20 ticks/s = 2 tiles/s vs 10 tiles/s walking.
    assert distance == pytest.approx(expected)


def test_d_while_carrying_hides_instead_of_firing_weapon(monkeypatch):
    game = Game()
    game._use_weapon = Mock()
    game._clear_push_hold = Mock()
    game.current_anim_name = "carry"
    game.last_action_time = 0.0
    game.action_delay = 0.0
    game.last_sword_time = 0.0
    game.sword_delay = 0.0
    game.key_just_pressed = {pygame.K_d: True}
    for attr in ('typing', 'show_player_list', 'show_server_list'):
        setattr(game, attr, False)
    game.dialogue_text = game.pm_target_id = None
    game.inventory_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: SimpleNamespace(visible=False)
    game._admin_overlay_captures_keys = lambda: False
    game._gs2_gui_captures_keys = lambda: False
    game._feed_gs1_input = game._fire_gs1_keypress_queue = Mock()
    game._auto_pickup_items = Mock()
    game.gs1 = SimpleNamespace(default_movement=True)
    game._clear_grab_state = Mock()
    game._move = Mock()
    game.grab_state = None
    game.is_moving = False
    game.walk_speed = c.WALK_SPEED
    game._frame_dt = .1
    game._move_accum = 0
    monkeypatch.setattr(pygame.key, 'get_pressed',
                        lambda: defaultdict(bool, {pygame.K_d: True}))
    game._handle_input(10.0)
    assert game.client.player.action_mode == 14
    game._use_weapon.assert_not_called()
