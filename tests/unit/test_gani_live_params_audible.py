"""A live `setani ani,param1` param must reach the sound resolver.

`PLAYSOUND PARAM1` is the stock "play a sound" gani idiom
(zlttp_playsound3.gani, sen_piano_note2.gani): the gani is generic and the
CALLER names the file. AnimationState resolves a PARAMn sound against its own
params (gani.py:559), and the gani's DEFAULTPARAMn already worked -- but the
render path split the params off the comma-joined name for the ATTR layers and
then called set_animation with the bare name, so a live param never arrived and
the resolver fell back to the default (or to nothing).

Driven through the real renderers on a real GameClient, plus the real
RenderMixin._update_animations, because the four call sites that drop the
params are in the renderers -- the same reason the earlier parse-only test
passed while hosler still heard nothing.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn.pygame_game import GameClient
from pyreborn.sounds import SoundManager

pygame.init()
pygame.display.set_mode((64, 64))


# Verbatim structure of lttp's zlttp_playsound3.gani: SINGLEDIRECTION, one
# PLAYSOUND PARAM1 in the last frame's trailer, with a DEFAULTPARAM1 fallback.
PLAYSOUND_PARAM = """GANI0001
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


class _FakeSound:
    """Stands in for pygame.mixer.Sound, recording every volume it is given."""

    def __init__(self):
        self.volumes = []

    def set_volume(self, *args):
        # play() returns self as the channel, so the stereo pan lands here too.
        if len(args) == 1:
            self.volumes.append(args[0])

    def play(self):
        return self


class _RecordingSoundManager(SoundManager):
    """Loads always succeed; records what was asked for and at what volume."""

    def __init__(self):
        super().__init__([], enabled=True)
        self.played = []
        self.sounds = {}

    def load(self, name):
        self.played.append(name)
        sound = self.sounds.get(name)
        if sound is None:
            sound = self.sounds[name] = _FakeSound()
        return sound


@pytest.fixture(scope="module")
def game():
    """A real, fully composed GameClient, offline (never connected)."""
    client = Client('127.0.0.1', 14900, version='6.037')
    g = GameClient(client)
    g.gani_parser.put_cache(
        "zlttp_playsound3",
        g.gani_parser.parse_content(PLAYSOUND_PARAM, "zlttp_playsound3"))
    return g


@pytest.fixture
def sound_mgr(game, monkeypatch):
    mgr = _RecordingSoundManager()
    monkeypatch.setattr(game, 'sound_mgr', mgr)
    return mgr


def _reset_world(game):
    client = game.client
    client.players.clear()
    client.npcs.clear()
    client.baddies.clear()
    client.horses.clear()
    game.npc_anims.clear()
    game.npc_visual.clear()
    game.other_player_anims.clear()
    game.other_player_visual.clear()
    game.camera.set_center(32.0, 32.0)
    game.visual_x = game.visual_y = 32.0
    game._player_render_pos = (32.0, 32.0)


def _pump(game, frames=40, dt=0.05):
    """One render pass per frame, then advance the animations -- the real
    frame order (game/render.py's _render then _update_animations)."""
    for _ in range(frames):
        game._render_entities()
        game._update_animations(dt)


def _volumes(mgr, name):
    sound = mgr.sounds.get(name)
    return sound.volumes if sound else []


class TestNpcParams:
    def test_live_setani_param_names_the_sound(self, game, sound_mgr):
        """The wire form is one comma-joined GANI prop; the split for the ATTR
        layers must not lose it on the way to set_animation."""
        _reset_world(game)
        game.client.npcs[3] = {'x': 32.0, 'y': 32.0,
                               'gani': 'zlttp_playsound3,zlttp_mallet.wav'}
        _pump(game)

        assert "zlttp_mallet.wav" in sound_mgr.played
        assert "PARAM1" not in sound_mgr.played
        assert "sword.wav" not in sound_mgr.played, "fell back to DEFAULTPARAM1"
        volumes = _volumes(sound_mgr, "zlttp_mallet.wav")
        assert volumes and all(v > 0.0 for v in volumes), volumes

    def test_new_params_on_the_same_gani_re_sound(self, game, sound_mgr):
        """A second piano key: same gani name, different note. The renderer
        re-asserts the NPC's gani every frame, so the params are the only
        signal that this is a genuinely new call."""
        _reset_world(game)
        npc = game.client.npcs[3] = {'x': 32.0, 'y': 32.0,
                                     'gani': 'zlttp_playsound3,a.wav'}
        _pump(game, frames=8)
        assert "a.wav" in sound_mgr.played

        npc['gani'] = 'zlttp_playsound3,b.wav'
        _pump(game, frames=8)

        assert "b.wav" in sound_mgr.played
        assert all(v > 0.0 for v in _volumes(sound_mgr, "b.wav"))

    def test_no_params_still_uses_defaultparam(self, game, sound_mgr):
        _reset_world(game)
        game.client.npcs[3] = {'x': 32.0, 'y': 32.0, 'gani': 'zlttp_playsound3'}
        _pump(game)

        assert "sword.wav" in sound_mgr.played
        assert "PARAM1" not in sound_mgr.played


class TestOtherPlayerParams:
    def test_live_setani_param_names_the_sound(self, game, sound_mgr):
        _reset_world(game)
        game.client.players[7] = {'x': 33.0, 'y': 32.0, 'level': '',
                                  'ani': 'zlttp_playsound3,zlttp_mallet.wav'}
        _pump(game)

        assert "zlttp_mallet.wav" in sound_mgr.played
        assert "sword.wav" not in sound_mgr.played, "fell back to DEFAULTPARAM1"
        assert all(v > 0.0 for v in _volumes(sound_mgr, "zlttp_mallet.wav"))

    def test_new_params_on_the_same_gani_re_sound(self, game, sound_mgr):
        """The other-player guard compared name and direction only, so a
        params-only change skipped set_animation entirely."""
        _reset_world(game)
        pdata = game.client.players[7] = {'x': 33.0, 'y': 32.0, 'level': '',
                                          'ani': 'zlttp_playsound3,a.wav'}
        _pump(game, frames=8)
        assert "a.wav" in sound_mgr.played

        pdata['ani'] = 'zlttp_playsound3,b.wav'
        _pump(game, frames=8)

        assert "b.wav" in sound_mgr.played
        assert all(v > 0.0 for v in _volumes(sound_mgr, "b.wav"))

    def test_params_survive_a_direction_change(self, game, sound_mgr):
        """Turning must not reset the params back to the gani default."""
        _reset_world(game)
        pdata = game.client.players[7] = {'x': 33.0, 'y': 32.0, 'level': '',
                                          'direction': 2,
                                          'ani': 'zlttp_playsound3,c.wav'}
        _pump(game, frames=8)
        pdata['direction'] = 3
        _pump(game, frames=8)

        assert "c.wav" in sound_mgr.played
        assert "sword.wav" not in sound_mgr.played
