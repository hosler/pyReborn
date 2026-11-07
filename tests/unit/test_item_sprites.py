"""Ground-item sprite lookup, fallback, shadow and reference placement."""

from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from pyreborn import ground_items as gi
from pyreborn.classic_sprites import SPRITE_RECTS
from pyreborn.game.constants import TILE_SIZE
from pyreborn.game.frame_context import FrameContext
from pyreborn.game.render_collect import EntityCollectMixin
from pyreborn.game.render_objects import LevelObjectsRenderMixin
from pyreborn.sprites import SpriteManager


class _ItemRenderHarness(LevelObjectsRenderMixin):
    def __init__(self, sprite_mgr):
        self.sprite_mgr = sprite_mgr


@pytest.mark.parametrize('item_type', gi.ITEM_NAMES)
def test_missing_sheet_returns_cached_vector_icon(item_type):
    h = _ItemRenderHarness(SimpleNamespace(get_sprite=Mock(return_value=None)))
    sprite = h._get_item_sprite(item_type)
    assert isinstance(sprite, pygame.Surface)
    assert sprite.get_size() == (TILE_SIZE, TILE_SIZE)
    assert h._get_item_sprite(item_type) is sprite


def test_unknown_item_type_falls_back_without_sprite_lookup():
    h = _ItemRenderHarness(SimpleNamespace(get_sprite=Mock()))
    assert h._get_item_sprite('some_future_item_type').get_size() == (16, 16)
    h.sprite_mgr.get_sprite.assert_not_called()


@pytest.mark.parametrize('index,item_type', list(enumerate(gi.ITEM_NAMES)))
def test_every_item_uses_the_overhead_sprite_crop_at_native_size(tmp_path, index, item_type):
    # putExtra maps itemIndex to giveitems: TServerLevel.cpp:1341-1347.
    # Both tables: Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1197-1217.
    rect = SPRITE_RECTS[gi.GIVE_SPRITES[index]]
    sheet = pygame.Surface((128, 1024), pygame.SRCALPHA)
    sheet.fill((10, 20, 30, 255), rect)
    pygame.image.save(sheet, str(tmp_path / 'sprites.png'))
    h = _ItemRenderHarness(SpriteManager(search_paths=[tmp_path]))
    sprite = h._get_item_sprite(item_type)
    assert sprite.get_size() == rect[2:]
    assert sprite.get_at((0, 0)) == (10, 20, 30, 255)
    assert h._get_item_sprite(item_type) is sprite


def test_sheet_arriving_after_fallback_replaces_the_vector_icon():
    h = _ItemRenderHarness(SimpleNamespace(get_sprite=Mock(return_value=None)))
    fallback = h._get_item_sprite('greenrupee')
    real = pygame.Surface((16, 32), pygame.SRCALPHA)
    h.sprite_mgr.get_sprite.return_value = real
    assert h._get_item_sprite('greenrupee') is real
    assert real is not fallback
    h.sprite_mgr.get_sprite.assert_called_with('sprites.png', 0, 144, 16, 32)


class _ItemScene(LevelObjectsRenderMixin, EntityCollectMixin):
    def __init__(self, item_type, time_left, zoom=1.0):
        self.client = SimpleNamespace(items_in_level=lambda _: {(10.0, 20.0): item_type})
        self._current_segment_info = lambda: ('a.nw', 64, 64)
        # Half a tick avoids floating point boundaries in item_time().
        self._item_first_seen = {
            ('a.nw', (10.0, 20.0)): 100.0 - (164 - time_left + 0.5) * gi.TICK}
        self.camera = SimpleNamespace(zoom=zoom)
        self.screen = Mock()
        self.sprite_mgr = SimpleNamespace(get_sprite=Mock(side_effect=self._crop))
        self.sprites = {}

    def _crop(self, sheet, x, y, w, h):
        self.sprites[(x, y, w, h)] = pygame.Surface((w, h), pygame.SRCALPHA)
        return self.sprites[(x, y, w, h)]

    def _world_to_screen(self, x, y):
        return x * TILE_SIZE * self.camera.zoom, y * TILE_SIZE * self.camera.zoom

    def collect(self):
        out = []
        self._collect_items(out, FrameContext(screen_size=(3000, 3000)))
        return out


@pytest.mark.parametrize('item_type,size', [('greenrupee', (16, 32)),
                                           ('bombs', (28, 32)),
                                           ('heart', (16, 16))])
def test_reference_sprite_and_shadow_positions_and_order(monkeypatch, item_type, size):
    monkeypatch.setattr('pyreborn.game.render_collect.time.monotonic', lambda: 100.0)
    h = _ItemScene(item_type, time_left=100)
    ent, = h.collect()
    # World item anchor (74,84), yBase=85, native dimensions in pixels:
    # Preagonal/FourPlay/quattroplay/src/TServerExtra.cpp:41-74.
    assert (ent.x, ent.y) == (75 * 16 - size[0] / 2, 85 * 16 - size[1] / 2)
    assert ent.depth == 86  # TServerExtra.cpp:20-28, independent of dimensions.
    h._draw_item_entity(ent, FrameContext())
    shadow, icon = h.screen.blit.call_args_list
    assert shadow.args[0].get_size() == (16, 8)
    assert shadow.args[1] == (1192, int(85 * 16 + size[1] / 2 - 8))
    assert icon.args[0].get_size() == size
    assert icon.args[1] == (int(ent.x), int(ent.y))
    assert h.sprite_mgr.get_sprite.call_args_list[0].args == ('sprites.png', 24, 0, 16, 8)


def test_bob_moves_only_item_and_keeps_shadow_and_depth_fixed(monkeypatch):
    monkeypatch.setattr('pyreborn.game.render_collect.time.monotonic', lambda: 100.0)
    fresh = _ItemScene('greenrupee', time_left=164)
    settled = _ItemScene('greenrupee', time_left=100)
    a, = fresh.collect()
    b, = settled.collect()
    assert a.y < b.y
    assert a.x == b.x
    assert a.depth == b.depth == 86
    assert a.data[2:] == b.data[2:]


@pytest.mark.parametrize('time_left,visible', [(35, False), (34, True), (-1, False)])
def test_blink_and_expiry_hide_both_sprite_and_shadow(monkeypatch, time_left, visible):
    monkeypatch.setattr('pyreborn.game.render_collect.time.monotonic', lambda: 100.0)
    h = _ItemScene('greenrupee', time_left)
    entities = h.collect()
    for ent in entities:
        h._draw_item_entity(ent, FrameContext())
    assert h.screen.blit.call_count == (2 if visible else 0)


def test_item_and_shadow_scale_with_camera_zoom(monkeypatch):
    monkeypatch.setattr('pyreborn.game.render_collect.time.monotonic', lambda: 100.0)
    h = _ItemScene('greenrupee', time_left=100, zoom=2.0)
    ent, = h.collect()
    h._draw_item_entity(ent, FrameContext())
    shadow, icon = h.screen.blit.call_args_list
    assert shadow.args[0].get_size() == (32, 16)
    assert icon.args[0].get_size() == (32, 64)
    assert shadow.args[1] == (2384, 2736)
    assert icon.args[1] == (2384, 2688)


def test_shadow_stays_visible_when_bobbing_icon_is_off_screen(monkeypatch):
    monkeypatch.setattr('pyreborn.game.render_collect.time.monotonic', lambda: 100.0)
    h = _ItemScene('greenrupee', time_left=164)
    # Put the item entirely above the viewport but keep its shadow visible.
    h._world_to_screen = lambda x, y: (50, -100 if y < 85 else 10)
    ent, = h.collect()
    h._draw_item_entity(ent, FrameContext())
    assert h.screen.blit.call_count == 2
