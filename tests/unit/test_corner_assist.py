"""Unit tests for classic-engine "corner assist" (collision.py's
_corner_assist_offset): a blocked pure-cardinal press that is only blocked by
being slightly off a doorway/corner opening gets nudged perpendicular
instead of stopping dead.

Uses the same minimal ActionsMixin+CollisionMixin harness pattern as
tests/unit/test_collision_gmap_frames.py.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.tiletypes import TileType, is_blocking


# Derived from the loaded type table, the same way
# test_onwall2_flush_slide.py does it. These ids used to be fabricated by a
# per-client tile-type override layer, which no longer exists.
WALL = next(t for t in range(4096) if is_blocking(t))


class _GameHarness(ActionsMixin, CollisionMixin):
    """Minimal GameClient stand-in exercising just the collision slice of
    the mixins (mirrors test_collision_gmap_frames.py's _GameHarness)."""

    def __init__(self, client):
        self.client = client
        self.noclip = False


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    return c


def _wall_row_with_doorway(row: int, doorway_cols=(32, 33, 34)) -> list:
    """A 64x64 level with `row` fully blocked except a 3-wide doorway — wide
    enough for the 2-tile collision box to fit through with room to spare
    (a 1-wide gap can never fit a 2-wide box at any offset)."""
    lvl = [0] * 4096
    for tx in range(64):
        if tx not in doorway_cols:
            lvl[row * 64 + tx] = WALL
    return lvl


def _wall_row_flat(row: int, span=(20, 45)) -> list:
    """A 64x64 level with `row` blocked uniformly across a wide span and no
    doorway anywhere nearby."""
    lvl = [0] * 4096
    for tx in range(*span):
        lvl[row * 64 + tx] = WALL
    return lvl


def _harness_with_level(lvl):
    c = _fake_connected_client()
    c._current_level_name = "test.nw"
    c.levels["test.nw"] = lvl
    c.tiles = lvl
    return c, _GameHarness(c)


# The y where the box's TOP first reaches row 20 on the NEXT step (y - 0.25)
# but not yet at rest — see the module docstring's geometry notes / the
# exploration in the task's PR description. Shared by all "approaching from
# below" cases below.
APPROACH_Y = 20.0


class TestCornerAssistClearableDoorway:
    """A blocked cardinal press near a doorway/corner nudges perpendicular
    toward the opening."""

    # Under the reference two-point probes (TPlayer.cpp:7503-7521; see
    # collision.py _is_position_blocked) an upward move into a wall row is
    # decided by the P2 point at x+2.0 alone (P1's y+2.0 sits below the
    # row), so a doorway at columns 32..34 is clear for x in [30, 33). The
    # blocked-but-assistable approach positions sit one MOVE_STEP outside
    # that window.

    def test_offset_left_of_doorway_nudges_right(self):
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 29.75, APPROACH_Y  # window starts at 30.0

        assert h._is_position_blocked(29.75, APPROACH_Y - 0.25, 0, -1) is True
        assert h._corner_assist_offset(0, -1) == (1, 0)

    def test_offset_right_of_doorway_nudges_left(self):
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 33.0, APPROACH_Y  # window ends at 33.0

        assert h._is_position_blocked(33.0, APPROACH_Y - 0.25, 0, -1) is True
        assert h._corner_assist_offset(0, -1) == (-1, 0)

    def test_centered_in_doorway_needs_no_assist(self):
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 32.0, APPROACH_Y

        # Dead-centered: the plain cardinal move already clears on its own.
        assert h._is_position_blocked(32.0, APPROACH_Y - 0.25, 0, -1) is False

    def test_vertical_doorway_nudges_along_x_only(self):
        """The returned nudge is always exactly one axis, matching the
        pressed axis' perpendicular (never a diagonal delta)."""
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 31.0, APPROACH_Y

        nudge = h._corner_assist_offset(0, -1)
        assert nudge is not None
        ddx, ddy = nudge
        assert ddy == 0 and ddx != 0


class TestCornerAssistDoesNotAssistFlatWall:
    """A long, uniform wall with no doorway anywhere within range must stay
    fully blocked — corner-assist must never let a player slide indefinitely
    along (or squeeze through) a flat wall."""

    def test_far_from_any_opening_returns_none(self):
        lvl = _wall_row_flat(20, span=(20, 45))
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 30.0, APPROACH_Y

        assert h._is_position_blocked(30.0, APPROACH_Y - 0.25, 0, -1) is True
        assert h._corner_assist_offset(0, -1) is None

    def test_doorway_too_far_away_returns_none(self):
        """A doorway exists, but 1.5 tiles away — well past the ~0.5 tile
        corner-assist range — must not be reachable by the nudge."""
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 29.5, APPROACH_Y  # doorway centered at 32.0

        assert h._corner_assist_offset(0, -1) is None


class TestCornerAssistDoesNotAssistSolidCorner:
    """A solid corner/pocket — where the perpendicular nudge itself is
    blocked, not just the far-away destination — must also stay blocked."""

    def test_boxed_in_corner_returns_none(self):
        lvl = _wall_row_flat(20, span=(20, 45))
        # Wall segment immediately beside the approach row too, boxing the
        # player into a dead-end pocket: any sideways nudge hits a wall.
        for tx in (30, 31, 32, 33, 34, 35):
            lvl[19 * 64 + tx] = 1
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 32.0, APPROACH_Y

        assert h._is_position_blocked(32.0, APPROACH_Y - 0.25, 0, -1) is True
        assert h._corner_assist_offset(0, -1) is None


class TestCornerAssistIgnoresDiagonalAndNoInput:
    def test_diagonal_press_returns_none(self):
        """Diagonal presses already have their own axis-slide in _move and
        do not use corner-assist."""
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 31.0, APPROACH_Y

        assert h._corner_assist_offset(1, -1) is None

    def test_no_input_returns_none(self):
        lvl = _wall_row_with_doorway(20)
        c, h = _harness_with_level(lvl)
        c.player.x, c.player.y = 31.0, APPROACH_Y

        assert h._corner_assist_offset(0, 0) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
