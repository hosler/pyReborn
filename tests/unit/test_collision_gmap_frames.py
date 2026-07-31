"""Regression tests for two 2026-07-19 gmap coordinate-frame bugs in the
CollisionMixin/ActionsMixin (pyreborn/game/collision.py, .../actions.py):

1. Chest frame mismatch: client.chests is keyed level-LOCAL (0-63. See
   client.py's PLO_LEVELCHEST handler), but _find_chest_in_front and
   _chest_blocks used to compare WORLD-frame touch points against those keys
   directly. On a gmap, a chest anywhere off the origin segment (grid (0,0))
   was therefore both unopenable (_find_chest_in_front never matched) and
   non-solid (_chest_blocks never matched, so you could walk straight
   through it).

2. Missing tile data ("no tiles resolve here") used to always read as
   walkable (0), even for a gmap cell with no known segment at all (a hole
   in the grid / straight off its edge) - the same situation the in-board
   OOB path one branch down correctly treats as blocking (-1). Fixed to
   block for genuine holes while staying walkable for a known-but-not-yet-
   streamed segment (avoids freezing movement at initial spawn, before the
   first PLO_BOARDPACKET arrives).
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


class _GameHarness(ActionsMixin, CollisionMixin):
    """Minimal GameClient stand-in exercising just the collision/touch-point
    slice of the mixins (mirrors tests/unit/test_render_cache_invalidation.
    py's _RenderHarness pattern)."""

    def __init__(self, client):
        self.client = client
        self.tile_corrections = {}


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    return c


def _client_with_grid():
    # Same 3x3 chicken.gmap layout used by test_gmap_coordination.py /
    # test_position_frame_normalization.py: chicken1.nw sits at grid (1, 1),
    # i.e. world origin (64, 64).
    c = _fake_connected_client()
    names = [
        "chicken4.nw", "chicken5.nw", "chicken6.nw",
        "chicken2.nw", "chicken1.nw", "chicken7.nw",
        "chicken3.nw", "chicken9.nw", "chicken8.nw",
    ]
    c.gmap_width, c.gmap_height = 3, 3
    for i, name in enumerate(names):
        c.gmap_grid[(i % 3, i // 3)] = name
    c._current_level_name = "chicken1.nw"
    c.levels["chicken1.nw"] = [0] * 4096
    c.tiles = c.levels["chicken1.nw"]
    return c


class TestChestFrameFolding:
    def test_find_chest_in_front_matches_a_chest_off_the_origin_segment(self):
        c = _client_with_grid()
        # Chest footprint local (5, 5)-(6, 6) in chicken1.nw (grid (1, 1)).
        c.chests = {(5, 5): False}

        h = _GameHarness(c)
        # World position chosen so the "facing down" touch points land on
        # local (5, 5): segment origin (64, 64) + local (5.2, 1.6).
        c.player.x, c.player.y = 64 + 5.2, 64 + 1.6
        c.player.direction = 2  # down

        assert h._find_chest_in_front() == (5, 5)

    def test_find_chest_in_front_none_when_not_facing_a_chest(self):
        c = _client_with_grid()
        c.chests = {(5, 5): False}
        h = _GameHarness(c)
        c.player.x, c.player.y = 64 + 5.2, 64 + 1.6
        c.player.direction = 0  # up: touch points land elsewhere

        assert h._find_chest_in_front() is None

    def test_chest_blocks_off_the_origin_segment(self):
        c = _client_with_grid()
        c.chests = {(5, 5): False}
        h = _GameHarness(c)

        # A world point inside the chest's local (5, 5)-(6, 6) footprint on
        # segment (1, 1).
        assert h._chest_blocks(64 + 5.3, 64 + 5.3) is True
        # Just outside the footprint, same segment.
        assert h._chest_blocks(64 + 7.3, 64 + 7.3) is False


class TestNoTileDataBlocking:
    def test_hole_in_gmap_grid_blocks(self):
        c = _client_with_grid()
        h = _GameHarness(c)
        # Grid (5, 5) has no entry in gmap_grid at all -- a genuine hole
        # straight off the edge of the known 3x3 grid.
        assert h._get_tile_at(5 * 64 + 1.0, 5 * 64 + 1.0) == -1

    def test_known_but_unstreamed_segment_stays_walkable(self):
        c = _client_with_grid()
        # A known segment (registered in gmap_grid) whose board hasn't
        # streamed in yet -- e.g. chicken2.nw at grid (0, 1), no entry in
        # c.levels. Must NOT block: this is exactly the connect/warp window
        # before PLO_BOARDPACKET arrives, and blocking it would freeze
        # movement dead at spawn.
        h = _GameHarness(c)
        assert (0, 1) in c.gmap_grid
        assert "chicken2.nw" not in c.levels
        assert h._get_tile_at(1.0, 64 + 1.0) == 0

    def test_standalone_level_with_no_board_yet_stays_walkable(self):
        """Non-gmap initial-spawn path: no level streamed in at all yet."""
        c = _fake_connected_client()
        c._current_level_name = ""
        h = _GameHarness(c)
        assert h._get_tile_at(1.0, 1.0) == 0

    def test_known_segment_in_bounds_tile_still_reads_normally(self):
        """Sanity check the fix did not disturb the ordinary in-bounds path
        for a segment whose board HAS streamed in."""
        c = _client_with_grid()
        c.tiles[5 * 64 + 5] = 42  # tile at local (5, 5)
        h = _GameHarness(c)
        assert h._get_tile_at(64 + 5.3, 64 + 5.3) == 42


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
