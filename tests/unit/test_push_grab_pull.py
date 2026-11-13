"""Unit tests for the push/grab/pull hold-state feel mechanics
(game/actions.py's _update_push_hold / _update_grab_pull_state and their
_clear_* counterparts):

- Push: holding a movement key into a wall for PUSH_HOLD_TIME switches to
  the "push" gani.
- Grab: holding A (grab) while facing a plain blocking wall tile (nothing
  liftable/interactable) shows "grab".
- Pull: while grabbing, also holding the movement key OPPOSITE the grabbed
  facing switches to "pull" without re-facing that direction.

Push/pull also dispatch point-based NPC actions; test_batch_a.py checks
the timing, direction parameter and script delivery.

Uses the same minimal ActionsMixin+CollisionMixin harness pattern as
tests/unit/test_swimming_state.py, extended with the handful of extra
attributes _move()/_try_link_warp() touch.
"""

from unittest.mock import Mock

import pytest

from offline_game import spy
from pyreborn.game.constants import PUSH_HOLD_TIME
from pyreborn.tiletypes import is_blocking


# Derived from the loaded type table; the per-client tile-type override layer
# that used to fabricate a blocking id is gone.
WALL = next(t for t in range(4096) if is_blocking(t))


@pytest.fixture
def facing_wall(make_game, monkeypatch):
    """``facing_wall(direction=0)``: (client, real offline game) with the box
    already touching a wall (row 20, columns 20-44) to the given facing, and
    nothing liftable/chest/door/sign there. ``game.sent_anims`` lists the
    gani names the client broadcast (call-through spy on set_animation)."""
    def build(direction=0, wall=True):
        def tiles(tx, ty):
            return WALL if wall and ty == 20 and 20 <= tx < 45 else 0
        y = 19.5 if wall else 30.0
        game = make_game(player_xy=(30.0, y), tiles=tiles)
        game.client.player.direction = direction
        calls = spy(monkeypatch, game.client, "set_animation")
        game.sent_anims = _Names(calls)
        return game.client, game
    return build


class _Names:
    """The first argument of each recorded call."""

    def __init__(self, calls):
        self._calls = calls

    def __contains__(self, name):
        return any(args[0] == name for args, _ in self._calls)


class TestPushHoldState:
    def test_push_repeats_after_twenty_ticks_with_sound(self, facing_wall, sim_time, monkeypatch):
        # TPlayer.cpp:7531-7544,7558-7561: move and sound on each 20-tick cycle.
        now = [100.0]
        sim_time(lambda: now[0])
        _, h = facing_wall()
        monkeypatch.setattr(h, '_stone_action', Mock())
        plays = spy(monkeypatch, h.sound_mgr, 'play')
        h._update_push_hold(0, -1)
        now[0] = 100.999
        h._update_push_hold(0, -1)
        h._stone_action.assert_not_called()
        now[0] = 101.0
        h._update_push_hold(0, -1)
        h._stone_action.assert_called_once_with('push', 0)
        assert plays == [(('stonemove.wav',), {})]
        now[0] = 101.9
        h._update_push_hold(0, -1)
        assert h._stone_action.call_count == len(plays) == 1
        now[0] = 102.0
        h._update_push_hold(0, -1)
        assert h._stone_action.call_count == len(plays) == 2
        h._update_push_hold(0, -1)
        assert h._stone_action.call_count == 2

    def test_direction_change_resets_repeat_cycle_and_counter(self, facing_wall, sim_time, monkeypatch):
        # TPlayer.cpp:7529-7531: starting a new push resets the mode counter.
        now = [100.0]
        sim_time(lambda: now[0])
        _, h = facing_wall()
        monkeypatch.setattr(h, '_stone_action', Mock())
        h._update_push_hold(0, -1)
        now[0] = 102.0
        h._update_push_hold(0, -1)
        h._update_push_hold(1, 0)
        assert h._push_counter == 38
        assert h._push_fire_cycle == -1
        assert not h.is_pushing
        now[0] = 102.9
        h._update_push_hold(1, 0)
        assert h._stone_action.call_count == 1
        now[0] = 103.0
        h._update_push_hold(1, 0)
        assert h._stone_action.call_count == 2
        h._stone_action.assert_called_with('push', 3)

    @pytest.mark.parametrize('scripted,animation_sound', [(True, False), (False, True)])
    def test_push_sound_leaves_scripted_movement_and_animation_audio_alone(self, facing_wall, sim_time, monkeypatch, scripted, animation_sound):
        # TPlayer.cpp:7535: only default movement owns the built-in sound.
        now = [100.0]
        sim_time(lambda: now[0])
        _, h = facing_wall()
        monkeypatch.setattr(h, '_stone_action', Mock())
        plays = spy(monkeypatch, h.sound_mgr, 'play')
        h.gs1.default_movement = not scripted
        monkeypatch.setattr(h, '_gani_plays_sound', lambda name: animation_sound)
        h._update_push_hold(0, -1)
        now[0] = 101.0
        h._update_push_hold(0, -1)
        h._stone_action.assert_called_once_with('push', 0)
        assert plays == []

    def test_short_block_does_not_push(self, facing_wall):
        c, h = facing_wall()
        h._update_push_hold(0, -1)
        assert h.is_pushing is False
        assert h.current_anim_name != "push"

    def test_held_past_threshold_switches_to_push(self, facing_wall):
        c, h = facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = h.clock.sim_now() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)

        assert h.is_pushing is True
        assert h.current_anim_name == "push"
        assert "push" in h.sent_anims

    def test_changing_direction_resets_the_hold_timer(self, facing_wall):
        c, h = facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = h.clock.sim_now() - (PUSH_HOLD_TIME + 0.1)
        # Switch to a different held direction: the timer must restart, not
        # carry over the elapsed time from the old direction.
        h._update_push_hold(1, 0)

        assert h.is_pushing is False
        assert h._push_hold_dir == (1, 0)

    def test_clear_push_hold_resets_state(self, facing_wall):
        c, h = facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = h.clock.sim_now() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)
        assert h.is_pushing is True

        h._clear_push_hold()
        assert h.is_pushing is False
        assert h._push_hold_dir is None

    def test_carrying_never_pushes(self, facing_wall):
        c, h = facing_wall()
        c.player.pickup_object("bush", (1, 2, 3, 4), (30, 19))
        assert c.player.is_carrying() is True

        h._push_hold_dir = (0, -1)
        h._push_hold_start = h.clock.sim_now() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)

        assert h.is_pushing is False
        assert h.current_anim_name != "push"


class TestGrabPullState:
    def test_a_alone_facing_wall_enters_grab(self, facing_wall):
        c, h = facing_wall(direction=0)  # facing up, into the wall
        h._update_grab_pull_state(0, 0)

        assert h.grab_state == "grab"
        assert h._grab_direction == 0
        assert h.current_anim_name == "grab"
        assert "grab" in h.sent_anims

    def test_a_alone_facing_open_ground_does_not_grab(self, facing_wall):
        c, h = facing_wall(direction=0, wall=False)

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None

    def test_holding_opposite_direction_switches_to_pull(self, facing_wall):
        c, h = facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        # Facing up (0); opposite is down (dy=+1).
        h._update_grab_pull_state(0, 1)
        assert h.grab_state == "pull"
        # Facing stays pinned on the grabbed wall, not spun to face down.
        assert h._grab_direction == 0
        assert "pull" in h.sent_anims

    def test_releasing_opposite_direction_returns_to_grab(self, facing_wall):
        c, h = facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        h._update_grab_pull_state(0, 1)
        assert h.grab_state == "pull"

        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

    def test_a_non_opposite_direction_does_not_pull(self, facing_wall):
        c, h = facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        # Sideways, not the opposite of "up" — should stay "grab", not "pull".
        h._update_grab_pull_state(1, 0)
        assert h.grab_state == "grab"

    def test_clear_grab_state_resets(self, facing_wall):
        c, h = facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        h._clear_grab_state()
        assert h.grab_state is None
        assert h._grab_direction is None

    def test_carrying_never_grabs(self, facing_wall):
        c, h = facing_wall(direction=0)
        c.player.pickup_object("bush", (1, 2, 3, 4), (30, 19))
        assert c.player.is_carrying() is True

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None

    def test_sitting_never_grabs(self, facing_wall):
        c, h = facing_wall(direction=0)
        c.player.is_sitting = True

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
