"""Tests for the ground-item sprite lookup in game/render_objects.py.

_ITEM_SPRITE_TABLE maps LevelItemType names to a verified pics1.png
(sheet, x, y, w, h) rect; _get_item_sprite() crops+caches it via
sprite_mgr.get_sprite() and falls back to the pre-existing vector icon when a
table entry is missing or its sheet/crop can't be loaded (headless tests,
missing assets). As of this pass the table is empty -- see its module-level
comment in render_objects.py for the research that came up dry -- so these
tests mainly guard: (1) every LevelItemType name still gets *some* surface
back, and (2) the table-hit/table-miss code paths behave correctly whenever
entries do get added.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn.game import render_objects
from pyreborn.game.constants import TILE_SIZE
from pyreborn.game.render_objects import LevelObjectsRenderMixin, _ITEM_SPRITE_TABLE
from pyreborn.sprites import SpriteManager

pygame.init()
# convert_alpha() (used by SpriteManager.load_sheet) needs a display surface,
# even the dummy SDL driver's 1x1 one, or it raises "Parameter 'surface' is
# invalid" -- only test_table_hit_crops_and_caches_the_real_sheet below
# actually loads a real sheet, but this is harmless for the others.
pygame.display.set_mode((1, 1))

# Matches the 25 LevelItemType names in reborn_protocol.constants.LevelItemType
# (and GServer-v2's server/include/level/LevelItem.h ItemNames table).
ALL_ITEM_NAMES = [
    'greenrupee', 'bluerupee', 'redrupee', 'bombs', 'darts',
    'heart', 'glove1', 'bow', 'bomb', 'shield',
    'sword', 'fullheart', 'superbomb', 'battleaxe', 'goldensword',
    'mirrorshield', 'glove2', 'lizardshield', 'lizardsword', 'goldrupee',
    'fireball', 'fireblast', 'nukeshot', 'joltbomb', 'spinattack',
]


class _ItemRenderHarness(LevelObjectsRenderMixin):
    """Minimal GameClient stand-in: just needs a sprite_mgr for
    _get_item_sprite() to crop from."""

    def __init__(self, sprite_mgr):
        self.sprite_mgr = sprite_mgr


def _headless_harness():
    """A harness whose SpriteManager has no search paths, so every sheet
    lookup misses -- simulates both the offline test environment and a
    genuinely-missing asset."""
    return _ItemRenderHarness(SpriteManager(search_paths=[]))


class TestItemSpriteTableShape:
    def test_table_covers_a_subset_of_the_known_item_names(self):
        """Every table entry must be for a real LevelItemType name (typos
        would silently never match anything in _get_item_sprite)."""
        assert set(_ITEM_SPRITE_TABLE.keys()) <= set(ALL_ITEM_NAMES)

    def test_table_rects_are_well_formed_and_non_overlapping_per_sheet(self):
        """Guards any future (sheet, x, y, w, h) entries: positive size, and
        no two items sharing the same sheet crop overlapping pixels (a sure
        sign one of them was mis-copied)."""
        by_sheet = {}
        for name, (sheet, x, y, w, h) in _ITEM_SPRITE_TABLE.items():
            assert w > 0 and h > 0, name
            assert x >= 0 and y >= 0, name
            by_sheet.setdefault(sheet, []).append((name, x, y, w, h))

        for sheet, rects in by_sheet.items():
            for i, (name_a, xa, ya, wa, ha) in enumerate(rects):
                for name_b, xb, yb, wb, hb in rects[i + 1:]:
                    overlap_x = xa < xb + wb and xb < xa + wa
                    overlap_y = ya < yb + hb and yb < ya + ha
                    assert not (overlap_x and overlap_y), (
                        f"{name_a} and {name_b} overlap in {sheet}")


class TestItemSpriteFallback:
    """With no table entries reachable (either because _ITEM_SPRITE_TABLE is
    empty, or because the sheet can't be loaded), every item name must still
    resolve to a usable, correctly-sized vector-icon surface."""

    @pytest.mark.parametrize("item_type", ALL_ITEM_NAMES)
    def test_every_known_item_name_returns_a_tile_sized_surface(self, item_type):
        h = _headless_harness()
        sprite = h._get_item_sprite(item_type)
        assert isinstance(sprite, pygame.Surface)
        assert sprite.get_size() == (TILE_SIZE, TILE_SIZE)

    def test_unknown_item_type_falls_back_to_the_default_vector_icon(self):
        h = _headless_harness()
        sprite = h._get_item_sprite("some_future_item_type")
        assert isinstance(sprite, pygame.Surface)
        assert sprite.get_size() == (TILE_SIZE, TILE_SIZE)

    def test_fallback_sprites_are_cached_by_identity(self):
        h = _headless_harness()
        first = h._get_item_sprite("sword")
        second = h._get_item_sprite("sword")
        assert first is second


class TestItemSpriteTableHitAndMiss(object):
    """Exercises the sheet-crop path directly by monkeypatching a temporary
    table entry onto a real (tiny, synthetic) sheet, since the shipped table
    is currently empty."""

    def _fake_sheet_dir(self, tmp_path):
        sheet = pygame.Surface((32, 16), pygame.SRCALPHA)
        sheet.fill((10, 20, 30, 255), (0, 0, 16, 16))
        sheet.fill((40, 50, 60, 255), (16, 0, 16, 16))
        path = tmp_path / "fake_items.png"
        pygame.image.save(sheet, str(path))
        return tmp_path

    def test_table_hit_crops_and_caches_the_real_sheet(self, tmp_path, monkeypatch):
        search_dir = self._fake_sheet_dir(tmp_path)
        h = _ItemRenderHarness(SpriteManager(search_paths=[search_dir]))
        monkeypatch.setitem(render_objects._ITEM_SPRITE_TABLE,
                             "greenrupee", ("fake_items.png", 0, 0, 16, 16))

        sprite = h._get_item_sprite("greenrupee")
        assert isinstance(sprite, pygame.Surface)
        assert sprite.get_size() == (TILE_SIZE, TILE_SIZE)
        # Cropped from the first (dark blue-ish) tile, not the vector
        # fallback's colour for greenrupee (60, 220, 90).
        assert sprite.get_at((1, 1))[:3] == (10, 20, 30)

        again = h._get_item_sprite("greenrupee")
        assert again is sprite

    def test_table_entry_with_unloadable_sheet_falls_back_and_logs_once(self, monkeypatch, capsys):
        h = _headless_harness()
        monkeypatch.setitem(render_objects._ITEM_SPRITE_TABLE,
                             "bluerupee", ("does_not_exist.png", 0, 0, 16, 16))

        first = h._get_item_sprite("bluerupee")
        second = h._get_item_sprite("bluerupee")
        assert isinstance(first, pygame.Surface)
        assert first.get_size() == (TILE_SIZE, TILE_SIZE)
        assert first is second  # falls into the same vector-icon cache path

        out = capsys.readouterr().out
        assert out.count("bluerupee") == 1  # logged once, not per-frame


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
