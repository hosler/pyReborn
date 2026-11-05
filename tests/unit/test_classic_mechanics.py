"""Classic constants and gameplay boundaries verified against the oracle."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLPROP, PLSTATUS

from pyreborn import Client
from pyreborn.game import constants as c
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.input import InputMixin
from pyreborn.player import Player
from pyreborn.packets import PacketID


def test_classic_constants():
    assert c.WALK_SPEED == 10.0  # FourPlay TPlayer.cpp:807
    assert c.SHIELD_SPEED_MULTIPLIER == 1.2  # FourPlay TInitStatics.cpp:1243
    assert c.BOMB_FUSE_TIME == 3.0  # GServer Level.cpp:1986
    assert c.EXPLOSION_DURATION == 0.6  # 12 animate() calls × 50ms (TExplosion.cpp:101).
    assert c.THROW_DISTANCE == 9.0  # 9 ticks × 1.0 tile/tick (TPlayer.cpp:7831).
    assert c.THROW_DURATION == 0.45  # FourPlay TServerCarry.cpp:118
    assert c.DEAD_STATUS_DELAY == 1.4  # FourPlay TPlayer.cpp:2709
    assert c.REVIVAL_INPUT_DELAY == 1.5  # FourPlay TPlayer.cpp:7319
    assert Client._ARROW_SPEED == 20.0  # TClient.cpp:3653: DOUBLE_004023d8 = 1 tile/50ms tick
    assert Client._ARROW_MAX_DISTANCE == 128.0  # GServer Level.cpp:2629
    assert Client._SWORD_REACH == 4.0  # FourPlay TInitStatics.cpp:1251
    assert Client._SWORD_HALF_WIDTH == 2.0  # FourPlay TInitStatics.cpp:1277


def test_default_bomb_sends_counter_59():
    client = Client("localhost", 14900)
    client._protocol = SimpleNamespace(connected=True, send_packet=Mock(return_value=True))
    client._authenticated = True
    client.player.bombs = 1
    assert client.put_bomb()
    bomb = next(call.args[1] for call in client._protocol.send_packet.call_args_list
                if call.args[0] == PacketID.PLI_BOMBADD)
    assert bomb[-1] - 32 == 59  # GServer Level.cpp:1986


class InputHarness(InputMixin):
    def __init__(self):
        self.client = SimpleNamespace(player=Player(), _send_appearance_prop=Mock())
        self.player_anim = Mock()
        self.current_anim_name = "dead"


@pytest.mark.parametrize("key", [pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN,
                                     pygame.K_RIGHT, pygame.K_a, pygame.K_s,
                                     pygame.K_d, pygame.K_SPACE])
def test_death_status_and_first_gameplay_input(key):
    game = InputHarness()
    player = game.client.player
    player.hearts = 0
    player.status = PLSTATUS.PAUSED
    keys = defaultdict(bool, {key: True})
    assert not game._revive_on_input(0.0, keys)
    game._update_death_state(1.399)
    assert not player.status & PLSTATUS.DEAD
    game._update_death_state(1.4)
    assert player.status & PLSTATUS.DEAD  # FourPlay TPlayer.cpp:2709
    assert not game._revive_on_input(1.499, keys)
    assert not game._revive_on_input(1.5, defaultdict(bool))
    assert not game._revive_on_input(1.5, defaultdict(bool, {pygame.K_RETURN: True}))
    assert game._revive_on_input(1.5, keys)  # FourPlay TPlayer.cpp:7319
    assert player.status == PLSTATUS.PAUSED
    assert player.hearts == player.max_hearts
    game.client._send_appearance_prop.assert_any_call(PLPROP.STATUS, PLSTATUS.PAUSED)
    game.client._send_appearance_prop.assert_any_call(PLPROP.CURPOWER, int(player.max_hearts * 2))
    sent = game.client._send_appearance_prop.call_count
    assert not game._revive_on_input(2.0, keys)
    assert game.client._send_appearance_prop.call_count == sent


def test_fallback_health_clears_dead_and_resets_timer():
    game = InputHarness()
    game.client.player.hearts = 0
    game._update_death_state(0.0)
    game._update_death_state(1.4)
    game.client.player.hearts = 3
    game._update_death_state(3.0)
    assert not game.client.player.status & PLSTATUS.DEAD
    game.client.player.hearts = 0
    game._update_death_state(4.0)
    assert game._death_started == 4.0


@pytest.mark.parametrize("direction,offset", [(0, (-2, -4)), (1, (-4, -2)),
                                               (2, (-2, 0)), (3, (0, -2))])
def test_sword_rectangle_edges(direction, offset):
    client = Client("localhost", 14900)
    client.player.x, client.player.y = 30, 30
    fx, fy = client._ARROW_DIR_VECTORS[direction]
    left, top = 30 + offset[0], 30 + offset[1]
    for x, y in [(left, top), (left + 4, top), (left, top + 4), (left + 4, top + 4)]:
        assert client._target_in_sword_arc(x, y, fx, fy)  # FourPlay TPlayer.cpp:5465
    for x, y in [(left - .001, top + 2), (left + 4.001, top + 2),
                 (left + 2, top - .001), (left + 2, top + 4.001)]:
        assert not client._target_in_sword_arc(x, y, fx, fy)


def test_throw_uses_nine_tile_ground_range_and_nine_ticks():
    player = SimpleNamespace(is_carrying=lambda: True, direction=3,
                             throw_object=lambda: (2, [1, 2, 3, 4], None))
    game = SimpleNamespace(client=SimpleNamespace(player=player, x=30, y=30),
                           gani_parser=SimpleNamespace(parse=lambda _: None),
                           player_anim=Mock(), sound_mgr=Mock(), thrown_objects=[],
                           _facing_delta=lambda _: (1, 0))
    ActionsMixin._throw_object(game)
    obj, = game.thrown_objects
    assert obj['range'] == 9.0  # 9 ticks × 1.0 tile/tick (TPlayer.cpp:7831).
    assert obj['range'] / obj['speed'] == .45  # FourPlay TServerCarry.cpp:118
    assert obj['z'] == obj['z0'] > 0


@pytest.mark.parametrize("shield,swimming,expected", [(2, False, 1.0), (3, False, 1.2), (3, True, 1.0)])
def test_shield_multiplier_in_movement_input(monkeypatch, shield, swimming, expected):
    game = InputHarness()
    game.client.player.shield_power = shield
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
    game.current_anim_name = "idle"
    game.is_swimming = swimming
    game.walk_speed = c.WALK_SPEED
    game._frame_dt = .1
    game._move_accum = 0
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_RIGHT: True}))
    game._handle_input(10.0)
    distance = game._move.call_count * c.MOVE_STEP + game._move_accum
    assert distance == pytest.approx(expected)  # FourPlay TPlayer.cpp:7447
