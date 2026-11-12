"""Classic ground-item rules (pyreborn/ground_items.py): walk-over pickup,
bob/blink presentation, weapon-grant table, and the S+D / S+A chords.

Numbers are transcribed from the decompiled client under
Preagonal/FourPlay/quattroplay/src/ (TServerLevel.cpp animateExtras/putExtra,
TServerExtra.cpp draw, TPlayer.cpp nextGiveItem/loseItem, TInitStatics.cpp
tables)."""

import math
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

pygame.init()
pygame.display.set_mode((64, 64))

from pygame.locals import K_a, K_d, K_s, K_SPACE, K_UP, K_DOWN, K_LEFT, K_RIGHT

from pyreborn.clock import Clock
from pyreborn import ground_items as gi
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.input import InputMixin
from pyreborn.packets import LEVEL_ITEM_NAMES


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


def test_auto_pickup_removes_non_giveaway_items_without_sending():
    items = {(10.0, 10.0): 'glove1'}
    game = _pickup_game((10.0, 10.0), items)
    game.client.remove_item_local = Mock(
        side_effect=lambda level, x, y: items.pop((x, y), None))
    assert ActionsMixin._auto_pickup_items(game) == 0
    game.client.pickup_item.assert_not_called()
    game.client.remove_item_local.assert_called_once_with('a.nw', 10.0, 10.0)
    assert items == {}


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

def _pickup_game(player_xy, items, take_ok=True):
    client = SimpleNamespace(
        connected=True, authenticated=True,
        player=SimpleNamespace(x=player_xy[0], y=player_xy[1]),
        get_current_level_from_position=lambda: 'a.nw',
        items_in_level=lambda name: items,
        pickup_item=Mock(return_value=take_ok),
    )
    clock = Clock()
    return SimpleNamespace(client=client, sound_mgr=Mock(), clock=clock,
                           _item_first_seen={('a.nw', k): clock.sim_now() - 2.0 for k in items})


def test_auto_pickup_sends_one_take_per_item_until_server_removes_it():
    items = {(10.0, 10.0): 'greenrupee'}
    game = _pickup_game((10.0, 10.0), items)
    assert ActionsMixin._auto_pickup_items(game) == 1
    game.client.pickup_item.assert_called_once_with(10.0, 10.0)
    game.sound_mgr.play.assert_called_once_with("item.wav")
    assert ActionsMixin._auto_pickup_items(game) == 0          # deduped
    items.clear()                                              # server removed it
    ActionsMixin._auto_pickup_items(game)
    items[(10.0, 10.0)] = 'greenrupee'                         # dropped again
    game._item_first_seen[('a.nw', (10.0, 10.0))] = game.clock.sim_now() - 2.0
    assert ActionsMixin._auto_pickup_items(game) == 1


def test_auto_pickup_ignores_far_items_and_unsent_takes_retry():
    game = _pickup_game((10.0, 10.0), {(30.0, 30.0): 'heart'})
    assert ActionsMixin._auto_pickup_items(game) == 0
    game = _pickup_game((10.0, 10.0), {(10.0, 10.0): 'heart'}, take_ok=False)
    assert ActionsMixin._auto_pickup_items(game) == 0
    game.client.pickup_item.return_value = True
    assert ActionsMixin._auto_pickup_items(game) == 1


def test_auto_pickup_converts_world_position_to_level_local():
    # GMAP segment (1, 0): world x 74 is local 10
    game = _pickup_game((74.0, 10.0), {(10.0, 10.0): 'heart'})
    assert ActionsMixin._auto_pickup_items(game) == 1


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


def test_giveaway_drop_costs_the_stat_and_lays_the_item():
    from reborn_protocol import PLPROP
    player = SimpleNamespace(x=10.0, y=10.0, direction=3, rupees=40, bombs=0,
                             arrows=0, hearts=3.0)
    client = SimpleNamespace(
        player=player, items={}, send_appearance_prop=Mock(),
        send_item_add=Mock(return_value=True),
        get_current_level_from_position=lambda: 'a.nw')
    player.action_mode = 9
    game = SimpleNamespace(client=client, sound_mgr=Mock(), clock=Clock(),
                           _giveaway_item=2)
    game._giveaway_stats = lambda: ActionsMixin._giveaway_stats(game)
    assert ActionsMixin._giveaway_drop(game) is True
    assert player.rupees == 10
    client.send_appearance_prop.assert_called_once_with(PLPROP.RUPEESCOUNT, 10)
    client.send_item_add.assert_called_once_with(12.5, 11.0, 2)
    assert client.items == {'a.nw': {(12.5, 11.0): 'redrupee'}}
    assert game._giveaway_item is None
    assert player.action_mode == 0
    game._giveaway_item = 2
    assert ActionsMixin._giveaway_drop(game) is False        # 10 < 30 now
    assert player.rupees == 10


# --- chords -----------------------------------------------------------------

class _Keys:
    def __init__(self, *held):
        self._held = set(held)

    def __getitem__(self, key):
        return key in self._held

    def __len__(self):
        return 512


class _UI:
    visible = False


class _ChordHarness(InputMixin):
    def __init__(self):
        self.client = SimpleNamespace(
            player=SimpleNamespace(hearts=3.0, direction=0),
            input_frozen=False, local_level_transition='')
        self.gs1 = SimpleNamespace(default_movement=True, keys_dir=set(),
                                   keys_raw=set())
        self.typing = False
        self.dialogue_text = None
        self.inventory_ui = _UI()
        self.show_player_list = self.show_server_list = False
        self.pm_target_id = None
        self.key_just_pressed = {}
        self.last_action_time = 0.0
        self.action_delay = 0.3
        self._frozen_until = 0.0
        self._vk_cache = {}
        self.is_moving = False
        self.calls = []

    def _ensure_settings_ui(self):
        return _UI()

    def _gs2_gui_captures_keys(self):
        return False

    def _feed_gs1_input(self, keys):
        pass

    def _fire_gs1_keypress_queue(self):
        pass

    def _auto_pickup_items(self):
        self.calls.append('auto_pickup')

    def _clear_grab_state(self):
        pass

    def _clear_push_hold(self):
        pass

    def _cycle_weapon(self):
        self.calls.append('cycle')

    def _giveaway_select(self):
        self.calls.append('giveaway')

    def _giveaway_drop(self):
        self.calls.append('drop')

    def _use_weapon(self):
        self.calls.append('use_weapon')

    def _swing_sword(self):
        self.calls.append('sword')


def _press(harness, held, just, now=100.0):
    harness.key_just_pressed = {k: True for k in just}
    orig = pygame.key.get_pressed
    pygame.key.get_pressed = lambda: _Keys(*held)
    try:
        harness._handle_input(now)
    finally:
        pygame.key.get_pressed = orig


def test_s_plus_d_cycles_weapons():
    h = _ChordHarness()
    _press(h, {K_s, K_d}, {K_d})
    assert h.calls == ['auto_pickup', 'cycle']


def test_s_plus_a_is_the_item_giveaway_not_weapon_cycle():
    h = _ChordHarness()
    _press(h, {K_s, K_a}, {K_a})
    assert h.calls == ['auto_pickup', 'giveaway']


def test_bare_a_drops_while_giveaway_is_up():
    h = _ChordHarness()
    h._giveaway_item = 2
    _press(h, {K_a}, {K_a})
    assert h.calls == ['auto_pickup', 'drop']
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0


class _GiveawayInputHarness(_ChordHarness, ActionsMixin):
    _giveaway_select = ActionsMixin._giveaway_select
    _giveaway_drop = ActionsMixin._giveaway_drop

    def __init__(self):
        super().__init__()
        from pyreborn.player import Player
        self.client.player = Player(rupees=40, bombs=5, arrows=5)
        self.client.items = {}
        self.client.send_appearance_prop = Mock()
        self.client.send_item_add = Mock(return_value=True)
        self.client.get_current_level_from_position = lambda: 'a.nw'
        self.sound_mgr = Mock()
        self._play_action_animation = Mock()


def test_hold_s_and_tap_a_cycles_between_releases_without_cooldown():
    h = _GiveawayInputHarness()
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
    assert h.sound_mgr.play.call_count == 7
    assert all(call.args == ('item2.wav',) for call in h.sound_mgr.play.call_args_list)


def test_releasing_s_or_a_preserves_selection_then_bare_a_lays_it():
    h = _GiveawayInputHarness()
    _press(h, {K_s, K_a}, {K_a})
    _press(h, {K_a}, set())  # Releasing S while A remains held cannot drop.
    _press(h, set(), set())
    assert h._giveaway_item == 0
    assert h.client.player.action_mode == 9
    assert not h.client.send_item_add.called
    _press(h, {K_a}, {K_a})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert h.client.player.rupees == 39
    h.client.send_item_add.assert_called_once()
    h.sound_mgr.play.assert_called_with('item.wav')


@pytest.mark.parametrize('key', [K_UP, K_DOWN, K_LEFT, K_RIGHT, K_d, K_SPACE, K_s])
def test_only_fresh_other_gameplay_presses_end_selection(key):
    h = _GiveawayInputHarness()
    _press(h, {K_s, K_a}, {K_a})
    _press(h, {key}, set())
    assert h._giveaway_item == 0
    assert h.client.player.action_mode == 9
    _press(h, {key}, {key})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert set(h.calls) == {'auto_pickup'}
    assert not h.client.send_item_add.called


def test_pressing_s_while_a_is_held_does_not_enter_selection():
    h = _ChordHarness()
    _press(h, {K_s, K_a}, {K_s})
    assert h.calls == ['auto_pickup']


def test_bare_a_ends_selection_even_if_selected_item_is_no_longer_available():
    h = _GiveawayInputHarness()
    _press(h, {K_s, K_a}, {K_a})
    h.client.player.rupees = 0
    _press(h, {K_a}, {K_a})
    assert h._giveaway_item is None
    assert h.client.player.action_mode == 0
    assert not h.client.send_item_add.called
