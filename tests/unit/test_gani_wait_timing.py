"""WAIT is parsed as metadata but deliberately ignored for frame timing.

The canonical directive chain does not parse WAIT (TGraalAni.cpp:419-442),
and each animation step defaults to one tick (TGraalAniStep.cpp:5). Playback
therefore remains one 0.05-second tick per frame regardless of stored WAIT.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                '../../../reborn-protocol'))

import pytest

from pyreborn.gani import AnimationState, GaniParser


_WAITING = """GANI0001
SPRITE    0         SPRITES    0    0   24   12 shadow

SETBACKTO ce_idle

ANI
   0  12  34
   0  12  36
   0  12  34
   0  12  36
PLAYSOUND sword.wav 1,5 2
WAIT 2

   0  12  34
   0  12  36
   0  12  34
   0  12  36
WAIT 4

   0  12  34
   0  12  36
   0  12  34
   0  12  36
WAIT 1
ANIEND
"""

_LOOPING = _WAITING.replace("SETBACKTO ce_idle", "LOOP\nCONTINUOUS")


def _anim(content, name):
    parser = GaniParser()
    parser.put_cache(name, parser.parse_content(content, name))
    anim = AnimationState(parser)
    anim.set_animation(name, 2)
    return anim


class TestWaitParses:
    def test_wait_is_recorded_per_frame(self):
        gani = GaniParser().parse_content(_WAITING, "waiting")
        assert gani.setback == "ce_idle"
        assert [gani.get_frame(2, i).wait for i in range(3)] == [2.0, 4.0, 1.0]


class TestWaitTiming:
    def test_wait_values_do_not_change_flat_cadence(self):
        anim = _anim(_WAITING, "waiting")
        anim.update(0.049)
        assert anim.frame == 0
        anim.update(0.001)
        assert anim.frame == 1
        anim.update(0.05)
        assert anim.frame == 2
        anim.update(0.05)
        assert anim.is_finished()
        assert anim.get_setback() == "ce_idle"

    @pytest.mark.parametrize(
        "elapsed", [0.0, 0.049, 0.05, 0.099, 0.10, 0.149, 0.15, 0.31]
    )
    @pytest.mark.parametrize("looping", [False, True])
    def test_frame_index_matches_animation_state(self, elapsed, looping):
        content = _LOOPING if looping else _WAITING
        anim = _anim(content, f"waiting-{looping}")
        anim.update(elapsed)
        assert anim.gani.frame_index_at(elapsed, 2) == anim.frame

    def test_frame_index_past_end_loops_or_holds_last(self):
        non_looping = _anim(_WAITING, "waiting").gani
        looping = _anim(_LOOPING, "looping").gani
        assert non_looping.frame_index_at(1.0, 2) == 2
        assert looping.frame_index_at(0.20, 2) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
