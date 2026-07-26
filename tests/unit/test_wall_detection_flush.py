"""Classic (non-scripted) wall detection: resting flush, and agreeing with the
scripted swept-rect model.

The scripted oracle is `CheckWallDir(k, speed, customs)` in
Preagonal/graal-lttp/weapons/weapon-Player_Movement.txt:613 — the live LTTP
world's own movement weapon. It fires two `onwall2(player.x+dx, player.y+dy,
w, h)` rect probes per direction over the thin sliver the collision box is
about to sweep into:

    k: 0=up 1=left 2=down 3=right
    {{.5, 1-speed}, {1.5, 1-speed}, {1, speed}},   // UP
    {{0, 1},        {0, 2},         {speed, 1}},   // LEFT
    {{.5, 3},       {1.5, 3},       {1, speed}},   // DOWN
    {{2.5, 1},      {2.5, 2},       {speed, 1}},   // RIGHT

`speed` is in TILES, not pixels: its callers add it straight to `player.x`
(:249), the finest call passes `1/16` (:388) and HitWall steps `i += 1/16`
across it (:663). The walk value is `wspeed` (:235-236), .5/3 tiles/frame.

Directions 0/2/3 anchor their rect on the collision box's own leading edge
(y+1, y+3, x+2.5) and extend it by `speed` on the side the box is moving
toward — UP is the only one that has to subtract (`1-speed`), because its
rect grows upward from the edge rather than away from it. LEFT is the odd
one out: the box's left edge is x+0.5 (HitWall's left probe, :652-656, uses
x+.5), so the swept sliver is x+0.5-speed .. x+0.5, yet the table anchors at
x+0 — correct only at `player.speed = 0.5` (:52), the value it was written
for. LTTP gets away with it because a blocked CheckWallDir hands off to
HitWall, which advances the leading edge in 1/16 steps and then SNAPS
(`player.x = int(player.x)+.5`), so the coarse over-eager probe is corrected
before the player comes to rest.

These tests pin two things:

1. the classic box check already comes to rest flush (gap 0) against a wall
   in all four directions, and
2. it agrees, position for position, with the geometrically-correct swept
   sliver — while transcribing the table's LEFT anchor literally at our
   MOVE_STEP would stop the player a quarter tile short.

Harness pattern is tests/unit/test_corner_assist.py's.
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
from pyreborn.game.constants import (
    MOVE_STEP,
    PLAYER_COLLISION_BOTTOM, PLAYER_COLLISION_LEFT,
    PLAYER_COLLISION_RIGHT, PLAYER_COLLISION_TOP,
)
from pyreborn.tiletypes import TileType

from .test_onwall2_flush_slide import BLOCK, _onwall2


class _GameHarness(ActionsMixin, CollisionMixin):
    def __init__(self, client):
        self.client = client
        self.tile_corrections = {BLOCK: TileType.BLOCKING}
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


# 0=up 1=left 2=down 3=right, the oracle's k ordering.
_DELTA = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}


def _walk(start, k, blocked):
    """Step from `start` in direction `k` until `blocked(x, y, k)`, in the
    MOVE_STEP increments actions.py's _move uses. Returns the resting (x, y)."""
    x, y = start
    dx, dy = _DELTA[k]
    for _ in range(400):
        if blocked(x, y, k):
            break
        x += dx * MOVE_STEP
        y += dy * MOVE_STEP
    return round(x, 6), round(y, 6)


def _box_blocked(harness):
    """actions.py's _move gate: the destination collision box overlaps a wall."""
    def probe(x, y, k):
        dx, dy = _DELTA[k]
        return harness._is_position_blocked(x + dx * MOVE_STEP,
                                            y + dy * MOVE_STEP, dx, dy)
    return probe


def _swept_blocked(walls, left_anchor):
    """CheckWallDir with `speed` = MOVE_STEP, over the real onwall2 the
    scripted path calls. `left_anchor` is the LEFT rect's x offset."""
    onwall2 = _onwall2(walls)
    speed = MOVE_STEP
    table = {
        0: ((0.5, 1 - speed), (1.5, 1 - speed), (1.0, speed)),
        1: ((left_anchor, 1.0), (left_anchor, 2.0), (speed, 1.0)),
        2: ((0.5, 3.0), (1.5, 3.0), (1.0, speed)),
        3: ((2.5, 1.0), (2.5, 2.0), (speed, 1.0)),
    }

    def probe(x, y, k):
        a, b, size = table[k]
        return (onwall2(x + a[0], y + a[1], size[0], size[1]) or
                onwall2(x + b[0], y + b[1], size[0], size[1]))
    return probe


# Script-literal LEFT anchor vs the swept sliver the other three directions use.
_LEFT_ANCHOR_LITERAL = 0.0
_LEFT_ANCHOR_SWEPT = PLAYER_COLLISION_LEFT - MOVE_STEP

_WALL_ROW_UP, _WALL_ROW_DOWN = 20, 40
_WALL_COL_LEFT, _WALL_COL_RIGHT = 20, 40
_ROW_UP = [(tx, _WALL_ROW_UP) for tx in range(64)]
_ROW_DOWN = [(tx, _WALL_ROW_DOWN) for tx in range(64)]
_COL_LEFT = [(_WALL_COL_LEFT, ty) for ty in range(64)]
_COL_RIGHT = [(_WALL_COL_RIGHT, ty) for ty in range(64)]


class TestClassicRestsFlush:
    """Walking into a flat wall leaves the collision box's leading edge exactly
    on the wall's boundary. Every expected gap below is 0."""

    def test_up_is_flush(self):
        c, h = _harness(_ROW_UP)
        _, y = _walk((32.0, 30.0), 0, _box_blocked(h))
        # Box top lands on the wall row's BOTTOM boundary.
        assert (y + PLAYER_COLLISION_TOP) - (_WALL_ROW_UP + 1) == 0

    def test_left_is_flush(self):
        c, h = _harness(_COL_LEFT)
        x, _ = _walk((30.0, 30.0), 1, _box_blocked(h))
        # Box left lands on the wall column's RIGHT boundary.
        assert (x + PLAYER_COLLISION_LEFT) - (_WALL_COL_LEFT + 1) == 0

    def test_down_is_flush(self):
        c, h = _harness(_ROW_DOWN)
        _, y = _walk((32.0, 20.0), 2, _box_blocked(h))
        # Box bottom lands on the wall row's TOP boundary.
        assert _WALL_ROW_DOWN - (y + PLAYER_COLLISION_BOTTOM) == 0

    def test_right_is_flush(self):
        c, h = _harness(_COL_RIGHT)
        x, _ = _walk((20.0, 30.0), 3, _box_blocked(h))
        # Box right lands on the wall column's LEFT boundary.
        assert _WALL_COL_RIGHT - (x + PLAYER_COLLISION_RIGHT) == 0


class TestClassicMatchesScriptedSweptProbe:
    """The classic destination-box check and the scripted swept-sliver check
    are the same predicate for an approach that starts clear of walls: the
    sliver IS the region the box newly covers, and the region it already
    covered was wall-free."""

    @pytest.mark.parametrize("k,walls,start", [
        (0, _ROW_UP, (32.0, 30.0)),
        (1, _COL_LEFT, (30.0, 30.0)),
        (2, _ROW_DOWN, (32.0, 20.0)),
        (3, _COL_RIGHT, (20.0, 30.0)),
    ])
    def test_same_resting_position_on_a_flat_wall(self, k, walls, start):
        c, h = _harness(walls)
        assert (_walk(start, k, _box_blocked(h)) ==
                _walk(start, k, _swept_blocked(walls, _LEFT_ANCHOR_SWEPT)))

    def test_same_resting_position_across_a_scattered_board(self):
        """Not just flat walls: every open start cell of a board of scattered
        blocks, in all four directions. The board is walled in — off-board is
        blocking to the box check but not to onwall2, and that domain
        difference (the standalone-level bounds check, deliberately left on
        the body box) is not what this comparison is about."""
        walls = [(tx, ty) for ty in range(64) for tx in range(64)
                 if (tx * 7 + ty * 13) % 23 == 0
                 or tx in (0, 63) or ty in (0, 63)]
        c, h = _harness(walls)
        box = _box_blocked(h)
        swept = _swept_blocked(walls, _LEFT_ANCHOR_SWEPT)
        for sy in range(4, 60, 5):
            for sx in range(4, 60, 5):
                if h._is_position_blocked(float(sx), float(sy)):
                    continue
                for k in range(4):
                    start = (float(sx), float(sy))
                    assert _walk(start, k, box) == _walk(start, k, swept), \
                        f"start={start} k={k}"

    def test_literal_left_anchor_would_stop_a_quarter_tile_short(self):
        """The oracle's `{0, 1}` LEFT anchor is hardcoded for speed 0.5. At
        MOVE_STEP it probes 0.25 tiles beyond the swept sliver, so a literal
        transcription rests one step short of flush — the same class of defect
        as the bug this file guards, and the reason LTTP needs HitWall's snap."""
        c, h = _harness(_COL_LEFT)
        start = (30.0, 30.0)
        flush, _ = _walk(start, 1, _box_blocked(h))
        literal, _ = _walk(start, 1, _swept_blocked(_COL_LEFT,
                                                    _LEFT_ANCHOR_LITERAL))
        assert literal - flush == MOVE_STEP


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
