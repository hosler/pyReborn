"""Servers ship .wav files whose RIFF fmt tag is MPEG Layer 3 (0x0055).
SDL_mixer's WAV parser rejects them, but decodes the bare data chunk as
a raw MP3 stream — SoundManager._decode unwraps the container."""
import os
import struct

import pygame
import pytest

from pyreborn.sounds import SoundManager

_VENDORED = ("/home/hosler/Projects/opengraal2/Preagonal/"
             "graal-bomber-gs2/world/sounds/eye_go2.wav")


def _mixer():
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        pygame.mixer.init()
    except pygame.error:
        pytest.skip("no audio device")


def _synthetic_mpeg_wav(payload: bytes) -> bytes:
    fmt = struct.pack("<HHIIHH", 0x0055, 2, 24000, 24000, 1, 0)
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", len(payload)) + payload)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def test_vendored_mpeg_wav_decodes():
    _mixer()
    if not os.path.exists(_VENDORED):
        pytest.skip("vendored corpus absent")
    sound = SoundManager._decode(open(_VENDORED, "rb").read())
    assert sound.get_length() > 0.5


def test_synthetic_wrapper_hands_payload_to_the_mp3_decoder():
    _mixer()
    if not os.path.exists(_VENDORED):
        pytest.skip("vendored corpus absent")
    real = open(_VENDORED, "rb").read()
    pos, payload = 12, b""
    while pos + 8 <= len(real):
        cid = real[pos:pos + 4]
        size = int.from_bytes(real[pos + 4:pos + 8], "little")
        if cid == b"data":
            payload = real[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)
    sound = SoundManager._decode(_synthetic_mpeg_wav(payload))
    assert sound.get_length() > 0.5


def test_plain_pcm_wav_still_loads():
    _mixer()
    pcm = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    body = struct.pack("<h", 0) * 800
    data = (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE"
            + b"fmt " + struct.pack("<I", len(pcm)) + pcm
            + b"data" + struct.pack("<I", len(body)) + body)
    assert SoundManager._decode(data).get_length() > 0
