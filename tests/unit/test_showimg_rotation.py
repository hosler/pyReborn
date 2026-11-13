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

import pygame
import pytest

from offline_game import stub_art

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLACK = (0, 0, 0, 255)


@pytest.fixture
def make_harness(make_game, monkeypatch):
    """``make_harness(sheet)``: a real offline game (its own screen, camera
    and layer renderer) whose every sheet is ``sheet``. The screen is black."""
    def build(sheet):
        game = make_game()
        stub_art(monkeypatch, game, sheet)
        return game
    return build


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
    def test_unrotated_layer_draws_at_topleft(self, make_harness):
        h = make_harness(_bar_sheet())
        h._render_showimg_rec(_gui_rec())
        # 40x8 bar at (50, 50): red half then green half.
        assert h.screen.get_at((55, 54)) == RED
        assert h.screen.get_at((85, 54)) == GREEN
        assert h.screen.get_at((70, 40)) == BLACK

    def test_rotation_spins_ccw_around_centre(self, make_harness):
        h = make_harness(_bar_sheet())
        h._render_showimg_rec(_gui_rec(rotation=math.pi / 2))
        # 90 deg CCW around the unrotated centre (70, 54): the bar becomes
        # vertical (x 66..74, y 34..74) with the green end on top.
        assert h.screen.get_at((70, 44)) == GREEN
        assert h.screen.get_at((70, 64)) == RED
        # The horizontal footprint is gone.
        assert h.screen.get_at((85, 54)) == BLACK
        assert h.screen.get_at((55, 54)) == BLACK

    def test_rotated_surface_memoized_per_rec(self, make_harness):
        h = make_harness(_bar_sheet())
        rec = _gui_rec(rotation=math.pi / 2)
        h._render_showimg_rec(rec)
        first = rec['_rot_surf']
        assert first.get_size() == (8, 40)
        h._render_showimg_rec(rec)
        assert rec['_rot_surf'] is first  # same angle -> no re-rotate
        rec['rotation'] = math.pi / 4
        h._render_showimg_rec(rec)
        assert rec['_rot_surf'] is not first

    def test_zero_rotation_skips_rotate_path(self, make_harness):
        h = make_harness(_bar_sheet())
        rec = _gui_rec(rotation=0.0)
        h._render_showimg_rec(rec)
        assert '_rot_surf' not in rec
        assert h.screen.get_at((55, 54)) == RED


class TestFindimgVisible:
    def test_visible_false_skips_layer(self, make_harness):
        h = make_harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec(visible=False)}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == BLACK

    def test_visible_unset_still_draws(self, make_harness):
        h = make_harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec()}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == RED

    def test_visible_true_draws(self, make_harness):
        h = make_harness(_bar_sheet())
        h._render_npc_layers({1: _gui_rec(visible=True)}, over=True, gui=True)
        assert h.screen.get_at((55, 54)) == RED

    def test_rotated_bbox_reaching_viewport_is_not_culled(self, make_harness,
                                                          monkeypatch):
        h = make_harness(_bar_sheet())
        drawn = []
        monkeypatch.setattr(h, '_render_showimg_rec', drawn.append)
        # A 40 px bar whose left edge sits 5 px right of the screen: culled
        # as it is, but its rotated bounding square reaches back in.
        (x0, y0), (x1, _) = (h.camera.world_to_screen(0.0, 0.0),
                             h.camera.world_to_screen(1.0, 0.0))
        scale = x1 - x0
        wx = (h.screen.get_width() + 5 - x0) / scale
        wy = (h.screen.get_height() / 2 - y0) / scale
        flat = {'image': 'cog_bar.png', 'x': wx, 'y': wy, 'vis': 1}
        h._render_npc_layers({1: flat}, over=False, on_screen_only=True)
        assert drawn == []
        rec = dict(flat, rotation=math.pi / 4)
        h._render_npc_layers({1: rec}, over=False, on_screen_only=True)
        assert drawn == [rec]
