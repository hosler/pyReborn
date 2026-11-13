"""Swimming mode and water bursts (TPlayer.cpp:5982-6040)."""

import pytest

from .test_ground_effects import ground_tile, new_game, tile_of  # noqa: F401


def test_water_entry_and_exit_set_mode_and_burst_at_player_offset(new_game):
    # TPlayer.cpp:6010-6012,6018-6022,6039-6040.
    game = new_game()
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    assert game.is_swimming
    assert game.client.player.action_mode == 10
    assert game.current_anim_name == 'swim'
    assert game.leap_calls == [((5, 20.5, 21.75), {})]
    game._update_swimming_state()
    assert len(game.leap_calls) == 1

    ground_tile(game, tile_of(0))
    game._update_swimming_state()
    assert not game.is_swimming
    assert game.client.player.action_mode == 0
    assert game.current_anim_name == 'idle'
    assert game.leap_calls == [((5, 20.5, 21.75), {})] * 2
    # TServerLevel.cpp:2864: the burst owns the audio, one splash each.
    assert [args for args, _ in game.sound_calls] == [('water.wav',)] * 2


def test_water_to_lava_keeps_mode_and_switches_animation_without_entry_burst(new_game):
    # TPlayer.cpp:6016-6023: already swimming selects swim/lava by ground type.
    game = new_game()
    ground_tile(game, tile_of(11))
    game._update_swimming_state()
    for kind, ani in ((12, 'lava'), (11, 'swim')):
        ground_tile(game, tile_of(kind))
        game._update_swimming_state()
        assert game.client.player.action_mode == 10
        assert game.current_anim_name == ani
    assert len(game.leap_calls) == 1


@pytest.mark.parametrize('mode', [1, 3, 5, 14])
def test_leaving_water_preserves_another_action_mode(mode, new_game):
    # TPlayer.cpp:6007-6012: only mode 10 is cleared on leaving water.
    game = new_game()
    game.is_swimming = True
    game.client.player.action_mode = mode
    game._update_swimming_state()
    assert game.client.player.action_mode == mode


@pytest.mark.parametrize('state', ['jump', 'mode2', 'mode6', 'frozen',
                                  'freeze_timer', 'scripted', 'ghost'])
@pytest.mark.parametrize('swimming', [False, True])
def test_water_test_skips_rooted_frozen_and_scripted_players(state, swimming, new_game):
    # TPlayer.cpp:5990-5997: skip the whole test, in either transition direction.
    game = new_game()
    game.is_swimming = swimming
    game.client.player.action_mode = 10 if swimming else 0
    if not swimming:
        ground_tile(game, tile_of(11))
    if state == 'jump':
        game._ledge_jump = object()
    elif state in ('mode2', 'mode6'):
        game.client.player.action_mode = int(state[-1])
    elif state == 'frozen':
        game.client.frozen = True
    elif state == 'freeze_timer':
        game._frozen_until = float('inf')
    elif state == 'scripted':
        game.gs1.default_movement = False
    else:
        game.client.ghost_mode = True
    mode = game.client.player.action_mode
    game._update_swimming_state()
    assert game.is_swimming is swimming
    assert game.client.player.action_mode == mode
    assert game.anim_calls == []
    assert game.leap_calls == []
