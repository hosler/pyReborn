"""Regression tests for the two showimg residuals noted after the bomber-v6
wave (commit 59976de):

1. findimg(i).rotation was stored on the layer record (gs2_client._LayerImage
   writes it through) but _render_showimg_rec never applied it — the v6
   lobby's CadavreTest cogs (showimg cadavrezcog2.png + a 0.01s setTimer loop
   nudging .rotation) drew frozen. Reference semantics from the C# client's
   ShowImg/Drawing.cs: radians, pivot = drawn image centre, positive =
   counter-clockwise on screen (it negates the angle for MonoGame's
   clockwise convention. Pygame's rotate() is already CCW).

2. findimg(i).visible = false stored 'visible': False on the record but the
   renderer ignored it, so hidden layers kept drawing.
"""

import math
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame

from pyreborn.game.render_entities import EntityRenderMixin

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLACK = (0, 0, 0, 255)


class _Harness(EntityRenderMixin):
    """Minimal GameClient stand-in exercising just the showimg layer slice of
    EntityRenderMixin — no pygame display/asset/GS1-engine setup."""

    def __init__(self, sheet: pygame.Surface):
        self.screen = pygame.Surface((200, 200))
        self.screen.fill((0, 0, 0))
        self.camera = SimpleNamespace(
            scale=16.0,
            world_to_screen=lambda x, y: (x * 16.0, y * 16.0),
        )
        self.sprite_mgr = SimpleNamespace(
            load_sheet=lambda name: sheet,
            get_sprite=lambda name, *part: sheet,
        )
        self.requested = []

    def _request_asset(self, name):
        self.requested.append(name)


def _bar_sheet():
    """40x8 bar: left half red, right half green — asymmetric in both axes'
    extents AND ends, so the test can tell rotation direction apart."""
    surf = pygame.Surface((40, 8), pygame.SRCALPHA)
    surf.fill(RED, pygame.Rect(0, 0, 20, 8))
    surf.fill(GREEN, pygame.Rect(20, 0, 20, 8))
    return surf


def _gui_rec(**extra):
    rec = {'image': 'cog_bar.png', 'x': 50.0, 'y': 50.0,
           'vis': 4, 'vis_set': True}
    rec.update(extra)
    return rec


class TestShowimgRotation:
    def test_unrotated_layer_draws_at_topleft(self):
        h = _Harness(_bar_sheet())
        h._render_showimg_rec(_gui_rec())
        # 40x8 bar at (50, 50): red half then green half.
        assert h.screen.get_at((55, 54)) == RED
        assert h.screen.get_at((85, 54)) == GREEN
        assert h.screen.get_at((70, 40)) == BLACK

    def test_rotation_spins_ccw_around_centre(self):
        h = _Harness(_bar_sheet())
        h._render_showimg_rec(_gui_rec(rotation=math.pi / 2))
        # 90 deg CCW around the unrotated centre (70, 54): the bar becomes
        # vertical (x 66..74, y 34..74) with the green end on top.
        assert h.screen.get_at((70, 44)) == GREEN
        assert h.screen.get_at((70, 64)) == RED
        # The horizontal footprint is gone.
        assert h.screen.get_at((85, 54)) == BLACK
        assert h.screen.get_at((55, 54)) == BLACK

    def test_rotated_surface_memoized_per_rec(self):
        h = _Harness(_bar_sheet())
        rec = _gui_rec(rotation=math.pi / 2)
        h._render_showimg_rec(rec)
        first = rec['_rot_surf']
        assert first.get_size() == (8, 40)
        h._render_showimg_rec(rec)
        assert rec['_rot_surf'] is first  # same angle -> no re-rotate
        rec['rotation'] = math.pi / 4
        h._render_showimg_rec(rec)
        assert rec['_rot_surf'] is not first

    def test_zero_rotation_skips_rotate_path(self):
        h = _Harness(_bar_sheet())
        rec = _gui_rec(rotation=0.0)
        h._render_showimg_rec(rec)
        assert '_rot_surf' not in rec
        assert h.screen.get_at((55, 54)) == RED


class TestFindimgVisible:
    def test_visible_false_skips_layer(self):
        h = _Harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec(visible=False)}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == BLACK

    def test_visible_unset_still_draws(self):
        h = _Harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec()}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == RED

    def test_visible_true_draws(self):
        h = _Harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec(visible=True)}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == RED

    def test_rotated_bbox_reaching_viewport_is_not_culled(self):
        h = _Harness(_bar_sheet())
        drawn = []
        h._render_showimg_rec = drawn.append
        rec = {'image': 'cog_bar.png', 'x': 13.0, 'y': 4.0,
               'vis': 1, 'rotation': math.pi / 4}
        h._render_npc_layers({1: rec}, over=False, on_screen_only=True)
        assert drawn == [rec]
