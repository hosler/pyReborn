import math
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

pygame.init()
pygame.display.set_mode((64, 64))

from pygame.locals import K_a, K_d, K_s, K_SPACE, K_UP, K_DOWN, K_LEFT, K_RIGHT

from offline_game import spy
from pyreborn import ground_items as gi
from pyreborn.packets import LEVEL_ITEM_NAMES

ITEM_ID = {name: i for i, name in LEVEL_ITEM_NAMES.items()}
LEVEL = 'fixture.nw'


def _age(time_left):
    """Seconds since first seen for an oracle `m_time` of `time_left`."""
    return (gi.ITEM_LIFETIME_TICKS - time_left) * gi.TICK + gi.TICK / 2


# --- pickup radius ----------------------------------------------------------

def test_pickup_range_is_strictly_under_two_tiles_from_player_centre():
    # player centre (x+1.5, y+2.0) vs item centre (x+1.0, y+1.0)
    assert gi.within_pickup_range(10.0, 10.0, 10.0, 10.0)
    assert gi.within_pickup_range(10.0, 10.0, 11.4, 10.0)      # dx 1.5-2.4 = -0.9... in
    assert not gi.within_pickup_range(10.0, 10.0, 8.5, 10.0)   # dx = 2.0
    assert gi.within_pickup_range(10.0, 10.0, 8.6, 10.0)       # dx = 1.9
    assert not gi.within_pickup_range(10.0, 10.0, 10.0, 13.0)  # dy = -2.0 -> not <2
    assert gi.within_pickup_range(10.0, 10.0, 10.0, 12.9)      # dy = -1.9


def test_pickup_has_a_four_tick_grace_and_ends_at_expiry():
    assert not gi.pickup_ready(0.0)                      # time 164
    assert not gi.pickup_ready(_age(160))                # needs time < 160
    assert gi.pickup_ready(_age(159))
    assert gi.pickup_ready(_age(0))
    assert not gi.pickup_ready(_age(-1))
    assert gi.item_expired(_age(-1)) and not gi.item_expired(_age(0))


def test_walkover_only_takes_giveaway_items_in_range_and_ready():
    items = {(10.0, 10.0): 'greenrupee', (10.0, 10.5): 'glove1',
             (40.0, 40.0): 'heart', (10.5, 10.0): 'bluerupee'}
    ages = {k: 5.0 for k in items}
    ages[(10.5, 10.0)] = 0.0                              # still in grace
    assert gi.walkover_takes(10.0, 10.0, items, ages) == [(10.0, 10.0)]


def test_walkover_absorbs_the_non_giveaway_kinds_locally():
    items = {(10.0, 10.0): 'greenrupee', (10.0, 10.5): 'glove1',
             (40.0, 40.0): 'sword', (10.5, 10.0): 'mirrorshield'}
    ages = {k: 5.0 for k in items}
    ages[(10.5, 10.0)] = 0.0                              # still in grace
    assert gi.walkover_absorbs(10.0, 10.0, items, ages) == [(10.0, 10.5)]


@pytest.fixture
def pickup_game(make_game, monkeypatch):
    """``pickup_game(player_xy, items, take_ok=True, **knobs)``: a real offline
    game whose level holds ``items`` (``{(x, y): name}``), each stamped as
    arrived two seconds ago (``client.item_stamps``), with the player at ``player_xy`` (world). Call-through
    spies: ``game.pickups`` (client.pickup_item), ``game.removals``
    (client.remove_item_local), ``game.sound_calls`` (sound_mgr.play).
    ``take_ok=False`` makes ``pickup_item`` report that nothing was sent."""
    def build(player_xy, items, take_ok=True, **knobs):
        game = make_game(items=[(x, y, ITEM_ID[name])
                                for (x, y), name in items.items()], **knobs)
        client = game.client
        client.player.x, client.player.y = player_xy
        level = client.get_current_level_from_position()
        for pos in client.items_in_level(level):
            client.item_stamps[(level, pos)] = game.clock.sim_now() - 2.0
        if not take_ok:
            monkeypatch.setattr(client, 'pickup_item', lambda *a, **k: False)
        game.pickups = spy(monkeypatch, client, 'pickup_item')
        game.removals = spy(monkeypatch, client, 'remove_item_local')
        game.sound_calls = spy(monkeypatch, game.sound_mgr, 'play')
        game.level = level
        return game
    return build


def test_auto_pickup_removes_non_giveaway_items_without_sending(pickup_game):
    game = pickup_game((10.0, 10.0), {(10.0, 10.0): 'glove1'})
    assert game._auto_pickup_items() == 0
    assert game.pickups == []
    assert game.removals == [((game.level, 10.0, 10.0), {})]
    assert game.client.items_in_level(game.level) == {}


def test_item_ages_forgets_removed_items_and_allows_retake():
    owner = SimpleNamespace()
    key = (5.0, 5.0)
    assert gi.item_ages(owner, 'a.nw', {key: 'heart'}, 100.0)[key] == 0.0
    assert gi.item_ages(owner, 'a.nw', {key: 'heart'}, 101.5)[key] == 1.5
    owner._item_take_sent.add(('a.nw', key))
    gi.item_ages(owner, 'a.nw', {}, 102.0)
    assert not owner._item_take_sent
    assert gi.item_ages(owner, 'a.nw', {key: 'heart'}, 103.0)[key] == 0.0


# --- ActionsMixin walk-over wiring -----------------------------------------

def test_auto_pickup_sends_one_take_per_item_until_server_removes_it(pickup_game):
    game = pickup_game((10.0, 10.0), {(10.0, 10.0): 'greenrupee'})
    client = game.client
    assert game._auto_pickup_items() == 1
    assert game.pickups == [((10.0, 10.0), {})]
    assert game.sound_calls == [(("item.wav",), {})]
    assert game._auto_pickup_items() == 0          # deduped
    client.items_in_level(game.level).clear()      # server removed it
    game._auto_pickup_items()
    client.items_in_level(game.level)[(10.0, 10.0)] = 'greenrupee'   # dropped again
    client.item_stamps[(game.level, (10.0, 10.0))] = game.clock.sim_now() - 2.0
    assert game._auto_pickup_items() == 1


def test_auto_pickup_ignores_far_items_and_unsent_takes_retry(pickup_game, monkeypatch):
    game = pickup_game((10.0, 10.0), {(30.0, 30.0): 'heart'})
    assert game._auto_pickup_items() == 0
    game = pickup_game((10.0, 10.0), {(10.0, 10.0): 'heart'}, take_ok=False)
    assert game._auto_pickup_items() == 0
    monkeypatch.undo()                 # the take can now be sent
    assert game._auto_pickup_items() == 1


def test_auto_pickup_converts_world_position_to_level_local(pickup_game):
    # GMAP segment (1, 0): world x 74 is local 10
    game = pickup_game((74.0, 10.0), {(10.0, 10.0): 'heart'},
                       gmap=True, gmap_segment=(1, 0))
    assert game._auto_pickup_items() == 1


# --- bob / blink ------------------------------------------------------------

def test_blink_hides_odd_ticks_at_or_below_36_only():
    assert gi.item_blink_hidden(_age(35))
    assert not gi.item_blink_hidden(_age(34))
    assert gi.item_blink_hidden(_age(1))
    assert not gi.item_blink_hidden(_age(0))
    assert not gi.item_blink_hidden(_age(37))        # odd but above the window
    assert not gi.item_blink_hidden(_age(100))


def test_bob_is_a_decaying_bounce_that_stops_below_time_142():
    assert gi.item_bob_tiles(_age(141)) == 0.0
    assert gi.item_bob_tiles(_age(100)) == 0.0
    t = 150
    expected = abs(math.sin(t / 3.0)) * (t / 164.0) ** 16 * 3.0
    assert gi.item_bob_tiles(_age(t)) == expected
    assert gi.item_bob_tiles(_age(164)) <= 3.0
    peak = max(gi.item_bob_tiles(_age(t)) for t in range(143, 164))
    assert peak > gi.item_bob_tiles(_age(143))


def test_lifetime_constants_match_the_oracle():
    assert (gi.ITEM_LIFETIME_TICKS, gi.BLINK_TICKS) == (0xa4, 0x24)


# --- grant table ------------------------------------------------------------

def test_item_tables_match_the_oracle():
    assert list(gi.ITEM_NAMES) == [LEVEL_ITEM_NAMES[i] for i in range(25)]
    assert sorted(gi.ITEMS_GIVEAWAY) == [0, 1, 2, 3, 4, 5, 7, 8, 15, 19]
    assert len(gi.GIVE_ORDER) == 24 and set(gi.GIVE_ORDER) == set(range(25)) - {11}


def test_only_items_with_a_default_script_grant_a_weapon():
    assert gi.WEAPON_GRANTS == {
        7: 'Bow', 8: 'Bomb', 12: 'Superbomb', 20: 'Fireball',
        21: 'Fireblast', 22: 'Nukeshot', 23: 'Joltbomb'}


def test_next_give_item_walks_giveorder_and_skips_unavailable():
    everything = lambda i: i in (0, 1, 2, 19, 3, 4, 5)
    assert gi.next_give_item(everything, None) == 0
    assert gi.next_give_item(everything, 0) == 1
    assert gi.next_give_item(everything, 2) == 19           # order is 0,1,2,19,3...
    assert gi.next_give_item(everything, 5) == 0            # wraps
    assert gi.next_give_item(lambda i: i == 4, None) == 4
    assert gi.next_give_item(lambda i: False, None) == -1


def test_giveaway_availability_thresholds():
    assert gi.giveaway_available(0, 1, 0, 0, 0)
    assert not gi.giveaway_available(1, 4, 0, 0, 0) and gi.giveaway_available(1, 5, 0, 0, 0)
    assert not gi.giveaway_available(2, 29, 0, 0, 0) and gi.giveaway_available(2, 30, 0, 0, 0)
    assert not gi.giveaway_available(19, 99, 0, 0, 0) and gi.giveaway_available(19, 100, 0, 0, 0)
    assert gi.giveaway_available(3, 0, 5, 0, 0) and not gi.giveaway_available(3, 0, 4, 0, 0)
    assert gi.giveaway_available(4, 0, 0, 5, 0) and not gi.giveaway_available(4, 0, 0, 4, 0)
    assert gi.giveaway_available(5, 0, 0, 0, 1.5) and not gi.giveaway_available(5, 0, 0, 0, 1.0)


def test_drop_position_uses_layd_offsets_snapped_to_half_tiles():
    assert gi.drop_position(10.0, 10.0, 0) == (10.5, 8.0)
    assert gi.drop_position(10.0, 10.0, 1) == (8.5, 11.0)
    assert gi.drop_position(10.0, 10.0, 2) == (10.5, 13.0)
    assert gi.drop_position(10.0, 10.0, 3) == (12.5, 11.0)
    # a freshly laid item is just out of its own pickup range
    for d in range(4):
        x, y = gi.drop_position(10.0, 10.0, d)
        assert not gi.within_pickup_range(10.0, 10.0, x, y)


def test_giveaway_drop_costs_the_stat_and_lays_the_item(make_game, monkeypatch):
    from reborn_protocol import PLPROP
    game = make_game(player_xy=(10.0, 10.0))
    client = game.client
    player = client.player
    player.x, player.y, player.direction = 10.0, 10.0, 3
    player.rupees, player.bombs, player.arrows, player.hearts = 40, 0, 0, 3.0
    player.action_mode = 9
    game._giveaway_item = 2
    level = client.get_current_level_from_position()
    client.items.pop(level, None)
    props = spy(monkeypatch, client, 'send_appearance_prop')
    adds = spy(monkeypatch, client, 'send_item_add')
    assert game._giveaway_drop() is True
    assert player.rupees == 10
    assert props == [((PLPROP.RUPEESCOUNT, 10), {})]
    assert adds == [((12.5, 11.0, 2), {})]
    assert client.items == {level: {(12.5, 11.0): 'redrupee'}}
    assert game._giveaway_item is None
    assert player.action_mode == 0
    game._giveaway_item = 2
    assert game._giveaway_drop() is False        # 10 < 30 now
    assert player.rupees == 10


# --- chords -----------------------------------------------------------------

class _Keys:
    def __init__(self, *held):
        self._held = set(held)

    def __getitem__(self, key):
        return key in self._held

    def __len__(self):
        return 512


@pytest.fixture
def chord(make_game, monkeypatch):
    """``chord(real_giveaway=False)``: a real offline game driven through the
    REAL _handle_input, with the dispatch targets recording into
    ``game.calls`` ('auto_pickup', 'cycle', 'giveaway', 'drop', 'use_weapon',
    'sword') instead of running. ``real_giveaway=True`` keeps the real
    _giveaway_select / _giveaway_drop and gives the player 40 rupees, 5 bombs
    and 5 arrows; ``game.sound_calls`` and ``game.item_adds`` spy on the
    sound manager and client.send_item_add."""
    def build(real_giveaway=False):
        game = make_game()
        game.frames(1)
        game.gs1.default_movement = True
        game.calls = []
        targets = {'_auto_pickup_items': 'auto_pickup', '_cycle_weapon': 'cycle',
                   '_use_weapon': 'use_weapon', '_swing_sword': 'sword'}
        if not real_giveaway:
            targets.update({'_giveaway_select': 'giveaway',
                            '_giveaway_drop': 'drop'})
        for name, label in targets.items():
            monkeypatch.setattr(game, name,
                                lambda *a, _l=label, **k: game.calls.append(_l))
        player = game.client.player
        player.hearts = 3.0
        if real_giveaway:
            player.rupees, player.bombs, player.arrows = 40, 5, 5
        game.sound_calls = spy(monkeypatch, game.sound_mgr, 'play')
        game.item_adds = spy(monkeypatch, game.client, 'send_item_add')
        return game
    return build


def _press(harness, held, just, now=100.0):
    harness.key_just_pressed = {k: True for k in just}
    orig = pygame.key.get_pressed
    pygame.key.get_pressed = lambda: _Keys(*held)
    try:
        harness._handle_input(now)
    finally:
        pygame.key.get_pressed = orig


def test_s_plus_d_cycles_weapons(chord):
    h = chord()
    _press(h, {K_s, K_d}, {K_d})
    assert h.calls == ['auto_pickup', 'cycle']


def test_s_plus_a_is_the_item_giveaway_not_weapon_cycle(chord):
    h = chord()
    _press(h, {K_s, K_a}, {K_a})
    assert h.calls == ['auto_pickup', 'giveaway']


def test_bare_a_drops_while_giveaway_is_up(chord):
    h = chord()
    h._giveaway_item = 2
    _press(h, {K_a}, {K_a})
    assert h.calls == ['auto_pickup', 'drop']
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0


def test_hold_s_and_tap_a_cycles_between_releases_without_cooldown(chord):
    h = chord(real_giveaway=True)
    # TPlayer.cpp:2220-2230: A presses cycle; held/released keys do nothing.
    for tap, item in enumerate((0, 1, 2, 3, 4, 5, 0)):
        now = 100.0 + tap * 0.02
        _press(h, {K_s, K_a}, {K_a}, now)
        assert h._giveaway_item == item
        assert h.client.player.action_mode == 9
        _press(h, {K_s, K_a}, set(), now + 0.005)
        _press(h, {K_s}, set(), now + 0.01)
        assert h._giveaway_item == item
        assert h.client.player.action_mode == 9
    assert len(h.sound_calls) == 7
    assert all(args == ('item2.wav',) for args, _ in h.sound_calls)


def test_releasing_s_or_a_preserves_selection_then_bare_a_lays_it(chord):
    h = chord(real_giveaway=True)
    _press(h, {K_s, K_a}, {K_a})
    _press(h, {K_a}, set())  # Releasing S while A remains held cannot drop.
    _press(h, set(), set())
    assert h._giveaway_item == 0
    assert h.client.player.action_mode == 9
    assert not h.item_adds
    _press(h, {K_a}, {K_a})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert h.client.player.rupees == 39
    assert len(h.item_adds) == 1
    assert h.sound_calls[-1] == (('item.wav',), {})


@pytest.mark.parametrize('key', [K_UP, K_DOWN, K_LEFT, K_RIGHT, K_d, K_SPACE, K_s])
def test_only_fresh_other_gameplay_presses_end_selection(chord, key):
    h = chord(real_giveaway=True)
    _press(h, {K_s, K_a}, {K_a})
    _press(h, {key}, set())
    assert h._giveaway_item == 0
    assert h.client.player.action_mode == 9
    _press(h, {key}, {key})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert set(h.calls) == {'auto_pickup'}
    assert not h.item_adds


def test_pressing_s_while_a_is_held_does_not_enter_selection(chord):
    h = chord()
    _press(h, {K_s, K_a}, {K_s})
    assert h.calls == ['auto_pickup']


def test_bare_a_ends_selection_even_if_selected_item_is_no_longer_available(chord):
    h = chord(real_giveaway=True)
    _press(h, {K_s, K_a}, {K_a})
    h.client.player.rupees = 0
    _press(h, {K_a}, {K_a})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert not h.item_adds
