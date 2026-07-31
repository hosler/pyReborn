"""Regression tests for the 2026-07-24 bomber-v6 "gs2 guis" live report.

Root causes found live (bomber.home.eevul.net:14915, hosler2, screenshots in
job a34dbef5 tmp/gui_before_* / gui_after_*):

1. The scripted GUI band (showimg/showtext layers with explicit
   changeimgvis >= 4) drew in showimg-INDEX order only. `vis` is a stratum:
   higher vis draws on top. The index only breaks ties within one stratum.
   The v6 -GraalUI HUD draws its white A/S/D/Q key letters at vis 6
   (indices 237-241) and their black drop-shadow copies at vis 5 on HIGHER
   indices (242-246) — index-only ordering painted the shadows over the
   white glyphs and the whole HUD lettering read as black-on-red.

2. SpriteManager.get_sprite clamped NEGATIVE part coordinates to the sheet's
   (0,0) corner. Scripts deliberately use negative part-x as "no sprite for
   this state" (-GraalUI's empty heart slots walk part-x -80, -160, ...,
   -1280). The real client samples off-sheet and draws nothing. The clamp
   only looked correct on reborn_system_hearts.png because that sheet's
   corner happens to be transparent.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pathlib import Path

import pygame

from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.sprites import SpriteManager

RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
GREEN = (0, 255, 0, 255)
BLACK = (0, 0, 0, 255)


def _solid(color):
    surf = pygame.Surface((20, 20), pygame.SRCALPHA)
    surf.fill(color)
    return surf


class _Harness(EntityRenderMixin):
    """Minimal GameClient stand-in for the showimg layer slice (same pattern
    as test_showimg_rotation.py). Sheets are solid colors keyed by name."""

    def __init__(self, sheets):
        self.screen = pygame.Surface((200, 200))
        self.screen.fill((0, 0, 0))
        self.camera = SimpleNamespace(
            scale=16.0,
            world_to_screen=lambda x, y: (x * 16.0, y * 16.0),
        )
        self.sprite_mgr = SimpleNamespace(
            load_sheet=lambda name: sheets.get(name),
            get_sprite=lambda name, *part: sheets.get(name),
        )
        self.requested = []

    def _request_asset(self, name):
        self.requested.append(name)


def _gui_rec(image, vis, x=50.0, y=50.0):
    return {'image': image, 'x': x, 'y': y, 'vis': vis, 'vis_set': True}


class TestGuiBandVisStratumOrder:
    def test_higher_vis_draws_on_top_despite_lower_index(self):
        # The -GraalUI shape: main layer at vis 6 with a LOW index, shadow
        # copy at vis 5 with a HIGHER index, both covering the same spot.
        h = _Harness({'white.png': _solid(RED), 'shadow.png': _solid(BLUE)})
        store = {
            237: _gui_rec('white.png', vis=6),
            242: _gui_rec('shadow.png', vis=5),
        }
        h._render_npc_layers(store, over=True, gui=True)
        assert h.screen.get_at((55, 55)) == RED     # vis 6 above vis 5

    def test_same_vis_still_stacks_by_index(self):
        h = _Harness({'a.png': _solid(RED), 'b.png': _solid(GREEN)})
        store = {
            300: _gui_rec('a.png', vis=4),
            301: _gui_rec('b.png', vis=4),
        }
        h._render_npc_layers(store, over=True, gui=True)
        assert h.screen.get_at((55, 55)) == GREEN   # higher index on top

    def test_world_over_band_uses_vis_strata_too(self):
        # vis 3 must draw above vis 2 even when its index is lower.
        h = _Harness({'top.png': _solid(RED), 'under.png': _solid(GREEN)})
        store = {
            10: {'image': 'top.png', 'x': 3.0, 'y': 3.0,
                 'vis': 3, 'vis_set': True},
            11: {'image': 'under.png', 'x': 3.0, 'y': 3.0,
                 'vis': 2, 'vis_set': True},
        }
        h._render_npc_layers(store, over=True, gui=False)
        assert h.screen.get_at((52, 52)) == RED


class TestNegativePartInvisible:
    def _sprite_manager(self, tmp_path: Path) -> SpriteManager:
        # A sheet whose (0,0) corner is OPAQUE red — under the old clamp a
        # negative part would wrongly render this corner.
        pygame.display.init()
        pygame.display.set_mode((32, 32))
        sheet = pygame.Surface((40, 20), pygame.SRCALPHA)
        sheet.fill(RED, pygame.Rect(0, 0, 20, 20))
        sheet.fill(GREEN, pygame.Rect(20, 0, 20, 20))
        path = tmp_path / "sheet.png"
        pygame.image.save(sheet, str(path))
        return SpriteManager([tmp_path])

    def test_negative_part_returns_none(self, tmp_path):
        sm = self._sprite_manager(tmp_path)
        assert sm.get_sprite('sheet.png', -20, 0, 20, 20) is None
        assert sm.get_sprite('sheet.png', 0, -5, 20, 20) is None

    def test_positive_overshoot_still_clamps(self, tmp_path):
        sm = self._sprite_manager(tmp_path)
        sprite = sm.get_sprite('sheet.png', 30, 0, 20, 20)
        assert sprite is not None
        assert sprite.get_size() == (10, 20)         # clamped to sheet edge
        assert sprite.get_at((5, 5)) == GREEN

    def test_valid_part_unaffected(self, tmp_path):
        sm = self._sprite_manager(tmp_path)
        sprite = sm.get_sprite('sheet.png', 20, 0, 20, 20)
        assert sprite is not None
        assert sprite.get_at((10, 10)) == GREEN

    def test_negative_part_rec_draws_nothing(self, tmp_path):
        sm = self._sprite_manager(tmp_path)
        h = _Harness({})
        h.sprite_mgr = sm
        rec = {'image': 'sheet.png', 'x': 50.0, 'y': 50.0,
               'vis': 4, 'vis_set': True, 'part': (-20, 0, 20, 20)}
        h._render_npc_layers({200: rec}, over=True, gui=True)
        assert h.screen.get_at((55, 55)) == BLACK
