"""The 2026-07-26 NPC rendering/dialogue cluster (live funtimes/bomber hunts).

1. `setani` from an NPC-bound GS1 script targets the LOCAL PLAYER, never the
   NPC — only `setcharani` is the NPC form. GServer-v2 GS1Commands.cpp and the
   GS2 host already split them this way). The old alias made bomber-classic's
   piano NPC vanish on seating and the seated player never got the playing
   pose.
2. A GS2 NPC's `this.chat = "..."` write must feed the same speech-bubble
   store (setup.py on_say -> npc_chat_texts) the GS1 say/message command
   feeds, or the bubble never renders (bomber v6 Isaac 10333: 'Yes?').
3. `#b` is a line break in sign text. Format_sign_text dropped it while
   packet_codec's parse_say2 translated it, so the sign-popup path leaked the
   raw token.
4. A server-run `showcharacter` streams the literal NPC image "#c#"
   (GS1Commands.cpp:3049 / NPC.h isCharacter). The render path must treat it
   as the character marker, not a sheet filename (three funtimes villagers
   were invisible).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import time
from types import SimpleNamespace

import pytest

from pyreborn import Client
from pyreborn.game.dialogue import format_sign_text
from pyreborn.game.setup import SetupMixin
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2, _NpcThisObject


# -- GS1 setani routing -----------------------------------------------------

class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


class _AnimRecorder:
    def __init__(self):
        self.calls = []

    def set_animation(self, name, direction=None, force=False, params=None):
        self.calls.append((name, direction, tuple(params or ())))


def _gs1_game():
    client = Client("localhost", 14900)
    client._authenticated = True
    client._protocol = _SentRecorder()
    gs1 = ClientGS1(client)
    game = type("_Game", (SetupMixin,), {})()
    game.client = client
    game.gs1 = gs1
    game.player_anim = _AnimRecorder()
    game.current_anim_name = "idle"
    game.npc_chat_texts = {}
    game._setup_gs1_callbacks()
    return client, gs1, game


def test_setani_from_an_npc_script_drives_the_player_not_the_npc():
    client, gs1, game = _gs1_game()
    npc_id = 33
    npc = client.npcs[npc_id] = {"x": 15.0, "y": 40.0, "gani": "sen_piano,"}
    gs1.load_script("npc_33", "if (playertouchsme) { setani sen_piano_idle,; }",
                    npc_id=npc_id, x=15, y=40)
    gs1.trigger_npc_event(npc_id, "playertouchsme")

    # NPC untouched: the piano keeps its own gani (it used to vanish here)
    assert npc["gani"] == "sen_piano,"
    # player got the pose, on the wire and in the local renderer state
    assert client.player.animation == "sen_piano_idle"
    assert game.current_anim_name == "sen_piano_idle"
    assert game.player_anim.calls[-1][0] == "sen_piano_idle"


def test_setcharani_still_targets_the_npc():
    client, gs1, game = _gs1_game()
    npc_id = 7
    npc = client.npcs[npc_id] = {"x": 5.0, "y": 5.0}
    gs1.load_script("npc_7", "if (created) { setcharani itsasign2,; }",
                    npc_id=npc_id, x=5, y=5)
    gs1.trigger_npc_event(npc_id, "created")
    # the raw joined arg (trailing comma and all) is what the store carries;
    # the renderer's _split_npc_gani peels it apart at draw time
    assert npc["gani"] == "itsasign2,"
    assert client.player.animation != "itsasign2"
    assert game.current_anim_name == "idle"


def test_setani_params_reach_the_local_anim():
    """`setani sen_piano_note2,<note>.wav` — the PARAM token names the sound.
    the local mirror must hand the params to set_animation, same as the NPC
    render path does."""
    client, gs1, game = _gs1_game()
    gs1.load_script("npc_9", "if (created) { setani sen_piano_note2,fa.wav; }",
                    npc_id=9, x=1, y=1)
    client.npcs[9] = {"x": 1.0, "y": 1.0}
    gs1.trigger_npc_event(9, "created")
    assert game.player_anim.calls[-1] == ("sen_piano_note2", 2, ("fa.wav",))


# -- GS2 NPC chat -> speech bubble ------------------------------------------

def _npc_client(npcs):
    return SimpleNamespace(
        player=SimpleNamespace(x=30.0, y=30.0, account="me", nickname="Me",
                               id=1, direction=2, gani="idle"),
        players={}, x=30.0, y=30.0, weapons={}, server_name="probe",
        connected=False, _current_level_name="a.nw", npcs=npcs,
        gs2_bytecode={"weapon": {}, "npc": {}, "gani": {}, "class": {}},
        on_gs2_bytecode=None, on_server_text=None, gs2_host=None,
        _in_update=False)


def test_gs2_chat_write_stores_and_feeds_the_bubble():
    rec = {"x": 10.0, "y": 20.0, "image": "isaac.png", "_level": "a.nw"}
    said = []
    client = _npc_client({10333: rec})
    gs1 = SimpleNamespace(on_say=lambda npc_id, text: said.append((npc_id, text)))
    this = _NpcThisObject(ClientGS2(client, gs1=gs1), ("npc", 10333))

    this.set("chat", "Yes?")
    assert rec["message"] == "Yes?"
    assert said == [(10333, "Yes?")]

    # `message` is the same slot; clearing goes through the same callback so
    # the bubble store can drop the entry immediately
    this.set("message", "")
    assert rec["message"] == ""
    assert said[-1] == (10333, "")


def test_gs2_chat_write_resolves_string_keyed_npc_ids():
    """The bubble key must be the client.npcs key the renderer iterates
    with, even when the VM was keyed by the id's string form."""
    rec = {"x": 1.0, "y": 1.0, "_level": "a.nw"}
    said = []
    client = _npc_client({77: rec})
    gs1 = SimpleNamespace(on_say=lambda npc_id, text: said.append((npc_id, text)))
    this = _NpcThisObject(ClientGS2(client, gs1=gs1), ("npc", "77"))
    this.set("chat", "hello")
    assert said == [(77, "hello")]


def test_gs2_chat_write_survives_a_detached_runtime():
    """No gs1 runtime / no live npc record: the write still lands on member
    storage without raising (bytecode can run before the props stream)."""
    client = _npc_client({})
    this = _NpcThisObject(ClientGS2(client), ("npc", 5))
    this.set("chat", "early")  # must not raise
    assert this.get("chat") == "early"


def test_setup_on_say_clears_the_bubble_on_empty_text():
    game = type("_Game", (SetupMixin,), {})()
    game.client = SimpleNamespace(player=SimpleNamespace())
    game.gs1 = ClientGS1(game.client)
    game.player_anim = _AnimRecorder()
    game.npc_chat_texts = {}
    game._setup_gs1_callbacks()

    game.gs1.on_say(4, "hi there")
    assert game.npc_chat_texts[4][0] == "hi there"
    game.gs1.on_say(4, "")
    assert 4 not in game.npc_chat_texts


# -- #b in the sign-popup path ----------------------------------------------

def test_format_sign_text_translates_hash_b_linebreaks():
    assert format_sign_text("line one#bline two") == "line one\nline two"


def test_format_sign_text_hash_b_before_char_escapes():
    # #K(35) emits a literal '#'; a following 'b' is TEXT, not a line break
    assert format_sign_text("#K(35)bomb") == "#bomb"


# -- '#c#' character marker in the render path ------------------------------

@pytest.fixture(scope="module")
def game():
    import pygame
    from pyreborn.pygame_game import GameClient
    pygame.init()
    pygame.display.set_mode((64, 64))
    client = Client('127.0.0.1', 14900, version='6.037')
    return GameClient(client)


def test_character_marker_image_renders_as_character(game):
    """image '#c#' must take the character branch (head/body/colors), not the
    static-sprite branch that tried (and failed forever) to load a sheet
    literally named '#c#'."""
    game.client.npcs.clear()
    game.npc_anims.clear()
    game.camera.set_center(32.0, 32.0)
    loads = []
    orig_load = game.sprite_mgr.load_sheet
    game.sprite_mgr.load_sheet = lambda name: (loads.append(name),
                                               orig_load(name))[1]
    try:
        game.client.npcs[24] = {
            'x': 30.0, 'y': 30.0, 'image': '#c#',
            'headimage': 'head1.png', 'bodyimage': 'body.png',
        }
        game._render_entities()
    finally:
        game.sprite_mgr.load_sheet = orig_load

    # character path: an AnimationState was created (idles by default)...
    assert 24 in game.npc_anims
    # ...and nothing ever tried to load "#c#" as a sheet
    assert '#c#' not in loads
