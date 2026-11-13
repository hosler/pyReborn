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

import pytest

from offline_game import GMAP_SEGMENTS


@pytest.fixture
def grid_game(make_game):
    """``grid_game(chests=())``: a real offline game on the fixture's 2x2
    gmap, standing in its segment (1, 1) (fixture_d.nw, world origin
    (64, 64)). Chests are ``(x, y, opened)`` on that segment."""
    def build(chests=()):
        game = make_game(gmap=True, gmap_segment=(1, 1), chests=chests,
                         tiles=lambda tx, ty: 0)
        return game.client, game
    return build


CHEST = [(5, 5, False)]


class TestChestFrameFolding:
    def test_find_chest_in_front_matches_a_chest_off_the_origin_segment(
            self, grid_game):
        # Chest footprint local (5, 5)-(6, 6) in fixture_d.nw (grid (1, 1)).
        c, h = grid_game(CHEST)
        # World position chosen so the "facing down" touch points land on
        # local (5, 5): segment origin (64, 64) + local (5.2, 1.6).
        c.player.x, c.player.y = 64 + 5.2, 64 + 1.6
        c.player.direction = 2  # down

        assert h._find_chest_in_front() == (5, 5)

    def test_find_chest_in_front_none_when_not_facing_a_chest(self, grid_game):
        c, h = grid_game(CHEST)
        c.player.x, c.player.y = 64 + 5.2, 64 + 1.6
        c.player.direction = 0  # up: touch points land elsewhere

        assert h._find_chest_in_front() is None

    def test_chest_blocks_off_the_origin_segment(self, grid_game):
        c, h = grid_game(CHEST)

        # A world point inside the chest's local (5, 5)-(6, 6) footprint on
        # segment (1, 1).
        assert h._chest_blocks(64 + 5.3, 64 + 5.3) is True
        # Just outside the footprint, same segment.
        assert h._chest_blocks(64 + 7.3, 64 + 7.3) is False


class TestNoTileDataBlocking:
    def test_hole_in_gmap_grid_blocks(self, grid_game):
        c, h = grid_game()
        # Grid (5, 5) has no entry in gmap_grid at all -- a genuine hole
        # straight off the edge of the known 2x2 grid.
        assert (5, 5) not in c.gmap_grid
        assert h._get_tile_at(5 * 64 + 1.0, 5 * 64 + 1.0) == -1

    def test_known_but_unstreamed_segment_stays_walkable(self, grid_game):
        c, h = grid_game()
        # A known segment (registered in gmap_grid) whose board hasn't
        # streamed in yet -- fixture_c.nw at grid (0, 1). Must NOT block:
        # this is exactly the connect/warp window before PLO_BOARDPACKET
        # arrives, and blocking it would freeze movement dead at spawn.
        unstreamed = GMAP_SEGMENTS[2]
        c.levels.pop(unstreamed, None)
        assert c.gmap_grid[(0, 1)] == unstreamed
        assert unstreamed not in c.levels
        assert h._get_tile_at(1.0, 64 + 1.0) == 0

    def test_standalone_level_with_no_board_yet_stays_walkable(self, make_game):
        """Non-gmap initial-spawn path: no level streamed in at all yet."""
        h = make_game()
        h.client._current_level_name = ""
        assert h._get_tile_at(1.0, 1.0) == 0

    def test_known_segment_in_bounds_tile_still_reads_normally(self, grid_game):
        """Sanity check the fix did not disturb the ordinary in-bounds path
        for a segment whose board HAS streamed in."""
        c, h = grid_game()
        c.tiles[5 * 64 + 5] = 42  # tile at local (5, 5)
        assert h._get_tile_at(64 + 5.3, 64 + 5.3) == 42


class TestChestProbeAllSides:
    """Chest at local (60, 46) (the funtimes 2x2 chest): standing
    flush against each face (player box (x+0.5,y+1)-(x+2.5,y+3)) opens it, one
    tile of gap does not. Facing up used to probe y+1.0 == the box top, which
    floors into the tile below a flush chest and missed it."""

    # direction -> (flush x, flush y) in segment-local tiles
    FLUSH = {0: (60.0, 47.0), 2: (60.0, 43.0), 3: (57.5, 45.5), 1: (61.5, 45.5)}

    def _found(self, grid_game, direction, x, y):
        c, h = grid_game([(60, 46, False)])
        c.player.x, c.player.y = 64 + x, 64 + y
        c.player.direction = direction
        return h._find_chest_in_front()

    @pytest.mark.parametrize("direction", [0, 1, 2, 3])
    def test_flush_against_each_face_opens(self, grid_game, direction):
        x, y = self.FLUSH[direction]
        assert self._found(grid_game, direction, x, y) == (60, 46)

    @pytest.mark.parametrize("direction", [0, 1, 2, 3])
    def test_a_tile_of_gap_does_not_open(self, grid_game, direction):
        x, y = self.FLUSH[direction]
        dx, dy = {0: (0, 1), 2: (0, -1), 3: (-1, 0), 1: (1, 0)}[direction]
        assert self._found(grid_game, direction, x + dx, y + dy) is None
