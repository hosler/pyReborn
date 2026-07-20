"""Unit tests for the push/grab/pull hold-state feel mechanics
(game/actions.py's _update_push_hold / _update_grab_pull_state and their
_clear_* counterparts):

- Push: holding a movement key into a wall for PUSH_HOLD_TIME switches to
  the "push" gani.
- Grab: holding A (grab) while facing a plain blocking wall tile (nothing
  liftable/interactable) shows "grab".
- Pull: while grabbing, also holding the movement key OPPOSITE the grabbed
  facing switches to "pull" without re-facing that direction.

None of this actually moves a tile — there's no server support for
pushable/pullable blocks; it's purely animation/feel state, verified here at
the state-machine level (no live server/pygame display needed).

Uses the same minimal ActionsMixin+CollisionMixin harness pattern as
tests/unit/test_swimming_state.py, extended with the handful of extra
attributes _move()/_try_link_warp() touch.
"""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.constants import PUSH_HOLD_TIME
from pyreborn.tiletypes import TileType


class _NoopSound:
    def play(self, *a, **k):
        pass


class _SpyAnim:
    """Records set_animation/set_direction calls instead of touching pygame,
    and tracks the gani name like the real AnimationState does (renderer/
    other code reads player_anim.gani.name in a few places, but nothing here
    needs it)."""

    def __init__(self):
        self.direction = 2
        self.calls = []

    def set_animation(self, name, direction=None, force=False):
        self.calls.append(("set_animation", name, direction, force))
        if direction is not None:
            self.direction = direction

    def set_direction(self, direction):
        self.calls.append(("set_direction", direction))
        self.direction = direction


class _NoopNpcHandler:
    def process_movement(self, *a, **k):
        pass

    def update_npcs(self):
        pass


class _SentAnims:
    """Stand-in for client.set_animation, recording gani names broadcast to
    the server (build_animation's PLI_PLAYERPROPS path) without needing a
    live connection."""

    def __init__(self):
        self.sent = []


class _Harness(ActionsMixin, CollisionMixin):
    """Minimal GameClient stand-in exercising the push/grab/pull slice of
    the mixins, without pygame display/asset/sound setup."""

    def __init__(self, client):
        self.client = client
        self.tile_corrections = {1: TileType.BLOCKING}
        self.noclip = False
        self.is_swimming = False
        self.current_anim_name = "idle"
        self.is_moving = False
        self.sound_mgr = _NoopSound()
        self.player_anim = _SpyAnim()
        self.npc_handler = _NoopNpcHandler()
        self._found_chest_level = None
        self._was_on_link = False
        self._link_arrival = None

        # Push/grab/pull state (normally initialized in pygame_game.py).
        self._push_hold_dir = None
        self._push_hold_start = 0.0
        self.is_pushing = False
        self.grab_state = None
        self._grab_direction = None

        self._sent = _SentAnims()
        real_set_animation = self.client.set_animation

        def _spy_set_animation(name):
            self._sent.sent.append(name)
            return real_set_animation(name)

        self.client.set_animation = _spy_set_animation


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    return c


def _flat_wall_level(row: int = 20, span=(20, 45)) -> list:
    lvl = [0] * 4096
    for tx in range(*span):
        lvl[row * 64 + tx] = 1
    return lvl


def _harness_facing_wall(direction: int = 0):
    """A harness positioned with its box already touching a wall to the
    given facing direction, and nothing liftable/chest/door/sign there."""
    c = _fake_connected_client()
    lvl = _flat_wall_level()
    c._current_level_name = "test.nw"
    c.levels["test.nw"] = lvl
    c.tiles = lvl
    h = _Harness(c)
    c.player.x, c.player.y = 30.0, 19.5  # box top touches row 20 one step up
    c.player.direction = direction
    return c, h


class TestPushHoldState:
    def test_short_block_does_not_push(self):
        c, h = _harness_facing_wall()
        h._update_push_hold(0, -1)
        assert h.is_pushing is False
        assert h.current_anim_name != "push"

    def test_held_past_threshold_switches_to_push(self):
        c, h = _harness_facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = time.time() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)

        assert h.is_pushing is True
        assert h.current_anim_name == "push"
        assert "push" in h._sent.sent

    def test_changing_direction_resets_the_hold_timer(self):
        c, h = _harness_facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = time.time() - (PUSH_HOLD_TIME + 0.1)
        # Switch to a different held direction: the timer must restart, not
        # carry over the elapsed time from the old direction.
        h._update_push_hold(1, 0)

        assert h.is_pushing is False
        assert h._push_hold_dir == (1, 0)

    def test_clear_push_hold_resets_state(self):
        c, h = _harness_facing_wall()
        h._push_hold_dir = (0, -1)
        h._push_hold_start = time.time() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)
        assert h.is_pushing is True

        h._clear_push_hold()
        assert h.is_pushing is False
        assert h._push_hold_dir is None

    def test_carrying_never_pushes(self):
        c, h = _harness_facing_wall()
        c.player.pickup_object("bush", (1, 2, 3, 4), (30, 19))
        assert c.player.is_carrying() is True

        h._push_hold_dir = (0, -1)
        h._push_hold_start = time.time() - (PUSH_HOLD_TIME + 0.1)
        h._update_push_hold(0, -1)

        assert h.is_pushing is False
        assert h.current_anim_name != "push"


class TestGrabPullState:
    def test_a_alone_facing_wall_enters_grab(self):
        c, h = _harness_facing_wall(direction=0)  # facing up, into the wall
        h._update_grab_pull_state(0, 0)

        assert h.grab_state == "grab"
        assert h._grab_direction == 0
        assert h.current_anim_name == "grab"
        assert "grab" in h._sent.sent

    def test_a_alone_facing_open_ground_does_not_grab(self):
        c = _fake_connected_client()
        c._current_level_name = "test.nw"
        c.levels["test.nw"] = [0] * 4096
        c.tiles = c.levels["test.nw"]
        h = _Harness(c)
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 0

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None

    def test_holding_opposite_direction_switches_to_pull(self):
        c, h = _harness_facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        # Facing up (0); opposite is down (dy=+1).
        h._update_grab_pull_state(0, 1)
        assert h.grab_state == "pull"
        # Facing stays pinned on the grabbed wall, not spun to face down.
        assert h._grab_direction == 0
        assert "pull" in h._sent.sent

    def test_releasing_opposite_direction_returns_to_grab(self):
        c, h = _harness_facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        h._update_grab_pull_state(0, 1)
        assert h.grab_state == "pull"

        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

    def test_a_non_opposite_direction_does_not_pull(self):
        c, h = _harness_facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        # Sideways, not the opposite of "up" — should stay "grab", not "pull".
        h._update_grab_pull_state(1, 0)
        assert h.grab_state == "grab"

    def test_clear_grab_state_resets(self):
        c, h = _harness_facing_wall(direction=0)
        h._update_grab_pull_state(0, 0)
        assert h.grab_state == "grab"

        h._clear_grab_state()
        assert h.grab_state is None
        assert h._grab_direction is None

    def test_carrying_never_grabs(self):
        c, h = _harness_facing_wall(direction=0)
        c.player.pickup_object("bush", (1, 2, 3, 4), (30, 19))
        assert c.player.is_carrying() is True

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None

    def test_sitting_never_grabs(self):
        c, h = _harness_facing_wall(direction=0)
        c.player.is_sitting = True

        h._update_grab_pull_state(0, 0)
        assert h.grab_state is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
