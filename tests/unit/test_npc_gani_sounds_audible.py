"""An NPC's gani sound must reach the mixer at a real, non-zero volume.

hosler could hear his OWN gani sounds but no NPC's. Two separate defects,
both proven here through the REAL entry point (RenderMixin._update_animations,
game/render.py:158/164) rather than through the parser alone -- a
parse-only test passed while the symptom persisted.

1. The ANI frame grammar. A frame is N sprite lines (1 when SINGLEDIRECTION,
   else 4) followed by a TRAILER of WAIT/PLAYSOUND lines belonging to THAT
   frame -- Preagonal/TilesEditor/src/AniEditor/Ani.cpp:690-728 and the C#
   client's Preagonal.Common/.../Animations/Animation.cs:129-160 agree. The
   parser instead treated PLAYSOUND as applying to the NEXT frame group and
   fed `WAIT n` to the sprite-line path, where it closed the group and threw
   the pending sound away. Effect over the reference content (lttp, bomber,
   GTA, GServer-v2, the engine's own gani set): 728 of ~1500 PLAYSOUNDs
   discarded outright by a trailing WAIT, 422 more attached to a frame group
   after the last one (so never reachable), and every SINGLEDIRECTION file
   (1125 of them) mis-grouped four frames into four directions. Stock
   player ganis (sword.gani/walk.gani) carry no WAIT, so their sound merely
   landed one frame late -- inaudibly wrong. That asymmetry is exactly why
   only the local player seemed to work.

2. PARAMn sound filenames. `PLAYSOUND PARAM1` is the stock "play a sound"
   gani idiom (zlttp_playsound3.gani, sen_piano_note2.gani); nothing
   substituted the caller's setani params or the gani's own DEFAULTPARAMn, so
   the sound manager was handed the literal string "PARAM1".
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.gani import AnimationState, GaniParser
from pyreborn.game.render import RenderMixin
from pyreborn.sounds import SoundManager


# A frame whose trailer is `PLAYSOUND` then `WAIT` -- the shape of
# zlttp_sword.gani and 728 other frames in the reference content.
SOUND_THEN_WAIT = """GANI0001
SPRITE    0         SPRITES    0    0   24   16 shadow

ANI
  0   0   0
  0   0   0
  0   0   0
  0   0   0
PLAYSOUND steps2.wav 1.5 2
WAIT 2

  0   1   0
  0   1   0
  0   1   0
  0   1   0
ANIEND
"""

# A SINGLEDIRECTION gani whose ONLY sound sits in the last frame's trailer,
# named by a PARAMn token with a DEFAULTPARAMn fallback: verbatim structure of
# lttp's zlttp_playsound3.gani, the stock "play this sound" gani.
SINGLE_DIR_PARAM = """GANI0001
SPRITE    0         SPRITES    0    0    2    2 NULL

SETBACKTO sen_null
SINGLEDIRECTION
DEFAULTPARAM1 sword.wav

ANI
   0  12  34
WAIT 2
   0  12  34
PLAYSOUND PARAM1
ANIEND
"""

# The comma-decimal offsets some content is written with ("1,5" for 1.5).
COMMA_DECIMAL = """GANI0001
SPRITE    0         SPRITES    0    0   24   16 shadow

SINGLEDIRECTION

ANI
  0   0   0
PLAYSOUND bomb.wav 1,5 2
ANIEND
"""


class _FakeSound:
    """Stands in for pygame.mixer.Sound; records every volume it is given."""

    def __init__(self):
        self.volumes = []
        self.channel_volumes = []

    def set_volume(self, v):
        self.volumes.append(v)

    def play(self):
        return self

    # play() returns this object as its channel, so the stereo pan lands here.
    def get_volume(self):
        return self.volumes[-1] if self.volumes else 0.0


class _FakeChannelSound(_FakeSound):
    def set_volume(self, *args):
        if len(args) == 2:
            self.channel_volumes.append(args)
        else:
            self.volumes.append(args[0])


class _RecordingSoundManager(SoundManager):
    """A SoundManager whose loads always succeed, recording what was asked
    for and what volume each play ended up at."""

    def __init__(self):
        super().__init__([], enabled=True)
        self.played = []
        self.sounds = {}

    def load(self, name):
        self.played.append(name)
        sound = self.sounds.get(name)
        if sound is None:
            sound = self.sounds[name] = _FakeChannelSound()
        return sound


class _StubPlayer:
    direction = 2
    hearts = 3
    is_sitting = False

    def is_carrying(self):
        return False


class _StubClient:
    def __init__(self):
        self.player = _StubPlayer()
        self.players = {}
        self.npcs = {}
        self.baddies = {}
        self.horses = {}
        self.x = 30.0
        self.y = 30.0

    def set_animation(self, name):
        pass


class _Harness(RenderMixin):
    """Minimal GameClient stand-in exposing the real _update_animations."""

    def __init__(self, ganis):
        self.client = _StubClient()
        self.sound_mgr = _RecordingSoundManager()
        self.gani_parser = GaniParser([])
        for name, content in ganis.items():
            self.gani_parser.put_cache(
                name, self.gani_parser.parse_content(content, name))
        self.player_anim = AnimationState(self.gani_parser)
        self.current_anim_name = "idle"
        self.other_player_anims = {}
        self.other_player_visual = {}
        self.npc_anims = {}
        self.npc_visual = {}
        self.baddy_anims = {}
        self.horse_anims = {}
        self.grab_state = None
        self._grab_direction = 2
        self.is_pushing = False
        self.is_moving = False
        self.is_swimming = False
        self.visual_x = 30.0
        self.visual_y = 30.0

    def _update_sitting_state(self):
        pass

    def add_npc(self, npc_id, gani_name, at, params=None):
        """Mirror what game/render_entities.py does on an NPC's first draw:
        create the AnimationState, set its gani, and record its interpolated
        world position."""
        anim = AnimationState(self.gani_parser)
        anim.set_animation(gani_name, 2, params=params)
        assert anim.gani is not None, gani_name
        self.npc_anims[npc_id] = anim
        self.npc_visual[npc_id] = at
        self.client.npcs[npc_id] = {}
        return anim

    def pump(self, frames=40, dt=0.05):
        for _ in range(frames):
            self._update_animations(dt)


def _volumes_for(mgr, name):
    sound = mgr.sounds.get(name)
    return sound.volumes if sound else []


def test_npc_sound_with_a_wait_trailer_reaches_the_mixer():
    """The primary bug: a WAIT after PLAYSOUND silenced the sound entirely."""
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    h.add_npc(7, "npcwalk", (33.0, 31.0))
    h.pump()

    assert "steps2.wav" in h.sound_mgr.played
    volumes = _volumes_for(h.sound_mgr, "steps2.wav")
    assert volumes, "sound loaded but never played"
    assert all(v > 0.0 for v in volumes), volumes
    # ~5 tiles away (3 of NPC distance plus the sound piece's own 1.5/2 tile
    # offset within the gani) against a 26-tile falloff: clearly audible, not
    # a whisper that would read as "no NPC sounds".
    assert max(volumes) > 0.7, volumes


def test_npc_sound_pan_never_zeroes_both_channels():
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    h.add_npc(7, "npcwalk", (33.0, 31.0))
    h.pump()

    pans = h.sound_mgr.sounds["steps2.wav"].channel_volumes
    assert pans, "positional play never set a stereo pan"
    for left, right in pans:
        assert max(left, right) > 0.0, (left, right)


def test_singledirection_param_sound_resolves_via_defaultparam():
    """`PLAYSOUND PARAM1` + `DEFAULTPARAM1 sword.wav` in the LAST frame of a
    SINGLEDIRECTION gani -- all three of the defects at once."""
    h = _Harness({"zlttp_playsound3": SINGLE_DIR_PARAM})
    h.add_npc(9, "zlttp_playsound3", (30.0, 30.0))
    h.pump()

    assert "sword.wav" in h.sound_mgr.played
    assert "PARAM1" not in h.sound_mgr.played
    assert all(v > 0.0 for v in _volumes_for(h.sound_mgr, "sword.wav"))


def test_setani_params_override_the_gani_default():
    """`setani zlttp_playsound3,zlttp_mallet.wav` must play the caller's file."""
    h = _Harness({"zlttp_playsound3": SINGLE_DIR_PARAM})
    h.add_npc(9, "zlttp_playsound3", (30.0, 30.0),
              params=["zlttp_mallet.wav"])
    h.pump()

    assert "zlttp_mallet.wav" in h.sound_mgr.played
    assert "sword.wav" not in h.sound_mgr.played


def test_comma_joined_gani_name_supplies_params():
    """The wire form is a single `ani,param1` string (NPC GANI prop)."""
    h = _Harness({"zlttp_playsound3": SINGLE_DIR_PARAM})
    h.add_npc(9, "zlttp_playsound3,zlttp_mallet.wav", (30.0, 30.0))
    h.pump()

    assert "zlttp_mallet.wav" in h.sound_mgr.played


def test_repeated_setani_with_new_params_replays_the_sound():
    """A piano key: same gani, different note. The same-name early return in
    set_animation must not swallow the second press."""
    h = _Harness({"zlttp_playsound3": SINGLE_DIR_PARAM})
    anim = h.add_npc(9, "zlttp_playsound3", (30.0, 30.0), params=["a.wav"])
    h.pump(frames=5)
    anim.set_animation("zlttp_playsound3", 2, params=["b.wav"])
    h.pump(frames=5)

    assert "a.wav" in h.sound_mgr.played
    assert "b.wav" in h.sound_mgr.played


def test_other_player_sound_is_positional_and_audible():
    """The other_player path (game/render.py:158) shares _play_entity_sounds."""
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    anim = AnimationState(h.gani_parser)
    anim.set_animation("npcwalk", 2)
    h.other_player_anims[3] = anim
    h.other_player_visual[3] = (35.0, 30.0)
    h.client.players[3] = {}
    h.pump()

    assert all(v > 0.0 for v in _volumes_for(h.sound_mgr, "steps2.wav"))


def test_baddy_sound_is_played_not_discarded():
    """game/render.py's baddy loop threw update()'s return value away, so a
    baddy's walk/hurt sounds (bomywalk*.wav etc.) never played at all."""
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    anim = AnimationState(h.gani_parser)
    anim.set_animation("npcwalk", 2)
    h.baddy_anims[1] = anim
    # Baddy coords are LEVEL-local, and the listener is at world 30,30 in a
    # gmap segment 1 tile right -- the local frames must line up, not the
    # world ones, or a baddy standing next to the player reads as 64 tiles off.
    h.client.baddies[1] = {'x': 31.0, 'y': 30.0}
    h.visual_x = 30.0 + 64
    h.visual_y = 30.0
    h.pump()

    volumes = _volumes_for(h.sound_mgr, "steps2.wav")
    assert volumes, "baddy sound never reached the mixer"
    assert max(volumes) > 0.85, volumes


def test_horse_sound_is_played_not_discarded():
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    anim = AnimationState(h.gani_parser)
    anim.set_animation("npcwalk", 2)
    h.horse_anims[(31.0, 30.0)] = anim
    h.client.horses[(31.0, 30.0)] = {'x': 31.0, 'y': 30.0}
    h.pump()

    assert max(_volumes_for(h.sound_mgr, "steps2.wav")) > 0.85


def test_a_baddy_without_a_position_yet_is_skipped_not_crashed():
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    anim = AnimationState(h.gani_parser)
    anim.set_animation("npcwalk", 2)
    h.baddy_anims[1] = anim
    h.client.baddies[1] = {}
    h.pump(frames=5)

    assert h.sound_mgr.played == []


def test_distant_npc_is_attenuated_but_a_near_one_is_not():
    near = _Harness({"npcwalk": SOUND_THEN_WAIT})
    near.add_npc(1, "npcwalk", (31.0, 30.0))
    near.pump()

    far = _Harness({"npcwalk": SOUND_THEN_WAIT})
    far.add_npc(1, "npcwalk", (30.0 + SoundManager.POSITIONAL_FALLOFF + 5, 30.0))
    far.pump()

    assert max(_volumes_for(near.sound_mgr, "steps2.wav")) > 0.85
    assert not far.sound_mgr.played, "beyond falloff should not even load"


def test_comma_decimal_offsets_do_not_lose_the_sound():
    """Content written in a comma-decimal locale: `PLAYSOUND bomb.wav 1,5 2`.
    float('1,5') raises, and the old handler dropped the whole line."""
    h = _Harness({"boom": COMMA_DECIMAL})
    h.add_npc(4, "boom", (30.0, 30.0))
    h.pump()

    assert "bomb.wav" in h.sound_mgr.played
    frame = h.npc_anims[4].gani.directions[0][0]
    assert frame.sounds == [("bomb.wav", 1.5, 2.0)]


def test_local_player_sound_still_works():
    """Guard the half that was already audible (game/render.py:67-69)."""
    h = _Harness({"npcwalk": SOUND_THEN_WAIT})
    h.player_anim.set_animation("npcwalk", 2)
    h.current_anim_name = "npcwalk"
    h.pump()

    assert all(v > 0.0 for v in _volumes_for(h.sound_mgr, "steps2.wav"))


class TestFrameGrammar:
    """The grammar itself, pinned against the two oracles."""

    def test_trailer_sound_belongs_to_the_frame_it_follows(self):
        parser = GaniParser([])
        gani = parser.parse_content(SOUND_THEN_WAIT, "t")
        for direction in range(4):
            frames = gani.directions[direction]
            assert len(frames) == 2, direction
            assert frames[0].sound == ("steps2.wav", 1.5, 2.0)
            assert frames[1].sound is None

    def test_wait_line_is_not_a_sprite_line(self):
        parser = GaniParser([])
        gani = parser.parse_content(SINGLE_DIR_PARAM, "t")
        assert gani.single_dir is True
        # Two frames, one per sprite line -- not one frame spread over the
        # directions, and not a phantom frame for `WAIT 2`.
        assert len(gani.directions[0]) == 2
        assert gani.directions[1] == []
        assert gani.directions[0][1].sound == ("PARAM1", 0.0, 0.0)

    def test_multiple_playsounds_in_one_frame_are_all_kept(self):
        """sen_piano_note2.gani stacks PARAM1..PARAM12 on a single frame
        (Ani.cpp:721 pushes onto a list)."""
        parser = GaniParser([])
        gani = parser.parse_content("""GANI0001
SPRITE    0         SPRITES    0    0   24   16 shadow

SINGLEDIRECTION

ANI
  0   0   0
PLAYSOUND one.wav 1.5 2
PLAYSOUND two.wav 1.5 2
WAIT 1
ANIEND
""", "t")
        names = [s[0] for s in gani.directions[0][0].sounds]
        assert names == ["one.wav", "two.wav"]


class TestMissingSoundDownload:
    """A server's custom sounds exist nowhere on disk until requested."""

    def test_a_missing_sound_is_requested_once(self):
        mgr = SoundManager([], enabled=True)
        asked = []
        mgr.file_requester = asked.append
        assert mgr.load("eye_minisword.wav") is None
        assert mgr.load("eye_minisword.wav") is None
        assert asked == ["eye_minisword.wav"]

    def test_a_name_written_off_before_the_requester_existed_is_retried(self):
        """preload_common_sounds() runs before the client wires the hook."""
        mgr = SoundManager([], enabled=True)
        assert mgr.load("sen_mallet.wav") is None      # no requester yet
        asked = []
        mgr.file_requester = asked.append
        assert mgr.load("sen_mallet.wav") is None
        assert asked == ["sen_mallet.wav"]

    def test_arriving_bytes_clear_the_failed_record(self):
        mgr = SoundManager([], enabled=True)
        mgr.file_requester = lambda name: None
        assert mgr.load("sen_mallet.wav") is None
        assert "sen_mallet.wav" in mgr._sound_failed
        pytest.importorskip("pygame")
        import pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        mgr._initialized = True
        wav = _silent_wav_bytes()
        assert mgr.load_bytes("sen_mallet.wav", wav) is not None
        assert "sen_mallet.wav" not in mgr._sound_failed
        assert mgr.load("sen_mallet.wav") is not None


def _silent_wav_bytes(frames=256):
    """A minimal valid 8-bit mono WAV."""
    import struct
    data = b"\x80" * frames
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 22050, 22050, 1, 8)
            + b"data" + struct.pack("<I", len(data)) + data)
