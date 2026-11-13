"""Regression tests for the sticky-swimming bug: GameClient.is_swimming (the
state backing the GS1 `playerswimming` flag and the pygame HUD swim badge)
must recompute on warp/level-change, not just after a manual move().

Live evidence: a bot stranded in water on chicken5.nw still reported
swimming:true after warping into a dry indoor level (chicken_house1.nw).
Root cause: _update_swimming_state() (pyreborn/game/actions.py) was only
called from _move() and from the run() loop's per-frame catch-all - warp
entry points (_use_door_link, _process_pending_warp) never called it
directly, so any caller that does not drive the full run() loop (or checks
state immediately after a warp within the same frame, before the catch-all
runs) sees the previous level's stale value. Fixed by recomputing swimming
state immediately at both warp sites.
"""

import pytest

from offline_game import spy
from pyreborn.tiletypes import TileType, get_tile_type

# Derived from the loaded type table. These used to be tile ids 1 and 2,
# forced to these types by a per-client override layer that no longer exists.
DEEP = next(t for t in range(4096) if get_tile_type(t) == TileType.WATER)
SHALLOW = next(t for t in range(4096)
               if get_tile_type(t) == TileType.NEAR_WATER)

START = "fixture.nw"
OTHER = "dry.nw"


@pytest.fixture
def swim_game(make_game, monkeypatch):
    """``swim_game(start_tile, other_tile=0)``: a real offline game whose start
    level is one tile type end to end (a fn(tx, ty) also works) and which has
    a second level ``dry.nw`` of ``other_tile`` to warp to, already visited. ``_spawn_leaps``
    is spied (the real one still runs): ``game.leaps``."""
    def build(start_tile, other_tile=0):
        def board(tile):
            return tile if callable(tile) else (lambda tx, ty: tile)
        game = make_game(player_xy=(30.0, 30.0), tiles=board(start_tile),
                         extra_levels={OTHER: board(other_tile)})
        # Visit the other level and come back, so the client holds both
        # boards (a door into a cached level is the case these tests pin).
        async def round_trip(world):
            await world.me.warp(OTHER, 30.0, 30.0)
            await world.me.warp(START, 30.0, 30.0)
        game.server.run(round_trip)
        assert {START, OTHER} <= set(game.client.levels)
        game.leaps = spy(monkeypatch, game, "_spawn_leaps")
        return game
    return build


class TestSwimmingStateRecompute:
    def test_shallow_water_does_not_trigger_swimming(self, swim_game):
        h = swim_game(SHALLOW)

        h._update_swimming_state()

        assert h.is_swimming is False

    def test_baseline_recompute_detects_water(self, swim_game):
        h = swim_game(DEEP)
        h._update_swimming_state()
        assert h.is_swimming is True

    def test_standing_point_transitions_at_deep_shallow_boundary(self,
                                                                  swim_game):
        h = swim_game(lambda tx, ty: DEEP if tx >= 32 else SHALLOW)
        c = h.client

        # The standing point is player x + 1.5, so these positions straddle
        # the boundary between shallow column 31 and deep column 32.
        c.player.x = 30.49
        h._update_swimming_state()
        assert h.is_swimming is False

        c.player.x = 30.5
        h._update_swimming_state()
        assert h.is_swimming is True

        c.player.x = 30.49
        h._update_swimming_state()
        assert h.is_swimming is False

    def test_door_link_warp_clears_swimming_into_dry_level(self, swim_game):
        h = swim_game(DEEP)
        c = h.client
        h._update_swimming_state()
        assert h.is_swimming is True

        h._use_door_link({
            'dest_level': OTHER, 'dest_x': '24', 'dest_y': '26',
        })
        assert c._current_level_name == OTHER
        # Recomputed immediately by _use_door_link, not left stale from
        # the start level until the next run()-loop frame.
        assert h.is_swimming is False
        assert c.player.action_mode == 0  # TPlayer.cpp:6012
        assert h.leaps[-1] == ((5, c.x + 0.5, c.y + 1.0), {})

    def test_gs1_pending_warp_clears_swimming_into_dry_level(self, swim_game):
        h = swim_game(DEEP)
        c = h.client
        h._update_swimming_state()
        assert h.is_swimming is True

        h._pending_gs1_warp = (OTHER, 24.0, 26.0)
        h._process_pending_warp()
        assert c._current_level_name == OTHER
        assert h.is_swimming is False
        assert c.player.action_mode == 0  # TPlayer.cpp:6012
        assert h.leaps[-1] == ((5, c.x + 0.5, c.y + 1.0), {})

    def test_warp_into_water_sets_swimming_true(self, swim_game):
        # Symmetric case: a dry-level door_link warp landing in water.
        h = swim_game(0, other_tile=DEEP)
        c = h.client
        c.player.x, c.player.y = 24.0, 26.0
        h._update_swimming_state()
        assert h.is_swimming is False

        h._use_door_link({'dest_level': OTHER, 'dest_x': '30', 'dest_y': '30'})
        assert c._current_level_name == OTHER
        assert h.is_swimming is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
