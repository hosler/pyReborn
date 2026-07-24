"""onwall2 rect far-edge semantics: flush-wall sliding must not be blocked.

Bomber v6's -Test/Movement weapon (default_movement off) gates every step on
two onwall2 rect probes per direction (CheckWall in the captured bytecode,
cap_38_weapon__Test_Movement.disasm):

    move axis   extent = player.speed/16 - 1/16 = -0.04375  (speed = 0.3)
    perp axis   extent = 1 - 1/16 = 0.9375

The reference client (FourPlay TServerLevel::isRectOnWall) returns false for
w<=0/h<=0 rects, so our origin-cell fallback for degenerate extents is what
makes the script block at all. Because the script checks-then-moves, the
resting position penetrates bottom/right walls by up to one step (0.3). The
perpendicular slide probes then graze the wall row/column by
(penetration - 1/16) and an exact coverage walk counted that grazed cell:
standing flush against a wall BELOW blocked purely horizontal movement, and
flush against a wall to the RIGHT blocked purely vertical movement.

Fix under test: far-edge cell enumeration forgives sliver overlaps up to
_ONWALL2_EDGE_TOL (0.25 tiles); origin cells and overlaps beyond a quarter
tile are unchanged.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.gs1_client import ClientGS1
from pyreborn.tiletypes import is_blocking

BLOCK = next(t for t in range(4096) if is_blocking(t))
assert not is_blocking(0)


class _FakePlayer:
    def __init__(self, x=30.0, y=40.0):
        self.id = 1
        self.account = "t"
        self.nickname = "t"
        self.x = x
        self.y = y
        self.direction = 0
        self.gani = "idle"
        self.level = "test.nw"
        self.chat = ""


class _FakeClient:
    def __init__(self, walls):
        self.npcs = {}
        self.players = {}
        self.weapons = {}
        self.global_flags = {}
        self._current_level_name = "test.nw"
        self.player = _FakePlayer()
        self.tiles = [0] * 4096
        for tx, ty in walls:
            self.tiles[ty * 64 + tx] = BLOCK

    def send_packet(self, *a, **k):
        pass

    def triggeraction(self, *a, **k):
        pass


def _onwall2(walls):
    gs1 = ClientGS1(_FakeClient(walls))
    return lambda *args: bool(gs1._host.call_function("onwall2", list(args), None))


BOTTOM_WALL = [(tx, 45) for tx in range(0, 64)]   # wall row y=45
RIGHT_WALL = [(40, ty) for ty in range(0, 64)]    # wall column x=40


# --- the live bug: flush/penetrated against a bottom wall, sliding sideways


def test_bottom_wall_slide_probe_forgives_penetration_sliver():
    # Exact probe from the live repro: player rested at y=42.1 (leading edge
    # 45.1, 0.1 inside wall row 45); horizontal CheckWall probe covers rows
    # [44.1, 45.0375] - the 0.0375 graze into row 45 must NOT count.
    probe = _onwall2(BOTTOM_WALL)
    assert probe(30.2, 44.1, -0.04375, 0.9375) is False


def test_bottom_wall_slide_probe_flush_exact_stays_clear():
    # Integer-aligned flush (no penetration): far edge exactly on the wall
    # row boundary is exclusive.
    probe = _onwall2(BOTTOM_WALL)
    assert probe(30.2, 44.0, -0.04375, 0.9375) is False


def test_bottom_wall_down_probe_still_blocks():
    # The into-wall probe (degenerate h, origin cell = leading edge row)
    # must keep blocking, including from a penetrated resting position.
    probe = _onwall2(BOTTOM_WALL)
    assert probe(30.5, 45.1, 0.9375, -0.04375) is True     # penetrated
    assert probe(30.5, 45.0, 0.9375, -0.04375) is True     # exactly flush


def test_right_wall_slide_probe_forgives_penetration_sliver():
    # Mirror case: player rested at x=37.6 (leading edge 40.1, 0.1 inside
    # wall column 40); vertical probe covers cols [39.1, 40.0375].
    probe = _onwall2(RIGHT_WALL)
    assert probe(39.1, 30.7, 0.9375, -0.04375) is False


def test_right_wall_right_probe_still_blocks():
    probe = _onwall2(RIGHT_WALL)
    assert probe(40.1, 30.5, -0.04375, 0.9375) is True     # penetrated
    assert probe(40.0, 30.5, -0.04375, 0.9375) is True     # exactly flush


# --- semantics preserved outside the forgiveness sliver


def test_integer_rects_unchanged():
    probe = _onwall2(BOTTOM_WALL)
    assert probe(30.0, 43.0, 1.0, 3.0) is True    # rows 43-45: hits wall
    assert probe(30.0, 42.0, 1.0, 3.0) is False   # rows 42-44: exclusive far edge


def test_substantial_overlap_still_blocks():
    # Overlap into the wall row beyond the quarter-tile tolerance must hit:
    # rows [44.5, 45.4375] overlaps row 45 by 0.4375.
    probe = _onwall2(BOTTOM_WALL)
    assert probe(30.0, 44.5, 0.9375, 0.9375) is True


@pytest.mark.parametrize("overlap,expect", [
    (0.20, False),   # within tolerance: forgiven
    (0.30, True),    # beyond tolerance: counted
])
def test_far_edge_tolerance_boundary(overlap, expect):
    probe = _onwall2(BOTTOM_WALL)
    y = 44.0 + overlap  # rect [y, y+1) pokes `overlap` into wall row 45
    assert probe(30.0, y, 0.9375, 1.0) is expect


def test_two_arg_form_unchanged():
    probe = _onwall2(RIGHT_WALL)
    assert probe(40.5, 30.0) is True
    assert probe(39.9, 30.0) is False
