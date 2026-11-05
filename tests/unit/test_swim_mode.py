"""Swimming mode and water bursts (TPlayer.cpp:5982-6040)."""

from types import SimpleNamespace
from unittest.mock import call

import pytest

from .test_ground_effects import Game, tile_of


def test_water_entry_and_exit_set_mode_and_burst_at_player_offset():
    # TPlayer.cpp:6010-6012,6018-6022,6039-6040.
    game = Game()
    game.ground_tile(tile_of(11))
    game._update_swimming_state()
    assert game.is_swimming
    assert game.client.player.action_mode == 10
    assert game.current_anim_name == 'swim'
    game._spawn_leaps.assert_called_once_with(5, 20.5, 21.75)
    game._update_swimming_state()
    game._spawn_leaps.assert_called_once()

    game.ground_tile(tile_of(0))
    game._update_swimming_state()
    assert not game.is_swimming
    assert game.client.player.action_mode == 0
    assert game.current_anim_name == 'idle'
    assert game._spawn_leaps.call_args_list == [call(5, 20.5, 21.75)] * 2
    game.sound_mgr.play.assert_not_called()  # TServerLevel.cpp:2864: burst owns audio.


def test_water_to_lava_keeps_mode_and_switches_animation_without_entry_burst():
    # TPlayer.cpp:6016-6023: already swimming selects swim/lava by ground type.
    game = Game()
    game.ground_tile(tile_of(11))
    game._update_swimming_state()
    for kind, ani in ((12, 'lava'), (11, 'swim')):
        game.ground_tile(tile_of(kind))
        game._update_swimming_state()
        assert game.client.player.action_mode == 10
        assert game.current_anim_name == ani
    game._spawn_leaps.assert_called_once()


@pytest.mark.parametrize('mode', [1, 3, 5, 14])
def test_leaving_water_preserves_another_action_mode(mode):
    # TPlayer.cpp:6007-6012: only mode 10 is cleared on leaving water.
    game = Game()
    game.is_swimming = True
    game.client.player.action_mode = mode
    game._update_swimming_state()
    assert game.client.player.action_mode == mode


@pytest.mark.parametrize('state', ['jump', 'mode2', 'mode6', 'frozen',
                                  'freeze_timer', 'scripted', 'ghost'])
@pytest.mark.parametrize('swimming', [False, True])
def test_water_test_skips_rooted_frozen_and_scripted_players(state, swimming):
    # TPlayer.cpp:5990-5997: skip the whole test, in either transition direction.
    game = Game()
    game.is_swimming = swimming
    game.client.player.action_mode = 10 if swimming else 0
    if not swimming:
        game.ground_tile(tile_of(11))
    if state == 'jump':
        game._ledge_jump = object()
    elif state in ('mode2', 'mode6'):
        game.client.player.action_mode = int(state[-1])
    elif state == 'frozen':
        game.client.frozen = True
    elif state == 'freeze_timer':
        game._frozen_until = float('inf')
    elif state == 'scripted':
        game.gs1 = SimpleNamespace(default_movement=False)
    else:
        game.client.ghost_mode = True
    mode = game.client.player.action_mode
    game._update_swimming_state()
    assert game.is_swimming is swimming
    assert game.client.player.action_mode == mode
    game.player_anim.set_animation.assert_not_called()
    game._spawn_leaps.assert_not_called()
