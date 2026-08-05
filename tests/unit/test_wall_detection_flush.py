"""Classic (non-scripted) wall detection: the reference's TWO-POINT probes.

Oracle: TPlayer::movementAction, Preagonal/FourPlay/quattroplay/src/
TPlayer.cpp:7503-7521 --

    checkX1 = nx + 1.5;  checkY1 = ny + 2.0                    (always)
    checkX2 = nx + (dir == 1 ? 1.0 : 2.0)
    checkY2 = ny + (dir == 0 ? 1.0 : 0.5)

with the constants at TInitStatics.cpp:1243-1278 and isOnWall a pure POINT
test (TServerLevel.cpp:2642-2653). There is no box scan: the head row may
overlap a wall above and the feet row a wall below, which is the classic
walk-behind/walk-under feel.

History: this file used to pin a full 2x2-tile collision-box scan against
LTTP's scripted CheckWallDir swept-rect table. That table is that server's
OWN weapon script (it runs through onwall2 and still does); it was never the
reference client's default-movement collision, and transcribing it as such
was the "collision box is the whole sprite" bug (S3, 2026-08-05): the box
blocked on the torso and head rows, so the player stopped a full tile short
of walls the real client tucks under.
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
from pyreborn.game.constants import MOVE_STEP

from .test_onwall2_flush_slide import BLOCK


class _GameHarness(ActionsMixin, CollisionMixin):
    def __init__(self, client):
        self.client = client
        self.noclip = False


def _harness(walls):
    """Harness over a 64x64 board blocked at the given (tx, ty) cells."""
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    lvl = [0] * 4096
    for tx, ty in walls:
        lvl[ty * 64 + tx] = BLOCK
    c._current_level_name = "test.nw"
    c.levels["test.nw"] = lvl
    c.tiles = lvl
    return c, _GameHarness(c)


# 0=up 1=left 2=down 3=right, the reference's direction ordering.
_DELTA = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}


def _walk(harness, start, k):
    """Step from `start` in direction `k` until the destination probe pair
    blocks, in the MOVE_STEP increments actions.py's _move uses. Returns the
    resting (x, y)."""
    x, y = start
    dx, dy = _DELTA[k]
    for _ in range(400):
        if harness._is_position_blocked(x + dx * MOVE_STEP,
                                        y + dy * MOVE_STEP, dx, dy):
            break
        x += dx * MOVE_STEP
        y += dy * MOVE_STEP
    return round(x, 6), round(y, 6)


_WALL_ROW_UP, _WALL_ROW_DOWN = 20, 40
_WALL_COL_LEFT, _WALL_COL_RIGHT = 20, 40
_ROW_UP = [(tx, _WALL_ROW_UP) for tx in range(64)]
_ROW_DOWN = [(tx, _WALL_ROW_DOWN) for tx in range(64)]
_COL_LEFT = [(_WALL_COL_LEFT, ty) for ty in range(64)]
_COL_RIGHT = [(_WALL_COL_RIGHT, ty) for ty in range(64)]


class TestProbePoints:
    """The probe pair is a literal transcription of TPlayer.cpp:7512-7515."""

    @pytest.mark.parametrize("k,expected_p2", [
        (0, (2.0, 1.0)),   # up:    dir==0 takes the 1.0 y offset
        (1, (1.0, 0.5)),   # left:  dir==1 takes the 1.0 x offset
        (2, (2.0, 0.5)),   # down:  else-branch on both axes
        (3, (2.0, 0.5)),   # right: else-branch on both axes
    ])
    def test_pair_per_direction(self, k, expected_p2):
        c, h = _harness([])
        dx, dy = _DELTA[k]
        points = h._probe_points(10.0, 20.0, dx, dy)
        assert points[0] == (11.5, 22.0)          # P1 = (+1.5, +2.0), always
        assert points[1:] == [(10.0 + expected_p2[0], 20.0 + expected_p2[1])]

    def test_diagonal_checks_both_cardinals(self):
        c, h = _harness([])
        points = h._probe_points(10.0, 20.0, 1, -1)   # up-right
        assert points[0] == (11.5, 22.0)
        assert set(points[1:]) == {(12.0, 21.0), (12.0, 20.5)}


class TestRestingPositions:
    """Where the walk comes to rest against a flat wall. The rest point puts
    the LEADING PROBE within one MOVE_STEP of the wall boundary; the sprite
    body may overlap the wall row/column, exactly as the reference's
    upper-body probes allow."""

    def test_up_head_row_overlaps_the_wall(self):
        c, h = _harness(_ROW_UP)
        _, y = _walk(h, (32.0, 30.0), 0)
        # Up probes ny+1.0 (P2) and ny+2.0 (P1): blocked once ny+1.0 enters
        # row 20, so the sprite's top row sits ON the wall row.
        assert y == _WALL_ROW_UP + 1 - 1.0

    def test_left_edge_column_overlaps_the_wall(self):
        c, h = _harness(_COL_LEFT)
        x, _ = _walk(h, (30.0, 30.0), 1)
        # Left probes nx+1.0 (P2) and nx+1.5 (P1).
        assert x == _WALL_COL_LEFT + 1 - 1.0

    def test_down_stops_when_body_centre_reaches_the_wall(self):
        c, h = _harness(_ROW_DOWN)
        _, y = _walk(h, (32.0, 20.0), 2)
        # Down probes ny+0.5 and ny+2.0: the y+2.0 body point is the leading
        # probe. It rests one MOVE_STEP short of the row boundary (a point ON
        # the boundary floors into the wall tile).
        assert y + 2.0 == _WALL_ROW_DOWN - MOVE_STEP

    def test_right_stops_when_leading_probe_reaches_the_wall(self):
        c, h = _harness(_COL_RIGHT)
        x, _ = _walk(h, (20.0, 30.0), 3)
        assert x + 2.0 == _WALL_COL_RIGHT - MOVE_STEP


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
