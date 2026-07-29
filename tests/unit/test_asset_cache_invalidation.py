import io
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.gani import GaniParser
from pyreborn.game.setup import SetupMixin
from pyreborn.sprites import SpriteManager


def _png_bytes(color):
    surface = pygame.Surface((2, 2), pygame.SRCALPHA)
    surface.fill(color)
    output = io.BytesIO()
    pygame.image.save(surface, output, "asset.png")
    return output.getvalue()


def test_evicted_sheet_is_rehydrated_from_bytes_source():
    data = _png_bytes((12, 34, 56, 255))
    manager = SpriteManager([], fetch_bytes=lambda name: data)
    first = manager.load_bytes("remote.png", data)
    manager.sheet_cache.clear()

    restored = manager.load_sheet("remote.png")

    assert restored is not None
    assert restored is not first
    assert restored.get_at((0, 0)) == (12, 34, 56, 255)


def test_gani_miss_is_cached_and_download_supersedes_it(tmp_path, monkeypatch):
    probes = 0
    original_exists = Path.exists

    def count_exists(path):
        nonlocal probes
        probes += 1
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", count_exists)
    parser = GaniParser([tmp_path])

    assert parser.parse("later") is None
    first_probe_count = probes
    assert parser.parse("later") is None
    assert probes == first_probe_count

    downloaded = parser.parse_content("ANI\nANIEND\n", "later")
    parser.put_cache("later", downloaded)

    assert parser.parse("later") is downloaded


def test_load_bytes_invalidates_derived_sprite_cuts():
    manager = SpriteManager([])
    manager.load_bytes("replace.png", _png_bytes((200, 0, 0, 255)))
    old_cut = manager.get_sprite("replace.png", 0, 0, 1, 1)
    manager._recolor_sheet_cache[("replace.png", (0,))] = old_cut
    manager._recolor_sprite_cache[("replace.png", (0,), 0, 0, 1, 1)] = old_cut

    manager.load_bytes("replace.png", _png_bytes((0, 200, 0, 255)))
    new_cut = manager.get_sprite("replace.png", 0, 0, 1, 1)

    assert new_cut is not old_cut
    assert new_cut.get_at((0, 0)) == (0, 200, 0, 255)
    assert not manager._recolor_sheet_cache
    assert not manager._recolor_sprite_cache


def test_tile_derived_helper_clears_all_four_caches():
    class Harness(SetupMixin):
        pass

    harness = Harness()
    harness.tileset_mgr = SimpleNamespace(
        tile_cache={"tile": object()},
        clear_cache=lambda: harness.tileset_mgr.tile_cache.clear(),
    )
    harness.world_surface = object()
    harness._shimmer_cache = {(1, 1.0): object()}
    harness._chest_sprite_cache = {False: object()}

    harness._invalidate_tile_derived_caches()

    assert harness.tileset_mgr.tile_cache == {}
    assert harness.world_surface is None
    assert harness._shimmer_cache == {}
    assert harness._chest_sprite_cache == {}
