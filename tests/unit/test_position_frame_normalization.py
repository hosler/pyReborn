"""Regression tests for the multi_visibility gmap frame-mismatch flake.

BugDetector.check_position_sync is a plain delta comparator with no notion
of coordinate frames - it just compares client.x/.y against expected_x/y.
game_tester/multi_bot.py's run_visibility_test used to feed it a level-LOCAL
(0-63) other-player position (from bot1.players[...]['x'/'y'] - see
pyreborn/client.py's PLO_OTHERPLPROPS handler, which always normalizes
other players' x/y to that frame) against a WORLD expected position
(bot0.x/bot0.y - GameBot.x/.y return client.x/.y, which are WORLD on a gmap
per PLO_PLAYERWARP2's handler). On any gmap world away from segment (0, 0)
that comparison is off by (grid_x*64, grid_y*64) tiles - a spurious "huge
desync" every time, regardless of whether bot1 actually saw bot0 in the
right spot.

BugDetector.to_world_pos() (mirroring pyreborn.Client._update_npc_world_coords
/ game_tester.GameBot._resolve_level_name's `world = local + grid*64`
lookup) fixes this at the point multi_bot.py builds the comparison.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from game_tester.bug_detector import BugDetector


# 3x3 grid matching funtimes' chicken.gmap layout used elsewhere in this
# suite (tests/unit/test_gmap_coordination.py, chicken1.nw at grid (1, 1)).
_GRID = {
    (0, 0): "chicken4.nw", (1, 0): "chicken5.nw", (2, 0): "chicken6.nw",
    (0, 1): "chicken2.nw", (1, 1): "chicken1.nw", (2, 1): "chicken7.nw",
    (0, 2): "chicken3.nw", (1, 2): "chicken9.nw", (2, 2): "chicken8.nw",
}


class TestToWorldPos:
    def test_local_position_gets_segment_offset(self):
        # chicken1.nw is grid (1, 1): local (6, 6) -> world (70, 70).
        x, y = BugDetector.to_world_pos(6.0, 6.0, "chicken1.nw", _GRID)
        assert (x, y) == (70.0, 70.0)

    def test_origin_segment_is_a_no_op(self):
        x, y = BugDetector.to_world_pos(6.0, 6.0, "chicken4.nw", _GRID)
        assert (x, y) == (6.0, 6.0)

    def test_already_world_value_is_not_double_offset(self):
        """Mirrors the _update_npc_world_coords guard: a value >=64 (or
        negative) came off a high-precision prop that was already world and
        must pass through unchanged."""
        x, y = BugDetector.to_world_pos(70.0, 70.0, "chicken1.nw", _GRID)
        assert (x, y) == (70.0, 70.0)

    def test_unknown_level_passes_through_unchanged(self):
        x, y = BugDetector.to_world_pos(6.0, 6.0, "not_in_grid.nw", _GRID)
        assert (x, y) == (6.0, 6.0)

    def test_no_gmap_grid_passes_through_unchanged(self):
        x, y = BugDetector.to_world_pos(6.0, 6.0, "standalone.nw", {})
        assert (x, y) == (6.0, 6.0)


class TestCheckPositionSyncFrameConsistency:
    """The comparator itself is frame-agnostic; these lock in that feeding
    it two ALREADY-normalized (same-frame) positions behaves correctly, and
    that the raw local-vs-world mismatch this bug produced would indeed
    have been flagged (documenting why the multi_bot.py call site had to
    normalize before calling in, not inside the comparator)."""

    def test_matching_world_positions_pass(self):
        bot0_world = (70.0, 70.0)
        other_local = (6.0, 6.0)  # same spot, level-local
        normalized = BugDetector.to_world_pos(*other_local, "chicken1.nw", _GRID)
        result = BugDetector.check_position_sync(
            type('obj', (), {'x': normalized[0], 'y': normalized[1]})(),
            *bot0_world, tolerance=0.5
        )
        assert result.passed

    def test_unnormalized_local_vs_world_would_have_false_positived(self):
        """Documents the bug this fix closes: comparing raw local against
        world directly (the old multi_bot.py behavior) reports a spurious
        desync of a full segment (64 tiles) even though the position is
        identical once normalized."""
        bot0_world = (70.0, 70.0)
        other_local = (6.0, 6.0)  # same spot, but never normalized
        result = BugDetector.check_position_sync(
            type('obj', (), {'x': other_local[0], 'y': other_local[1]})(),
            *bot0_world, tolerance=5.0
        )
        assert not result.passed
        assert result.details["delta"] == (64.0, 64.0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
