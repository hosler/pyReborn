import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.sprites import (
    SpriteManager, TilesetManager, strip_tiledef_image,
)


def _sheet(color):
    surface = pygame.Surface((2048, 512), pygame.SRCALPHA)
    surface.fill(color)
    return surface


def _tile_id_at(tx, ty):
    block, column = divmod(tx, 16)
    return block * 512 + ty * 16 + column


def _pixel(manager, tx, ty):
    return manager.get_tile(_tile_id_at(tx, ty)).get_at((0, 0))


def test_tiledef_image_is_lowercase_basename():
    assert strip_tiledef_image(r"Levels/Tiles/CUSTOM.PNG") == "custom.png"

    manager = TilesetManager(SpriteManager([]))
    manager.set_full_tiledef("Levels/Tiles/CUSTOM.PNG", "")

    assert manager.full_tiledefs == [("custom.png", "", 0)]


def test_duplicate_paste_definition_is_ignored():
    manager = TilesetManager(SpriteManager([]))

    manager.set_tiledef("CUSTOM.PNG", "Level", 16, 32)
    manager.set_tiledef("custom.png", "level", 16, 32)

    assert manager.tiledefs == [("custom.png", "level", 16, 32)]


def test_full_definition_replaces_same_prefix_paste():
    manager = TilesetManager(SpriteManager([]))
    manager.set_tiledef("paste.png", "level", 16, 32)

    manager.set_full_tiledef("full.png", "level")

    assert manager.tiledefs == []
    assert manager.full_tiledefs == [("full.png", "level", 0)]


def test_longest_prefix_selects_base_sheet():
    sprites = SpriteManager([])
    sprites.sheet_cache["default.png"] = _sheet((10, 20, 30, 255))
    sprites.sheet_cache["specific.png"] = _sheet((40, 50, 60, 255))
    manager = TilesetManager(sprites)
    manager.set_full_tiledef("default.png", "")
    manager.set_full_tiledef("specific.png", "zlttp")
    manager.set_current_level("zlttp_overworld.nw")

    assert _pixel(manager, 0, 0) == (40, 50, 60, 255)


def test_remove_prefix_keeps_unrelated_definition():
    manager = TilesetManager(SpriteManager([]))
    manager.set_full_tiledef("world.png", "zlttp")
    manager.set_tiledef("castle.png", "zlttp_castle", 0, 0)
    manager.set_full_tiledef("church.png", "church")

    assert manager.clear_tiledefs("zlttp") is True
    assert manager.tiledefs == []
    assert manager.full_tiledefs == [("church.png", "church", 0)]


def test_non_aligned_pastes_use_sheet_pixel_offsets_and_level_prefix():
    sprites = SpriteManager([])
    sprites.sheet_cache["dustynewpics1.png"] = _sheet((10, 20, 30, 255))

    first = pygame.Surface((32, 16), pygame.SRCALPHA)
    first.fill((200, 0, 0, 255))
    second = pygame.Surface((16, 32), pygame.SRCALPHA)
    second.fill((0, 200, 0, 255))
    sprites.sheet_cache["first.png"] = first
    sprites.sheet_cache["second.png"] = second

    manager = TilesetManager(sprites)
    manager.set_tiledef("first.png", "species", 1728, 0)
    manager.set_tiledef("second.png", "species", 1536, 80)
    manager.set_current_level("speciesselect.nw")

    assert _pixel(manager, 108, 0) == (200, 0, 0, 255)
    assert _pixel(manager, 109, 0) == (200, 0, 0, 255)
    assert _pixel(manager, 107, 0) == (10, 20, 30, 255)
    assert _pixel(manager, 96, 5) == (0, 200, 0, 255)
    assert _pixel(manager, 96, 6) == (0, 200, 0, 255)
    assert _pixel(manager, 96, 4) == (10, 20, 30, 255)

    manager.set_current_level("unrelated.nw")
    assert _pixel(manager, 108, 0) == (10, 20, 30, 255)
    assert _pixel(manager, 96, 5) == (10, 20, 30, 255)


def test_same_position_paste_replaces_and_alpha_blends_over_base():
    sprites = SpriteManager([])
    sprites.sheet_cache["dustynewpics1.png"] = _sheet((0, 0, 100, 255))

    opaque = pygame.Surface((16, 16), pygame.SRCALPHA)
    opaque.fill((200, 0, 0, 255))
    translucent = pygame.Surface((16, 16), pygame.SRCALPHA)
    translucent.fill((0, 200, 0, 128))
    sprites.sheet_cache["opaque.png"] = opaque
    sprites.sheet_cache["translucent.png"] = translucent

    manager = TilesetManager(sprites)
    manager.set_tiledef("opaque.png", "", 0, 0)
    manager.set_tiledef("translucent.png", "", 0, 0)

    pixel = _pixel(manager, 0, 0)
    assert pixel.r < 110
    assert pixel.g >= 99
    assert pixel.b == 50


def test_aligned_column_pastes_preserve_legacy_layout():
    sprites = SpriteManager([])
    sprites.sheet_cache["dustynewpics1.png"] = _sheet((0, 0, 0, 255))
    manager = TilesetManager(sprites)

    for block in range(8):
        image = f"column{block}.png"
        column = pygame.Surface((256, 512), pygame.SRCALPHA)
        column.fill((block * 20, block * 20 + 1, block * 20 + 2, 255))
        sprites.sheet_cache[image] = column
        manager.set_tiledef(image, "", block * 256, 0)

    for block in range(8):
        assert _pixel(manager, block * 16, 0) == (
            block * 20, block * 20 + 1, block * 20 + 2, 255)
        assert _pixel(manager, block * 16 + 15, 31) == (
            block * 20, block * 20 + 1, block * 20 + 2, 255)
