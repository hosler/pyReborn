"""Regression tests for two render-cache staleness bugs found in the 2026-07-19
pygame-client audit:

1. addtiledef2/removetiledefs (game/setup.py's on_tiledef) cleared
   TilesetManager.tile_cache but not render_world.py's baked per-segment
   surface cache - a tileset swap kept blitting the OLD tileset's pixels
   until some unrelated event (board stream, level change) happened to force
   a full segment rebuild.

2. PLO_BOARDMODIFY (render_world.py's _patch_world_surface_for_modify) never
   updated a segment's `animated` water/lava index, so tiles added/removed by
   a board-modify delta kept animating (or failed to animate) as whatever
   type they were at segment-bake time.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest
from pyreborn import Client
from pyreborn.game.render_world import WorldRenderMixin
from pyreborn.game.camera import Camera2D
from pyreborn.game.setup import SetupMixin
from pyreborn.sprites import SpriteManager, TilesetManager
from pyreborn.tiletypes import get_tile_type, TileType

# A real WATER-type tile id (from tiletypes1.dat), used to exercise the
# animated-index update.
WATER_TILE_ID = 264
assert get_tile_type(WATER_TILE_ID) == TileType.WATER


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    return c


class _RenderHarness(SetupMixin, WorldRenderMixin):
    """Minimal GameClient stand-in exercising just the segment-cache slice
    of the mixins (on_tiledef via SetupMixin._setup_gs1_callbacks, the
    per-segment surface cache via WorldRenderMixin), without pygame
    display/asset/sound/GS1-engine setup."""

    def __init__(self, client):
        self.client = client
        self.gs1 = SimpleNamespace(resolve_ani=lambda name: name)
        self.player_anim = SimpleNamespace(name_resolver=None)
        self.current_anim_name = ""
        self.sprite_mgr = SpriteManager([])
        self.tileset_mgr = TilesetManager(self.sprite_mgr)
        self.world_surface = None
        self._setup_gs1_callbacks()


class TestTiledefInvalidatesSegmentCache:
    def test_set_tiledef_drops_cached_segment_surface(self):
        c = _fake_connected_client()
        c._current_level_name = "level1.nw"
        c.levels["level1.nw"] = [0] * 4096
        c.tiles = c.levels["level1.nw"]

        h = _RenderHarness(c)
        # _render_world() calls _apply_pending_full_invalidate() every frame
        # before blitting segments; simulate one frame having already run so
        # world_surface is in its steady True state, matching what a real
        # mid-session tiledef event sees (rather than the harness's freshly
        # constructed world_surface=None, which would trivially force a
        # rebuild on the very next call regardless of the fix under test).
        h._apply_pending_full_invalidate()
        first = h._get_segment_surface("level1.nw")
        assert first is not None
        # Cached: a second call with unchanged tiles/tiledefs returns the
        # exact same Surface object.
        assert h._get_segment_surface("level1.nw") is first

        h.gs1.on_tiledef("paste", "custom_tiles.png", "", 0, 0)
        # Reproduce _render_world()'s per-frame invalidation-application step.
        h._apply_pending_full_invalidate()

        second = h._get_segment_surface("level1.nw")
        assert second is not first, (
            "addtiledef2 must invalidate the baked segment surface so it "
            "re-renders with the new tileset instead of returning the stale "
            "pre-tiledef bake"
        )

    def test_clear_tiledefs_also_drops_cached_segment_surface(self):
        c = _fake_connected_client()
        c._current_level_name = "level1.nw"
        c.levels["level1.nw"] = [0] * 4096
        c.tiles = c.levels["level1.nw"]

        h = _RenderHarness(c)
        h._apply_pending_full_invalidate()
        h.gs1.on_tiledef("paste", "custom_tiles.png", "", 0, 0)
        h._apply_pending_full_invalidate()
        first = h._get_segment_surface("level1.nw")
        assert first is not None

        h.gs1.on_tiledef(None, None)  # removetiledefs
        h._apply_pending_full_invalidate()

        second = h._get_segment_surface("level1.nw")
        assert second is not first


class TestBoardModifyUpdatesAnimatedIndex:
    def test_water_tile_added_by_modify_is_indexed(self):
        c = _fake_connected_client()
        c._current_level_name = "level1.nw"
        tiles = [0] * 4096
        c.levels["level1.nw"] = tiles
        c.tiles = tiles

        h = _RenderHarness(c)
        h._get_segment_surface("level1.nw")  # bake with no water tiles
        entry = h._segments()["level1.nw"]
        assert entry['animated'] == []

        # Simulate what Client._apply_board_modify already did to
        # c.levels/c.tiles by the time on_board_modify fires: patch tile
        # (5, 5) to a WATER tile id in place.
        tiles[5 * 64 + 5] = WATER_TILE_ID
        h._patch_world_surface_for_modify({'x': 5, 'y': 5, 'width': 1, 'height': 1, 'layer': 0})

        assert (5, 5, WATER_TILE_ID) in entry['animated'], (
            "BOARDMODIFY must update the segment's animated water/lava index, "
            "not just re-blit the base tile"
        )

    def test_water_tile_removed_by_modify_is_unindexed(self):
        c = _fake_connected_client()
        c._current_level_name = "level1.nw"
        tiles = [0] * 4096
        tiles[5 * 64 + 5] = WATER_TILE_ID
        c.levels["level1.nw"] = tiles
        c.tiles = tiles

        h = _RenderHarness(c)
        h._get_segment_surface("level1.nw")  # bake WITH the water tile
        entry = h._segments()["level1.nw"]
        assert (5, 5, WATER_TILE_ID) in entry['animated']

        tiles[5 * 64 + 5] = 0
        h._patch_world_surface_for_modify({'x': 5, 'y': 5, 'width': 1, 'height': 1, 'layer': 0})

        assert entry['animated'] == [], (
            "BOARDMODIFY must drop stale animated-index entries for tiles "
            "that are no longer water/lava after the patch"
        )

    def test_modify_forces_animated_tiles_refold(self):
        """_refresh_animated_tiles_cache keys off id(surface), which an
        in-place patch doesn't change - the patch must also invalidate that
        key so the per-frame shimmer fold actually re-reads the updated
        animated index."""
        c = _fake_connected_client()
        c._current_level_name = "level1.nw"
        tiles = [0] * 4096
        c.levels["level1.nw"] = tiles
        c.tiles = tiles

        h = _RenderHarness(c)
        h._animated_tiles_key = "sentinel"
        h._get_segment_surface("level1.nw")
        tiles[5 * 64 + 5] = WATER_TILE_ID
        h._patch_world_surface_for_modify({'x': 5, 'y': 5, 'width': 1, 'height': 1, 'layer': 0})

        assert h._animated_tiles_key is None


class TestShimmerRamp:
    def test_ramp_cycles_off_half_full_half(self, monkeypatch):
        h = _RenderHarness(_fake_connected_client())
        times = iter((0.0, 0.3, 0.6, 0.9, 1.2))
        monkeypatch.setattr('pyreborn.game.render_world.time.time',
                            lambda: next(times))

        assert [h._shimmer_ramp_step() for _ in range(5)] == [0, 1, 2, 3, 0]

    def test_cache_is_zoom_keyed_and_precomputes_ramp_variants(self):
        h = _RenderHarness(_fake_connected_client())
        h.camera = Camera2D(320, 240)

        half = h._get_shimmer_tile(WATER_TILE_ID, 1)
        full = h._get_shimmer_tile(WATER_TILE_ID, 2)
        falling_half = h._get_shimmer_tile(WATER_TILE_ID, 3)
        assert half.get_size() == (16, 16)
        assert falling_half is half
        assert full is not half
        assert len(h._shimmer_cache) == 1
        assert len(h._shimmer_cache[(WATER_TILE_ID, 1.0)]) == 3

        h.camera.zoom = 1.5
        zoomed_half = h._get_shimmer_tile(WATER_TILE_ID, 1)
        assert zoomed_half.get_size() == (24, 24)
        assert zoomed_half is not half
        assert (WATER_TILE_ID, 1.5) in h._shimmer_cache


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
