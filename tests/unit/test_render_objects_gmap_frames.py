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

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.frame_context import FrameContextMixin
from pyreborn.game.render_collect import EntityCollectMixin
from pyreborn.game.render_objects import LevelObjectsRenderMixin


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
    # Same 3x3 chicken.gmap layout as test_collision_gmap_frames.py /
    # test_gmap_coordination.py: chicken1.nw at grid (1, 1) -> world origin
    # (64, 64).
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
    return c


class _ChestRenderHarness(LevelObjectsRenderMixin, EntityCollectMixin,
                          FrameContextMixin):
    """Minimal GameClient stand-in for _render_chests: stubs out
    _get_chest_sprite (tileset-backed) and _world_to_screen (camera-backed,
    defined on RenderMixin) so the test only exercises the coordinate fold,
    not tileset loading or camera math."""

    def __init__(self, client):
        self.client = client
        self.camera = self
        self.screen = pygame.Surface((800, 600))
        self.world_to_screen_calls = []

    def _get_chest_sprite(self, opened: bool):
        return pygame.Surface((32, 32), pygame.SRCALPHA)

    def _world_to_screen(self, world_x, world_y):
        self.world_to_screen_calls.append((world_x, world_y))
        return (100.0, 100.0)  # safely on-screen, regardless of input

    world_to_screen = _world_to_screen

    def _get_item_sprite(self, item_type):
        return pygame.Surface((16, 16), pygame.SRCALPHA)

    def _baddy_height_tiles(self, baddy):
        return 2.0

    def _horse_height_tiles(self, horse):
        return 2.0


class TestRenderChestsSegmentOrigin:
    def test_chest_world_screen_call_uses_segment_origin(self):
        c = _client_with_grid()
        c.chests = {(5, 5): False}
        h = _ChestRenderHarness(c)

        h._render_chests()

        # Local (5, 5) on segment (1, 1) -> world (69, 69), not the bare
        # local (5, 5) the old code passed straight through.
        assert h.world_to_screen_calls == [(69, 69)]

    def test_chest_on_origin_segment_is_unaffected(self):
        c = _fake_connected_client()
        c._current_level_name = "standalone.nw"  # not in_gmap_segment
        c.chests = {(5, 5): False}
        h = _ChestRenderHarness(c)

        h._render_chests()

        assert h.world_to_screen_calls == [(5, 5)]


class TestRenderItemsSegmentOrigin:
    def test_item_blit_and_depth_use_world_frame(self):
        c = _client_with_grid()
        c.items = {"chicken1.nw": {(5.0, 5.0): "greenrupee"}}
        h = _ChestRenderHarness(c)
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_items(entities, frame)

        # The live failure drew at local (5, 5), and a partial fix could fold
        # the blit while still sorting at local Y. Both must describe world
        # (69, 69), placing the item beside actors in this segment.
        assert h.world_to_screen_calls == [(69.0, 69.0)]
        assert len(entities) == 1
        assert entities[0].depth == h._depth_sort_key(69.0, 1.0)


class TestRenderBaddiesSegmentOrigin:
    def test_baddy_blit_and_depth_use_owning_segment_world_frame(self):
        c = _client_with_grid()
        c.baddies = {
            "chicken1.nw": {1: {"x": 5.0, "y": 5.0}},
            "chicken7.nw": {2: {"x": 5.0, "y": 5.0}},
        }
        h = _ChestRenderHarness(c)
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_baddies(entities, frame)

        assert h.world_to_screen_calls == [(69.0, 69.0)]
        assert [entity.key for entity in entities] == [1]
        assert entities[0].depth == h._depth_sort_key(
            69.0, h._baddy_height_tiles(c.baddies["chicken1.nw"][1]))

    def test_same_local_position_in_adjacent_segments_stays_independent(self):
        c = _client_with_grid()
        west = {"x": 5.0, "y": 5.0, "power": 2}
        east = {"x": 5.0, "y": 5.0, "power": 4}
        c.baddies = {"chicken1.nw": {1: west}, "chicken7.nw": {2: east}}

        assert c.baddies_in_level("chicken1.nw") == {1: west}
        assert c.baddies_in_level("chicken7.nw") == {2: east}


class TestRenderHorsesSegmentOrigin:
    def test_horse_blit_and_depth_use_owning_segment_world_frame(self):
        c = _client_with_grid()
        key = (5.0, 5.0)
        c.horses = {
            "chicken1.nw": {key: {"x": 5.0, "y": 5.0}},
            "chicken7.nw": {key: {"x": 5.0, "y": 5.0}},
        }
        h = _ChestRenderHarness(c)
        entities = []
        frame = h._frame_context()
        frame.screen_size = h.screen.get_size()

        h._collect_horses(entities, frame)

        assert h.world_to_screen_calls == [(69.0, 69.0)]
        assert [entity.key for entity in entities] == [key]
        assert entities[0].depth == h._depth_sort_key(
            69.0, h._horse_height_tiles(c.horses["chicken1.nw"][key]))

    def test_same_local_position_in_adjacent_segments_stays_independent(self):
        c = _client_with_grid()
        key = (5.0, 5.0)
        west = {"x": 5.0, "y": 5.0, "image": "west.png"}
        east = {"x": 5.0, "y": 5.0, "image": "east.png"}
        c.horses = {"chicken1.nw": {key: west}, "chicken7.nw": {key: east}}

        assert c.horses_in_level("chicken1.nw") == {key: west}
        assert c.horses_in_level("chicken7.nw") == {key: east}


class _SignCheckHarness(ActionsMixin, CollisionMixin, LevelObjectsRenderMixin):
    def __init__(self, client):
        self.client = client
        self.tile_corrections = {}


class TestCheckSignNearbySegmentOrigin:
    def test_finds_a_sign_off_the_origin_segment(self):
        c = _client_with_grid()
        c.signs = {"chicken1.nw": {(5, 5): "hello"}}
        c.player.x, c.player.y = 64 + 5.2, 64 + 1.6  # see test_collision_gmap_frames
        c.player.direction = 2  # down

        h = _SignCheckHarness(c)
        assert h._check_sign_nearby() == "hello"

    def test_no_false_match_across_a_segment_boundary(self):
        """Documents the wrap bug: world x=64.9 (just past segment (0,0)'s
        edge) must NOT read as local x=0.9 and match a sign sitting at local
        (0, 0) in a DIFFERENT segment than the player is actually in."""
        c = _client_with_grid()
        c._current_level_name = "chicken4.nw"  # grid (0, 0), origin (0, 0)
        c.signs = {"chicken4.nw": {(0, 0): "far away"}}
        # Both x and y touch points land just past 64 (world (64.4, 64.1));
        # %64 wraps that to (0.4, 0.1) -- right next to the sign at local
        # (0, 0), even though the player is actually clear across the
        # level from it.
        c.player.x, c.player.y = 63.9, 60.6
        c.player.direction = 2  # down

        h = _SignCheckHarness(c)
        assert h._check_sign_nearby() is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
