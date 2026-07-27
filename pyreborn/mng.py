"""Small MNG-LC reader for animations made of complete embedded PNG images."""

from dataclasses import dataclass
import io
import struct
from typing import Tuple

import pygame


MNG_SIGNATURE = b"\x8aMNG\r\n\x1a\n"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_OBJECT_CHUNKS = {
    b"CLON", b"DEFI", b"DHDR", b"DISC", b"MOVE", b"PAST",
}


class MNGError(ValueError):
    """Raised when an input is not a usable MNG stream."""


@dataclass(frozen=True)
class MNGAnimation:
    """Decoded complete frames and their display times in seconds."""

    width: int
    height: int
    ticks_per_second: int
    frames: Tuple[pygame.Surface, ...]
    frame_delays: Tuple[float, ...]
    used_static_fallback: bool = False


def _chunks(data: bytes):
    if not data.startswith(MNG_SIGNATURE):
        raise MNGError("invalid MNG signature")
    offset = len(MNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise MNGError("truncated MNG chunk")
        chunk_type = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        raw = data[offset: end]
        yield chunk_type, payload, raw
        offset = end
        if chunk_type == b"MEND":
            return
    raise MNGError("MNG stream has no MEND chunk")


def _fram_delay(payload: bytes):
    """Return a changed interframe delay, or None when FRAM keeps the old one."""
    if not payload:
        return None
    pos = 1  # framing mode
    if pos < len(payload):
        nul = payload.find(b"\0", pos)
        if nul < 0:
            return None
        pos = nul + 1
    if pos + 4 > len(payload):
        return None
    change_delay = payload[pos]
    pos += 4  # delay, timeout, clipping, sync-id change flags
    if change_delay and pos + 4 <= len(payload):
        return struct.unpack_from(">I", payload, pos)[0]
    return None


def decode_mng(data: bytes) -> MNGAnimation:
    """Decode full-frame PNG objects from a simple MNG-LC byte stream.

    Object manipulation and delta-image chunks deliberately degrade to the
    first decodable PNG frame, since compositing those objects incorrectly is
    worse than displaying a stable image.
    """
    width = height = ticks_per_second = None
    png_parts = None
    frames = []
    delays_ticks = []
    current_delay = 1
    unsupported_objects = False

    for chunk_type, payload, raw in _chunks(data):
        if chunk_type == b"MHDR":
            if len(payload) != 28:
                raise MNGError("invalid MHDR length")
            width, height, ticks_per_second = struct.unpack_from(">III", payload)
            if width <= 0 or height <= 0:
                raise MNGError("invalid MNG dimensions")
        elif chunk_type == b"FRAM":
            changed = _fram_delay(payload)
            if changed is not None:
                current_delay = changed
        elif chunk_type in _OBJECT_CHUNKS:
            unsupported_objects = True
        elif chunk_type == b"IHDR":
            png_parts = [PNG_SIGNATURE, raw]
        elif png_parts is not None:
            png_parts.append(raw)
            if chunk_type == b"IEND":
                try:
                    surface = pygame.image.load(io.BytesIO(b"".join(png_parts)))
                except pygame.error:
                    png_parts = None
                    continue
                frames.append(surface)
                delays_ticks.append(current_delay)
                png_parts = None

    if width is None or ticks_per_second is None:
        raise MNGError("MNG stream has no valid MHDR")
    if not frames:
        raise MNGError("MNG stream has no decodable PNG frame")

    fallback = unsupported_objects
    if fallback:
        frames = frames[:1]
        delays_ticks = delays_ticks[:1]
    rate = ticks_per_second or 1000
    delays = tuple(max(1.0 / rate, ticks / rate) for ticks in delays_ticks)
    return MNGAnimation(
        width, height, ticks_per_second, tuple(frames), delays, fallback,
    )
