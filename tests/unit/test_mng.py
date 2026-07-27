import io
from pathlib import Path
import struct
import zlib

import pygame

from pyreborn.mng import decode_mng
from pyreborn.sprites import SpriteManager


_REAL_LAMP = (
    Path(__file__).parents[2]
    / "examples/games/reborn_modern/assets/levels/images/bluelampani.mng"
)


def _chunk(kind, payload=b""):
    return (
        struct.pack(">I", len(payload)) + kind + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png_chunks(color):
    surface = pygame.Surface((2, 1), pygame.SRCALPHA)
    surface.fill(color)
    stream = io.BytesIO()
    pygame.image.save(surface, stream, "frame.png")
    data = stream.getvalue()
    chunks = []
    pos = 8
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        end = pos + 12 + length
        chunks.append(data[pos:end])
        pos = end
    return b"".join(chunks)


def _mng():
    mhdr = struct.pack(">7I", 2, 1, 100, 2, 2, 0, 1)
    fram_red = b"\x01\0\x01\x00\x00\x00" + struct.pack(">I", 10)
    fram_blue = b"\x01\0\x01\x00\x00\x00" + struct.pack(">I", 30)
    return (
        b"\x8aMNG\r\n\x1a\n" + _chunk(b"MHDR", mhdr)
        + _chunk(b"FRAM", fram_red) + _png_chunks((255, 0, 0, 255))
        + _chunk(b"FRAM", fram_blue) + _png_chunks((0, 0, 255, 255))
        + _chunk(b"MEND")
    )


def test_decode_two_full_png_frames():
    animation = decode_mng(_mng())
    assert (animation.width, animation.height) == (2, 1)
    assert len(animation.frames) == 2
    assert animation.frame_delays == (0.1, 0.3)
    assert animation.frames[0].get_at((0, 0))[:3] == (255, 0, 0)
    assert animation.frames[1].get_at((0, 0))[:3] == (0, 0, 255)


def test_decode_repository_lamp_sample():
    animation = decode_mng(_REAL_LAMP.read_bytes())
    assert (animation.width, animation.height) == (32, 64)
    assert animation.ticks_per_second == 1000
    assert len(animation.frames) == 3
    assert animation.frame_delays == (0.1, 0.001, 0.001)
    assert not animation.used_static_fallback


def test_object_features_fall_back_to_first_frame():
    data = _mng().replace(_chunk(b"FRAM", b"\x01\0\x01\x00\x00\x00" + struct.pack(">I", 30)),
                          _chunk(b"DEFI", b"\0\1") + _chunk(b"FRAM", b"\x01\0\x01\x00\x00\x00" + struct.pack(">I", 30)))
    animation = decode_mng(data)
    assert animation.used_static_fallback
    assert len(animation.frames) == 1


def test_sprite_manager_exposes_animation_and_static_frame(monkeypatch):
    manager = SpriteManager([])
    first = manager.load_bytes("lamp.mng", _mng())
    animation = manager.get_animation("lamp.mng")
    assert animation is not None and len(animation.frames) == 2
    assert first is manager.get_static_sheet("lamp.mng")
    assert first.get_at((0, 0))[:3] == (255, 0, 0)

    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 150)
    assert manager.load_sheet("lamp.mng").get_at((0, 0))[:3] == (0, 0, 255)
