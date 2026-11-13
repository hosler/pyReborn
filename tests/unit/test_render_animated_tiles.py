"""The cached shimmer blit list against the per-tile loop it replaced.

`reference_pass` is `_render_animated_tiles` as it was: every frame, one
`world_to_screen` + `_get_shimmer_tile` + `blit` per folded tile. Each test
warms the cache on a frame that draws the shimmer, changes one thing the
list or its surfaces depend on, draws again and requires the frame to equal
the reference pass over the same state, and to differ from the frame before
the change (so a stale list would have been caught, not just matched)."""

import types

import pygame
import pytest

from offline_game import GMAP_SEGMENTS, tile_color
from pyreborn.game import render_world

WATER = 264


def reference_pass(self):
    if not self.render_cache.shimmer_draw_this_frame:
        return
    tiles = self.render_cache.animated_tiles
    if not tiles:
        return
    for (tx, ty, tile_id) in tiles:
        sx, sy = self.camera.world_to_screen(tx, ty)
        tile = self._get_shimmer_tile(tile_id, self.render_cache.shimmer_step_this_frame)
        self.screen.blit(tile, (int(sx), int(sy)))


def rgb(surface):
    return pygame.image.tobytes(surface, "RGB")


def draw_frame(game):
    """Step 0.3 s at a time until a frame that draws the shimmer; its pixels."""
    for _ in range(8):
        game.frames(1, dt=0.3)
        if game.render_cache.shimmer_draw_this_frame:
            assert game.frame_errors == {}
            return rgb(game.last_frame)
    raise AssertionError("no shimmer frame in 8 steps")


def reference_frame(game):
    """The same frame again, with the per-tile loop doing the shimmer."""
    game._render_animated_tiles = types.MethodType(reference_pass, game)
    try:
        game.frames(1, dt=0.0)
    finally:
        del game._render_animated_tiles
    assert game.render_cache.shimmer_draw_this_frame
    return rgb(game.last_frame)


def folded(game):
    return {(x, y) for x, y, _ in game.render_cache.animated_tiles}


def check(game, before, cells=None):
    """`game` has changed since `before` was drawn: the next shimmer frame
    must equal the reference and must not be the old picture. `cells`, when
    given, is the set of water cells that must be in the folded list; the
    reference pass shares that list, so this is what catches a stale fold."""
    after = draw_frame(game)
    if cells is not None:
        assert folded(game) == cells, "folded animated list is stale"
    assert after == reference_frame(game), "cached shimmer list is stale"
    assert after != before, "the change did not reach the frame"
    return after


def water_at(cells):
    return lambda tx, ty: WATER if (tx, ty) in cells else 0


def block(x0, y0, w, h):
    return {(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)}


def test_same_frame_matches_reference(make_game):
    game = make_game(tiles=water_at(block(20, 20, 20, 10)))
    assert draw_frame(game) == reference_frame(game)
    assert game.render_cache.animated_tiles


def same_step_frame(game, dt=0.004):
    """One short frame that stays inside the ramp step of the last shimmer
    frame, so the cached list for that step is what gets reused."""
    step = game.render_cache.shimmer_step_this_frame
    game.frames(1, dt=dt)
    assert game.render_cache.shimmer_step_this_frame == step and game.render_cache.shimmer_draw_this_frame
    assert game.frame_errors == {}
    return rgb(game.last_frame)


def test_scrolling_matches_reference(make_game):
    """Standing still reuses the blit list; every sub-tile step inside one
    ramp step moves it."""
    game = make_game(tiles=water_at(block(10, 10, 40, 30)))
    draw_frame(game)
    seen = set()
    for _ in range(6):
        game.client.move(0, 1, step=0.37)
        pixels = same_step_frame(game)
        assert pixels == reference_frame(game)
        seen.add(pixels)
    assert len(seen) == 6


def test_standing_still_reuses_the_list_and_stays_correct(make_game):
    game = make_game(tiles=water_at(block(10, 10, 40, 30)))
    draw_frame(game)
    same_step_frame(game)
    held = game.render_cache.anim_draw.last_blits
    second = same_step_frame(game)
    assert game.render_cache.anim_draw.last_blits is held
    assert second == reference_frame(game)


def test_level_change_rebuilds(make_game):
    game = make_game(tiles=water_at(block(20, 20, 6, 6)),
                     extra_levels={"other.nw": water_at(block(28, 28, 8, 8))})
    before = draw_frame(game)
    assert before == reference_frame(game)

    async def warp(world, level, x, y):
        await world.me.warp(level, x, y)
    game.server.run(lambda w: warp(w, "other.nw", 30.0, 30.0))
    check(game, before, block(28, 28, 8, 8))
    assert game.client._current_level_name == "other.nw"


def test_gmap_segment_load_and_unload(make_game):
    """Water only in the south segment: it enters the folded list when the
    camera reaches it and leaves when the player walks back."""
    game = make_game(gmap=True, player_xy=(30.0, 10.0), tiles=lambda tx, ty: 0,
                     extra_levels={GMAP_SEGMENTS[2]: water_at(block(0, 0, 64, 64))})
    c = game.client
    start = draw_frame(game)
    assert game.render_cache.animated_tiles == [] and start == reference_frame(game)
    for _ in range(90):
        c.move(0, 1, step=0.5)
        game.frames(1)
    near = check(game, start)
    assert game.render_cache.animated_tiles
    assert all(y >= 64 for _, y in folded(game))
    for _ in range(90):
        c.move(0, -1, step=0.5)
        game.frames(1)
    check(game, near, set())
    assert game.render_cache.animated_tiles == []


def test_board_modify_adds_and_removes_water(make_game):
    from pyreborn.packets import PacketID
    game = make_game(tiles=water_at(block(20, 20, 4, 4)))
    before = draw_frame(game)

    def patch(tile):
        gc = lambda v: bytes([v + 32])
        data = gc(26) + gc(26) + gc(4) + gc(4)
        for _ in range(16):
            data += bytes([(tile >> 7) + 32, (tile & 127) + 32])
        game.feed(PacketID.PLO_BOARDMODIFY, data)
    patch(WATER)
    grown = check(game, before, block(20, 20, 4, 4) | block(26, 26, 4, 4))
    patch(0)
    check(game, grown, block(20, 20, 4, 4))


def test_resize_and_zoom_rebuild(make_game):
    game = make_game(tiles=water_at(block(10, 10, 40, 30)))
    before = draw_frame(game)
    game.viewport.handle_resize(640, 480)
    resized = check(game, before)
    game.camera.zoom = 1.5
    zoomed = check(game, resized)
    game.camera.zoom = 1.0
    check(game, zoomed)


def test_tileset_change_rebuilds(make_game, monkeypatch):
    game = make_game(tiles=water_at(block(20, 20, 10, 10)))
    before = draw_frame(game)
    original = game.tileset_mgr.get_tile_or_color

    def other(tile_id, *a, **k):
        surf = original(tile_id, *a, **k).copy()
        surf.fill((200, 30, 30))
        return surf
    monkeypatch.setattr(game.tileset_mgr, "get_tile_or_color", other)
    game._invalidate_tile_derived_caches()
    check(game, before)


def test_direct_zoom_changes_footprint_and_positions(make_game):
    """The debug camera draws the world with a zoomed camera, where scale and
    zoom (not just origin) change. Calls the pass directly on a cleared
    screen under each camera."""
    game = make_game(tiles=water_at(block(20, 20, 12, 12)))
    draw_frame(game)

    def both_ways():
        game.screen.fill((0, 0, 0))
        game._render_animated_tiles()
        mine = rgb(game.screen)
        game.screen.fill((0, 0, 0))
        reference_pass(game)
        assert mine == rgb(game.screen), "cached list stale under this camera"
        return mine

    one = both_ways()
    game.camera.zoom = 2.0
    two = both_ways()
    game.camera.zoom = 1.0
    again = both_ways()
    assert one != two and one == again


def test_shimmer_cache_cleared_alone_rebuilds(make_game):
    """Only the shimmer variants are dropped (surfaces and fold untouched):
    the held list must not keep pointing at the discarded surfaces."""
    game = make_game(tiles=water_at(block(20, 20, 10, 10)))
    draw_frame(game)
    same_step_frame(game)
    old = game.render_cache.anim_draw.last_blits[0][0]
    game.render_cache.shimmer.clear()
    same_step_frame(game)
    assert game.render_cache.anim_draw.last_blits[0][0] is not old
    assert game.render_cache.anim_draw.last_blits[0][0] is game._get_shimmer_tile(
        game.render_cache.animated_tiles[0][2], game.render_cache.shimmer_step_this_frame)


def test_in_place_board_patch_refolds(make_game):
    """A BOARDMODIFY patch edits the segment surface in place (same id), so
    only the explicit key reset makes the fold re-read the animated index."""
    game = make_game(tiles=water_at(block(20, 20, 4, 4)))
    c = game.client
    before = draw_frame(game)
    for ty in range(26, 30):
        for tx in range(26, 30):
            c.tiles[ty * 64 + tx] = WATER
            c.levels[c._tiles_level_name][ty * 64 + tx] = WATER
    game._patch_world_surface_for_modify(
        {'x': 26, 'y': 26, 'width': 4, 'height': 4, 'layer': 0})
    check(game, before, block(20, 20, 4, 4) | block(26, 26, 4, 4))
