"""PLAYSOUND's two numbers are a POSITION, not volume and pitch.

The ani editor writes them as `xoffset / 16.0` and `yoffset / 16.0`
(Preagonal/TilesEditor/src/AniEditor/Ani.cpp:911) and reads them back with
`* 16` (:717-718). Reading them as (volume, pitch) silenced every sound whose
x offset was negative -- which is common in weapon/NPC ganis -- while the
local player's own ganis happened to carry positive offsets that clamped to
full volume, so only OTHER entities went quiet.
"""

import pygame
import pytest

from pyreborn.gani import GaniParser
from pyreborn.sounds import SoundManager


def _frames_with_sound(text):
    parser = GaniParser([])
    anim = parser.parse_content(text, "t.gani")
    frames = anim.directions[0] if anim and anim.directions else []
    return [f.sound for f in frames if f.sound]


_GANI = """ANI
PLAYSOUND {line}
0 0 0
ANIEND
"""


def test_offsets_are_parsed_as_position_not_volume():
    sounds = _frames_with_sound(_GANI.format(line="bomb.wav 1.5 2"))
    assert sounds == [("bomb.wav", 1.5, 2.0)]


def test_negative_offset_survives_parsing():
    """The case that went silent: a negative x read as a volume is < 0."""
    sounds = _frames_with_sound(_GANI.format(line="shot.wav -0.6875 1.3125"))
    assert sounds == [("shot.wav", -0.6875, 1.3125)]
    assert sounds[0][1] < 0


def test_bare_playsound_is_kept_not_dropped():
    """`PLAYSOUND PARAM1` with no offsets is common in weapon ganis; the old
    `len(parts) >= 4` guard discarded it outright."""
    sounds = _frames_with_sound(_GANI.format(line="PARAM1"))
    assert sounds == [("PARAM1", 0.0, 0.0)]


def test_negative_offset_does_not_produce_a_negative_volume():
    """Regression: the emitted volume must stay in [0, 1] regardless of sign."""
    mgr = SoundManager([])
    seen = []

    class _FakeSound:
        def set_volume(self, v):
            seen.append(v)

        def play(self):
            return None

    mgr.enabled = True
    mgr.load = lambda name: _FakeSound()
    assert mgr.play_positional(("shot.wav", -0.6875, 1.3125), 0.0, 0.0) is True
    assert seen and all(0.0 <= v <= 1.0 for v in seen), seen
