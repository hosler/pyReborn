"""Frame scenes for the two render scaling paths: nameplate staggering with
many overlapping plates, and the water/lava shimmer pass on a level and on a
gmap. The existing offline scenes carry few of either, so these are the ones a
change to `_place_nameplate` or `_render_animated_tiles` has to leave
pixel-identical (frame-baseline captures) and that the invalidation tests in
test_render_animated_tiles.py build on."""

import offline_game
from frame_baseline import capture
from offline_game import GMAP_SEGMENTS, NAMED_NPC

WATER = 264          # a WATER tile in the default tilestype table


def water_field(tx, ty):
    """Water everywhere inside the border except a few dry stripes, so the
    animated index is large and not a solid rectangle."""
    if tx in (0, 63) or ty in (0, 63):
        return 2
    if (tx + 2 * ty) % 11 == 0:
        return 0
    return WATER


def crowd(n, cluster):
    """`n` nickname-bearing NPCs packed onto a few tiles so their plates
    overlap in long stagger chains."""
    npcs = []
    for i in range(n):
        spec = dict(NAMED_NPC)
        spec.update(id=200 + i, nickname=f"Guard {i % 7}",
                    x=24.0 + (i % cluster) * 0.5,
                    y=26.0 + (i % 3) * 0.25)
        npcs.append(spec)
    return npcs


def test_overlapping_nameplates_frame(make_game):
    game = make_game(npcs=crowd(64, 5))
    game.frames(4)
    capture(game, "crowd_a")
    game.frames(3)
    capture(game, "crowd_b")
    assert game.frame_errors == {}


def test_nameplates_spread_frame(make_game):
    game = make_game(npcs=crowd(70, 40))
    game.frames(4)
    capture(game, "spread")
    assert game.frame_errors == {}


def test_shimmer_on_level_frames(make_game):
    game = make_game(tiles=water_field)
    # Four consecutive 0.3 s ramp steps, so every phase is captured.
    for i in range(5):
        game.frames(1, dt=0.3)
        capture(game, f"level_{i}")
    assert game.render_cache.animated_tiles, "scene must contain animated tiles"
    assert game.frame_errors == {}


def test_shimmer_on_gmap_frames(make_game):
    game = make_game(gmap=True, tiles=water_field, player_xy=(60.0, 60.0))
    for i in range(5):
        game.frames(1, dt=0.3)
        capture(game, f"gmap_{i}")
    assert len(game.render_cache.animated_tiles) > 500
    # walk across the seam so the shimmer list is re-folded mid-run
    for step in range(6):
        game.client.move(1, 0, step=0.5)
        game.frames(1, dt=0.3)
        capture(game, f"gmap_walk_{step}")
    assert game.frame_errors == {}
