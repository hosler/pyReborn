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

import pytest
from pyreborn.game.camera import Camera2D
from pyreborn.tiletypes import get_tile_type, TileType

# A real WATER-type tile id (from tiletypes1.dat), used to exercise the
# animated-index update.
WATER_TILE_ID = 264
assert get_tile_type(WATER_TILE_ID) == TileType.WATER

LEVEL = "level1.nw"


@pytest.fixture
def render_game(make_game):
    """``render_game(water=())``: a real offline game in level1.nw on an open
    board (``water`` = (tx, ty) cells that start as WATER). Returns
    ``(game, tiles)``, ``tiles`` being the level's own board list."""
    def build(water=()):
        cells = set(water)
        game = make_game(level=LEVEL, tiles=lambda tx, ty: (
            WATER_TILE_ID if (tx, ty) in cells else 0))
        return game, game.client.levels[LEVEL]
    return build


class TestTiledefInvalidatesSegmentCache:
    def test_set_tiledef_drops_cached_segment_surface(self, render_game):
        h, _ = render_game()
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

    def test_clear_tiledefs_also_drops_cached_segment_surface(self, render_game):
        h, _ = render_game()
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
    def test_water_tile_added_by_modify_is_indexed(self, render_game):
        h, tiles = render_game()
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

    def test_water_tile_removed_by_modify_is_unindexed(self, render_game):
        h, tiles = render_game(water=[(5, 5)])
        h._get_segment_surface("level1.nw")  # bake WITH the water tile
        entry = h._segments()["level1.nw"]
        assert (5, 5, WATER_TILE_ID) in entry['animated']

        tiles[5 * 64 + 5] = 0
        h._patch_world_surface_for_modify({'x': 5, 'y': 5, 'width': 1, 'height': 1, 'layer': 0})

        assert entry['animated'] == [], (
            "BOARDMODIFY must drop stale animated-index entries for tiles "
            "that are no longer water/lava after the patch"
        )

    def test_modify_forces_animated_tiles_refold(self, render_game):
        """_refresh_animated_tiles_cache keys off id(surface), which an
        in-place patch does not change - the patch must also invalidate that
        key so the per-frame shimmer fold actually re-reads the updated
        animated index."""
        h, tiles = render_game()
        h.render_cache.animated_tiles_key = "sentinel"
        h._get_segment_surface("level1.nw")
        tiles[5 * 64 + 5] = WATER_TILE_ID
        h._patch_world_surface_for_modify({'x': 5, 'y': 5, 'width': 1, 'height': 1, 'layer': 0})

        assert h.render_cache.animated_tiles_key is None


class TestShimmerRamp:
    def test_ramp_cycles_off_half_full_half(self, render_game):
        h, _ = render_game()
        times = iter((0.0, 0.3, 0.6, 0.9, 1.2))
        h.clock.set_sources(source=lambda: next(times))

        assert [h._shimmer_ramp_step() for _ in range(5)] == [0, 1, 2, 3, 0]

    def test_cache_is_zoom_keyed_and_precomputes_ramp_variants(self, render_game):
        h, _ = render_game()
        h.camera = Camera2D(320, 240)

        half = h._get_shimmer_tile(WATER_TILE_ID, 1)
        full = h._get_shimmer_tile(WATER_TILE_ID, 2)
        falling_half = h._get_shimmer_tile(WATER_TILE_ID, 3)
        assert half.get_size() == (16, 16)
        assert falling_half is half
        assert full is not half
        assert len(h.render_cache.shimmer) == 1
        assert len(h.render_cache.shimmer[(WATER_TILE_ID, 1.0)]) == 3

        h.camera.zoom = 1.5
        zoomed_half = h._get_shimmer_tile(WATER_TILE_ID, 1)
        assert zoomed_half.get_size() == (24, 24)
        assert zoomed_half is not half
        assert (WATER_TILE_ID, 1.5) in h.render_cache.shimmer


# -- every path that drops a RenderCache group-C field, proved by pixels --------
#
# Each test draws with the old art, changes the world, and requires the NEW
# colour at a named screen position (the style of tests/offline_checks.py:
# synthetic art gives every tile its own colour, so a stale cache entry shows
# up as the old colour). Mutations are written against the invalidation code,
# not the tests.

import io

import offline_expect as ex
import offline_game as og
import pygame
from pyreborn.packets import PacketID

SHEET = "dustynewpics1.png"
RED = (200, 40, 40)
BUMP_FULL = (18, 26, 34)        # the step-2 shimmer overlay (render_world)
CHEST_AT = (20, 20)
CLOSED_TOP_LEFT = 1784          # CHEST_TILES_CLOSED[0][0]
WATER_AT = (12, 26)
PROBE = (5, 25)          # a plain floor tile clear of the HUD and the player
PATCH_AT = (5, 26)
PLAYER = (30.0, 30.0)


def _flat_sheet_png(color=RED):
    surf = pygame.Surface((2048, 512))
    surf.fill(color)
    out = io.BytesIO()
    pygame.image.save(surf, out, "sheet.png")
    return out.getvalue()


def _floor(tx, ty):
    return 0


def _water_floor(tx, ty):
    return WATER_TILE_ID if (tx, ty) == WATER_AT else 0


def _origin(game):
    return ex.level_origin(game, PLAYER)


def _at(game, tx, ty):
    return ex.to_screen(_origin(game), tx + 0.5, ty + 0.5)


def _shimmered(color):
    return tuple(min(255, c + b) for c, b in zip(color, BUMP_FULL))


def _draw(game, frames=2):
    game._shimmer_ramp_step = lambda: 2     # the full-bright ramp step
    game.frames(frames)
    return game.last_frame


def _scene(make_game, **knobs):
    knobs.setdefault("tiles", _water_floor)
    knobs.setdefault("player_xy", PLAYER)
    game = make_game(**knobs)
    frame = _draw(game)
    return game, frame


def _expect_old_art(game, frame):
    ex.expect_pixel(frame, _at(game, *PROBE), og.tile_color(0), "old tile 0")
    ex.expect_pixel(frame, _at(game, *WATER_AT),
                    _shimmered(og.tile_color(WATER_TILE_ID)), "old shimmer")


class TestInvalidationPaths:
    def test_asset_arrival_of_the_base_sheet_redraws_segment_and_shimmer(
            self, make_game):
        """on_file with the base tileset -> _invalidate_tile_derived_caches.
        Mutations: (a) drop `self.world_surface = None` from that method or
        make _apply_pending_full_invalidate skip `self._segments().clear()`
        -> fails 'new tile 0'; (b) drop `render_cache.shimmer.clear()` ->
        fails 'new shimmer'."""
        game, frame = _scene(make_game)
        _expect_old_art(game, frame)

        game.client.emit('on_file', SHEET, _flat_sheet_png())
        frame = _draw(game)

        ex.expect_pixel(frame, _at(game, *PROBE), RED, "new tile 0")
        ex.expect_pixel(frame, _at(game, *WATER_AT), _shimmered(RED),
                        "new shimmer")

    def test_asset_arrival_redraws_the_chest_sprite(self, make_game):
        """Mutation: drop `render_cache.chest_sprite.clear()` from
        _invalidate_tile_derived_caches -> fails 'new chest'."""
        game, frame = _scene(make_game, chests=[(*CHEST_AT, False)])
        ex.expect_pixel(frame, _at(game, *CHEST_AT),
                        og.tile_color(CLOSED_TOP_LEFT), "old chest")
        assert game.render_cache.chest_sprite

        game.client.emit('on_file', SHEET, _flat_sheet_png())
        frame = _draw(game)

        ex.expect_pixel(frame, _at(game, *CHEST_AT), RED, "new chest")

    def test_tiledef_paste_and_removal_redraw_everything(self, make_game):
        """on_tiledef (addtiledef2 / removetiledefs). Mutation: as the asset
        test, applied to either call site -> the 'pasted' or 'restored'
        assertions fail."""
        game, frame = _scene(make_game, chests=[(*CHEST_AT, False)])
        game.sprite_mgr.load_bytes("redsheet.png", _flat_sheet_png())

        game.gs1.on_tiledef("paste", "redsheet.png", "", 0, 0)
        frame = _draw(game)
        ex.expect_pixel(frame, _at(game, *PROBE), RED, "pasted tile 0")
        ex.expect_pixel(frame, _at(game, *WATER_AT), _shimmered(RED),
                        "pasted shimmer")
        ex.expect_pixel(frame, _at(game, *CHEST_AT), RED, "pasted chest")

        game.gs1.on_tiledef(None, None)
        frame = _draw(game)
        _expect_old_art(game, frame)
        ex.expect_pixel(frame, _at(game, *CHEST_AT),
                        og.tile_color(CLOSED_TOP_LEFT), "restored chest")

    def test_level_change_redraws_shimmer_and_chest_from_the_new_tileset(
            self, make_game):
        """A level-scoped full tiledef applies only to other.nw. Warping
        there and back runs _reload_level_scripts -> the invalidation.
        Mutations: drop shimmer.clear() -> fails 'other shimmer'; skip the
        segment clear (see the asset test) -> fails 'other tile 0'. The chest
        sprite is pinned by the two tests above (the chest exists only in
        the start level)."""
        game, frame = _scene(make_game, chests=[(*CHEST_AT, False)],
                             extra_levels={"other.nw": _water_floor})
        game.sprite_mgr.load_bytes("redsheet.png", _flat_sheet_png())
        game.tileset_mgr.set_full_tiledef("redsheet.png", "other", 0)

        async def warp(world, level, x, y):
            await world.me.warp(level, x, y)

        game.server.run(lambda w: warp(w, "other.nw", *PLAYER))
        frame = _draw(game, 70)
        assert game.client._current_level_name == "other.nw"
        ex.expect_pixel(frame, _at(game, *PROBE), RED, "other tile 0")
        ex.expect_pixel(frame, _at(game, *WATER_AT), _shimmered(RED),
                        "other shimmer")

        game.server.run(lambda w: warp(w, "fixture.nw", *PLAYER))
        frame = _draw(game, 70)
        assert game.client._current_level_name == "fixture.nw"
        _expect_old_art(game, frame)
        ex.expect_pixel(frame, _at(game, *CHEST_AT),
                        og.tile_color(CLOSED_TOP_LEFT), "chest after return")

    def test_board_modify_redraws_tile_and_adds_the_shimmer(self, make_game):
        """PLO_BOARDMODIFY patches the segment in place and must refold the
        animated list. Mutations: drop the in-place re-blit in
        _patch_world_surface_for_modify -> fails 'patched tile'; drop its
        `render_cache.animated_tiles_key = None` -> also fails 'patched
        tile' (the shimmer never covers it) and the refold test above."""
        game, frame = _scene(make_game)
        gc = lambda v: bytes([v + 32])
        data = gc(PATCH_AT[0]) + gc(PATCH_AT[1]) + gc(1) + gc(1)
        data += bytes([(WATER_TILE_ID >> 7) + 32, (WATER_TILE_ID & 127) + 32])
        game.feed(PacketID.PLO_BOARDMODIFY, data)
        frame = _draw(game)

        ex.expect_pixel(frame, _at(game, *PATCH_AT),
                        _shimmered(og.tile_color(WATER_TILE_ID)),
                        "patched tile")
        ex.expect_pixel(frame, _at(game, *WATER_AT),
                        _shimmered(og.tile_color(WATER_TILE_ID)), "new water")
        assert (*PATCH_AT, WATER_TILE_ID) in game.render_cache.animated_tiles

    def test_a_new_board_list_rebuilds_the_segment(self, make_game):
        """A board stream assigns a new tiles list (new id()); the segment
        entry's tiles_id no longer matches. Mutation: make
        _get_segment_surface return `entry['surface']` without comparing
        tiles_id -> fails 'streamed tile'."""
        game, frame = _scene(make_game)
        level = game.client._current_level_name
        board = list(game.client.levels[level])
        board[PATCH_AT[1] * 64 + PATCH_AT[0]] = 2
        game.client.levels[level] = board
        if game.client._tiles_level_name == level:
            game.client.tiles = board
        frame = _draw(game)

        ex.expect_pixel(frame, _at(game, *PATCH_AT), og.tile_color(2),
                        "streamed tile")

    def test_replacing_the_cache_object_clears_every_group_c_field(
            self, make_game):
        """The group-C fields live only on render_cache: a fresh object is a
        full invalidation and the frame is unchanged (pixels)."""
        game, frame = _scene(make_game, chests=[(*CHEST_AT, False)])
        before = pygame.image.tobytes(frame, "RGB")
        from pyreborn.game.render_cache import RenderCache
        game.render_cache = RenderCache()
        again = _draw(game)
        assert pygame.image.tobytes(again, "RGB") == before
        for name in ("segment", "shimmer", "chest_sprite"):
            assert getattr(game.render_cache, name)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
