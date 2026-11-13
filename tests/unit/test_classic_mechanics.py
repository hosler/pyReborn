"""Classic constants and gameplay boundaries verified against the oracle."""

from collections import defaultdict

import pygame
import pytest
from reborn_protocol import PLPROP, PLSTATUS

from offline_game import spy
from pyreborn import Client
from pyreborn.game import constants as c
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


def test_default_bomb_sends_counter_59(make_client):
    client = make_client()
    client.player.bombs = 1
    sent_before = len(client._protocol.sent)
    assert client.put_bomb()
    bomb = next(data for pid, data in client._protocol.sent[sent_before:]
                if pid == PacketID.PLI_BOMBADD)
    # Level.cpp:1986 fuse (counter 59) minus the owner's 5-tick latency
    # compensation, TServerLevel.cpp:1117-1119; the full fuse stays local.
    assert bomb[-1] - 32 == 54
    placed = [b for level in client.bombs.values() for b in level.values()]
    assert placed[-1]['fuse_s'] == pytest.approx(3.0)


@pytest.fixture
def dead_game(make_game, monkeypatch):
    """A real offline game dead on the floor, with a call-through spy on the
    appearance-prop sender (``game.prop_calls``)."""
    game = make_game()
    game.current_anim_name = "dead"
    game.prop_calls = spy(monkeypatch, game.client, "send_appearance_prop")
    return game


@pytest.mark.parametrize("key", [pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN,
                                     pygame.K_RIGHT, pygame.K_a, pygame.K_s,
                                     pygame.K_d, pygame.K_SPACE])
def test_death_status_and_first_gameplay_input(dead_game, key):
    game = dead_game
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
    assert ((PLPROP.STATUS, PLSTATUS.PAUSED), {}) in game.prop_calls
    assert ((PLPROP.CURPOWER, int(player.max_hearts * 2)), {}) in game.prop_calls
    sent = len(game.prop_calls)
    assert not game._revive_on_input(2.0, keys)
    assert len(game.prop_calls) == sent


def test_fallback_health_clears_dead_and_resets_timer(dead_game):
    game = dead_game
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


def test_throw_uses_nine_tile_ground_range_and_nine_ticks(make_game):
    game = make_game()
    player = game.client.player
    player.direction = 3
    player.pickup_object('bush', (1, 2, 3, 4), (0, 0))
    game._throw_object()
    obj, = game.thrown_objects
    assert obj['range'] == 9.0  # 9 ticks × 1.0 tile/tick (TPlayer.cpp:7831).
    assert obj['range'] / obj['speed'] == .45  # FourPlay TServerCarry.cpp:118
    assert obj['z'] == obj['z0'] > 0


# One tick of held movement: 0.5 tile (TPlayer.cpp:807), x1.2 with a shield.
@pytest.mark.parametrize("shield,swimming,expected", [(2, False, 0.5), (3, False, 0.6), (3, True, 0.5)])
def test_shield_multiplier_in_movement_input(make_game, monkeypatch, shield, swimming, expected):
    game = make_game()
    game.client.player.shield_power = shield
    moves = spy(monkeypatch, game, '_move')
    game.key_just_pressed = {}
    game.grab_state = None
    game.current_anim_name = "idle"
    game.is_swimming = swimming
    game.walk_speed = c.WALK_SPEED
    game._move_accum = 0
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: defaultdict(bool, {pygame.K_RIGHT: True}))
    game._handle_input(10.0)
    distance = len(moves) * c.MOVE_STEP + game._move_accum
    assert distance == pytest.approx(expected)  # FourPlay TPlayer.cpp:7447
