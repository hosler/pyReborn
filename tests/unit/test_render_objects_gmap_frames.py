"""Regression tests for the 2026-07-19 follow-up gmap frame bugs, same class
as the chest/collision fixes in test_collision_gmap_frames.py:

1. _render_chests and _render_items passed level-local (0-63) coords straight
   into _world_to_screen (which expects world coords), so every ground object
   off the origin gmap segment rendered at its bare local coordinate instead
   of its real position. Items also sorted with that local Y, disagreeing with
   the folded blit frame and nearby world-frame actors.
2. _check_sign_nearby (game/actions.py, the A-press sign-read path) used a
   raw %64 wrap to fold world touch points to level-local, the same
   wraparound bug _check_and_render_signs had (fixed via a signed
   segment-relative delta against the current segment's grid origin).

Both now go through the shared LevelObjectsRenderMixin._current_segment_origin
helper.
"""

import pygame
import pytest

from offline_game import GMAP_SEGMENTS
from pyreborn.tiletypes import is_blocking

# The fixture's 2x2 gmap: SPAWN (fixture_d.nw) is at grid (1, 1), world origin
# (64, 64); OTHER (fixture_c.nw) is the segment to its west, grid (0, 1).
SPAWN = GMAP_SEGMENTS[3]
OTHER = GMAP_SEGMENTS[2]
NORTH_WEST = GMAP_SEGMENTS[0]
WALL = next(t for t in range(4096) if is_blocking(t))


@pytest.fixture
def grid_game(make_game, monkeypatch):
    """``grid_game(gmap_segment=(1, 1), **knobs)``: a real offline game on the
    fixture gmap, standing in ``gmap_segment``. ``game.world_to_screen_calls``
    records every world coordinate the renderer converts through the camera
    (the conversion itself still runs); the screen is the game's own."""
    def build(gmap_segment=(1, 1), **knobs):
        knobs.setdefault('gmap', True)
        game = make_game(gmap_segment=gmap_segment, **knobs)
        game.frames(1)               # the camera now follows the player
        game.world_to_screen_calls = []
        real = game.camera.world_to_screen

        def world_to_screen(world_x, world_y):
            game.world_to_screen_calls.append((world_x, world_y))
            return real(world_x, world_y)
        monkeypatch.setattr(game.camera, 'world_to_screen', world_to_screen)
        return game
    return build


class TestRenderChestsSegmentOrigin:
    def test_chest_world_screen_call_uses_segment_origin(self, grid_game):
        h = grid_game(chests=[(5, 5, False)])

        h._render_chests()

        # Local (5, 5) on segment (1, 1) -> world (69, 69), not the bare
        # local (5, 5) the old code passed straight through.
        assert h.world_to_screen_calls == [(69, 69)]

    def test_chest_on_origin_segment_is_unaffected(self, grid_game):
        h = grid_game(gmap=False, level="standalone.nw",
                      chests=[(5, 5, False)])

        h._render_chests()

        assert h.world_to_screen_calls == [(5, 5)]


class TestRenderItemsSegmentOrigin:
    def test_item_blit_and_depth_use_world_frame(self, grid_game, sim_time,
                                                 monkeypatch):
        h = grid_game(items=[(5.0, 5.0, 0)], player_xy=(8.0, 8.0))
        # A 16x16 stand-in for the item art keeps the (x+1, y+1) centring the
        # expected coordinates are written for.
        monkeypatch.setattr(h, '_get_item_sprite',
                            lambda item_type: pygame.Surface((16, 16), pygame.SRCALPHA))
        h.client.item_stamps[(SPAWN, (5.0, 5.0))] = 100.0
        sim_time(lambda: 102.0)
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_items(entities, frame)

        # The live failure drew at local (5, 5), and a partial fix could fold
        # the blit while still sorting at local Y. Both must describe world
        # (69, 69), placing the item beside actors in this segment.
        # TServerExtra.cpp:59-74: sprite centred at (x+1,y+1), shadow below.
        assert h.world_to_screen_calls == [(69.5, 69.5), (69.5, 70.0)]
        assert len(entities) == 1
        assert entities[0].depth == h._depth_sort_key(69.0, 2.0)


class TestRenderBaddiesSegmentOrigin:
    def test_baddy_blit_and_depth_use_owning_segment_world_frame(self, grid_game):
        h = grid_game(player_xy=(8.0, 8.0))      # on screen, near world (69, 69)
        c = h.client
        c.baddies = {
            SPAWN: {1: {"x": 5.0, "y": 5.0}},
            OTHER: {2: {"x": 5.0, "y": 5.0}},
        }
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_baddies(entities, frame)

        assert h.world_to_screen_calls == [(69.0, 69.0)]
        assert [entity.key for entity in entities] == [1]
        assert entities[0].depth == h._depth_sort_key(
            69.0, h._baddy_height_tiles(c.baddies[SPAWN][1]))

    def test_same_local_position_in_adjacent_segments_stays_independent(self, grid_game):
        c = grid_game().client
        west = {"x": 5.0, "y": 5.0, "power": 2}
        east = {"x": 5.0, "y": 5.0, "power": 4}
        c.baddies = {SPAWN: {1: west}, OTHER: {2: east}}

        assert c.baddies_in_level(SPAWN) == {1: west}
        assert c.baddies_in_level(OTHER) == {2: east}


class TestRenderHorsesSegmentOrigin:
    def test_horse_blit_and_depth_use_owning_segment_world_frame(self, grid_game):
        h = grid_game(player_xy=(8.0, 8.0))      # on screen, near world (69, 69)
        c = h.client
        key = (5.0, 5.0)
        c.horses = {
            SPAWN: {key: {"x": 5.0, "y": 5.0}},
            OTHER: {key: {"x": 5.0, "y": 5.0}},
        }
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_horses(entities, frame)

        assert h.world_to_screen_calls == [(69.0, 69.0)]
        assert [entity.key for entity in entities] == [key]
        assert entities[0].depth == h._depth_sort_key(
            69.0, h._horse_height_tiles(c.horses[SPAWN][key]))

    def test_same_local_position_in_adjacent_segments_stays_independent(self, grid_game):
        c = grid_game().client
        key = (5.0, 5.0)
        west = {"x": 5.0, "y": 5.0, "image": "west.png"}
        east = {"x": 5.0, "y": 5.0, "image": "east.png"}
        c.horses = {SPAWN: {key: west}, OTHER: {key: east}}

        assert c.horses_in_level(SPAWN) == {key: west}
        assert c.horses_in_level(OTHER) == {key: east}


class TestCheckSignNearbySegmentOrigin:
    def test_finds_a_sign_off_the_origin_segment(self, grid_game):
        h = grid_game(signs=[(5, 5, "hello")],
                      tiles=lambda tx, ty: WALL if (tx, ty) == (5, 5) else 0)
        c = h.client
        # TPlayer.cpp:2849 reads a sign only with the upward wall probe.
        c.player.x, c.player.y = 64 + 4.0, 64 + 5.0
        c.player.direction = 0

        assert h._check_sign_nearby() == "hello\n"

    def test_no_false_match_across_a_segment_boundary(self, grid_game):
        """Documents the wrap bug: world x=64.9 (just past segment (0,0)'s
        edge) must NOT read as local x=0.9 and match a sign sitting at local
        (0, 0) in a DIFFERENT segment than the player is actually in."""
        h = grid_game(gmap_segment=(0, 0), signs=[(0, 0, "far away")])
        c = h.client
        assert c._current_level_name == NORTH_WEST   # grid (0, 0), origin (0, 0)
        # The upward probe crosses the segment edge; it must not wrap
        # back into the sign box at the current level's opposite corner.
        c.player.x, c.player.y = 63.0, 63.5
        c.player.direction = 0

        assert h._check_sign_nearby() is None
