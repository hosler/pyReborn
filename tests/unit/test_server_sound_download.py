"""A server-delivered sound must become playable, not be discarded.

A server's custom sounds exist nowhere on disk until requested: servers
publish them as downloadable files (`file sounds/*.wav` in foldersconfig) and
reference them from ganis/scripts. Measured over the reference content,
bomber-gs2 names 40 distinct sounds with 15 absent locally and GTA names 70
with 41 absent -- so the gap is most of a server's audio, not an edge case.

Both halves were missing:

1. `game/setup.py`'s on_file handled png/gif/bmp/mng, gani and music. WAV
   bytes arrived and fell off the end of the if-chain, so the download was
   thrown away and the sound stayed silent for the whole session.
2. Nothing wired `SoundManager.file_requester`, so a missing sound was never
   asked for in the first place.

Driven through the real callback the packet handler calls
(`client.on_file`, handlers/files.py:77) and a real GameClient, because the
defect was in the wiring, not in either half's own logic.
"""

import os
import struct
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn.game.setup import SAMPLE_EXTS
from pyreborn.pygame_game import GameClient
from pyreborn.sounds import SoundManager

pygame.init()
pygame.display.set_mode((64, 64))


def _silent_wav_bytes(frames=256):
    """A minimal valid 8-bit mono WAV."""
    data = b"\x80" * frames
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 22050, 22050, 1, 8)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture(scope="module")
def game():
    """A real, fully composed GameClient, offline (never connected)."""
    client = Client('127.0.0.1', 14900, version='6.037')
    return GameClient(client)


@pytest.fixture
def requests(game, monkeypatch):
    """Record what the client would ask the server for. request_file returns
    False while offline, which would make _request_asset a no-op."""
    asked = []

    def fake_request_file(filename):
        asked.append(filename)
        return True

    monkeypatch.setattr(game.client, 'request_file', fake_request_file)
    monkeypatch.setattr(game, '_requested_assets', set())
    return asked


class TestRequestingAMissingSound:
    def test_file_requester_is_wired_on_a_real_game_client(self, game):
        assert game.sound_mgr.file_requester is not None

    def test_a_missing_sound_asks_the_server_exactly_once(self, game, requests):
        """Two plays of a sound we do not have -> one PLI_WANTFILE. Repeats
        matter: a footstep/hit sound misses once per step."""
        game.sound_mgr.play("eye_minisword.wav")
        game.sound_mgr.play("eye_minisword.wav")

        assert requests == ["eye_minisword.wav"]


class TestOnFileRouting:
    def test_wav_bytes_reach_the_sound_cache(self, game, monkeypatch):
        seen = []
        real_load_bytes = game.sound_mgr.load_bytes

        def spy(name, data):
            seen.append((name, len(data)))
            return real_load_bytes(name, data)

        monkeypatch.setattr(game.sound_mgr, 'load_bytes', spy)
        wav = _silent_wav_bytes()
        game.client.on_file("gta_engine.wav", wav)

        assert seen == [("gta_engine.wav", len(wav))]

    def test_a_delivered_wav_becomes_playable(self, game):
        """End to end: the miss that requested it wrote the name off, and a
        cached-but-written-off name is still silent. play() returning True is
        the mixer actually being handed the sound at a volume."""
        game.sound_mgr.play("sen_mallet.wav")             # miss -> written off
        assert "sen_mallet.wav" in game.sound_mgr._sound_failed

        game.client.on_file("sen_mallet.wav", _silent_wav_bytes())

        assert game.sound_mgr.load("sen_mallet.wav") is not None
        assert game.sound_mgr.play("sen_mallet.wav") is True

    def test_a_missed_sample_replays_when_downloaded(self, game, monkeypatch):
        played = []
        monkeypatch.setattr(
            game.sound_mgr, 'play',
            lambda name, volume=1.0, pitch=1.0:
            played.append((name, volume, pitch)) or True)
        game.sound_mgr._pending_samples["fresh.wav"] = (
            __import__('time').monotonic(), 'play', (0.4, 1.0))

        game.client.on_file("fresh.wav", _silent_wav_bytes())

        assert played == [("fresh.wav", 0.4, 1.0)]
        assert "fresh.wav" not in game.sound_mgr._pending_samples

    def test_missing_sample_trigger_is_remembered_and_deduped(self, game):
        game.sound_mgr.play("not_here.wav", volume=0.4)
        first = game.sound_mgr._pending_samples["not_here.wav"]
        game.sound_mgr.play("not_here.wav", volume=0.8)

        assert game.sound_mgr._pending_samples["not_here.wav"] == first
        assert first[1:] == ('play', (0.4, 1.0))

    def test_an_expired_sample_is_dropped_without_replay(self, game, monkeypatch):
        played = []
        monkeypatch.setattr(game.sound_mgr, 'play',
                            lambda *args, **kwargs: played.append(args) or True)
        game.sound_mgr._pending_samples["stale.wav"] = (
            __import__('time').monotonic()
            - game.sound_mgr.pending_sample_ttl - 0.1,
            'play', (1.0, 1.0))

        game.client.on_file("stale.wav", _silent_wav_bytes())

        assert played == []
        assert "stale.wav" not in game.sound_mgr._pending_samples

    def test_ogg_still_goes_to_the_music_path(self, game, monkeypatch):
        """The boundary of the MUSIC_EXTS/SAMPLE_EXTS split (sounds.py:285):
        .ogg is a streaming format, so a downloaded track must reach
        mixer.music, not be cached as a one-shot sample."""
        assert 'ogg' not in SAMPLE_EXTS
        assert SoundManager.is_music("radio.ogg")

        music = []
        samples = []
        monkeypatch.setattr(game.sound_mgr, 'play_music',
                            lambda name, data=None, loop=True: music.append(name) or True)
        monkeypatch.setattr(game.sound_mgr, 'load_bytes',
                            lambda name, data: samples.append(name))
        game._pending_music = "radio.ogg"
        game.client.on_file("radio.ogg", b"OggS-not-really")

        assert music == ["radio.ogg"]
        assert samples == []

    def test_an_unrequested_ogg_is_not_cached_as_a_sample(self, game, monkeypatch):
        """Nothing was waiting on it, so it goes nowhere -- and in particular
        not through mixer.Sound, which would mis-handle a stream."""
        samples = []
        monkeypatch.setattr(game.sound_mgr, 'load_bytes',
                            lambda name, data: samples.append(name))
        game._pending_music = None
        game.client.on_file("unwanted.ogg", b"OggS-not-really")

        assert samples == []
        assert "unwanted.ogg" not in game.sound_mgr.sound_cache

    def test_images_and_ganis_still_route_where_they_did(self, game, monkeypatch):
        """The sound branch sits at the end of the same if-chain."""
        samples = []
        monkeypatch.setattr(game.sound_mgr, 'load_bytes',
                            lambda name, data: samples.append(name))
        game.client.on_file("head99.png", b"not-a-png")
        game.client.on_file("walkslow.gani", b"GANI0001\n")

        assert samples == []
        assert game.gani_parser.parse("walkslow") is not None
