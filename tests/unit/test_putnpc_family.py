"""Client-local scripted-NPC family: putnpc / putcomp / putnewcomp /
removecompus / putleaps / attachplayertoobj / detachplayer, plus `say <n>`
showing LEVEL SIGN n.

Oracle notes (grep-verified):
- putnpc is a WIRE command on the classic client: PLI_PUTNPC carries
  image/scriptfile/x/y and the SERVER instantiates the NPC from its own copy
  of the script file, then streams it back to the whole level (GServer-v2
  PlayerClientPackets.cpp:753-780 msgPLI_PUTNPC). The client must not spawn a
  local copy - the echo would double it. GTA guards every call with
  `if (testnpc(x,y)<0) putnpc ...` for exactly this persistence.
- putcomp/putnewcomp are PLI_BADDYADD (PlayerClientPackets.cpp:544-575);
  type/power/image defaults from LevelBaddy.h:26-47 + LevelBaddy.cpp:29-40.
- putleaps/attachplayertoobj/detachplayer are client-local
  (Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:3185-3211, 3579-3597;
  TServerLeap.cpp:11-131; TServerPlayer.cpp:509-581).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.packets import (
    PacketID, build_putnpc, build_baddy_add, build_baddy_props)
from reborn_protocol import BDPROP, BDMODE


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    return c


def _npc_gs1(client, npc_id, script, x=30.0, y=30.0):
    client.npcs.setdefault(npc_id, {"x": x, "y": y, "script": script})
    gs1 = ClientGS1(client)
    gs1.load_script(f"npc_{npc_id}", script, npc_id=npc_id, x=x, y=y)
    return gs1


def _sent(client, pli):
    return [d for (pid, d) in client._protocol.sent if pid == int(pli)]


# -- wire builders ----------------------------------------------------------

def test_build_putnpc_wire_bytes():
    # {GUChar len}{image}{GUChar len}{script}{GUChar x*2}{GUChar y*2}
    data = build_putnpc("barrel.png", "throw.txt", 18, 17)
    assert data == (bytes([10 + 32]) + b"barrel.png"
                    + bytes([9 + 32]) + b"throw.txt"
                    + bytes([36 + 32, 34 + 32]))


def test_build_baddy_add_wire_bytes():
    # {GUChar x*2}{GUChar y*2}{GUChar type}{GUChar power}{image, no prefix}
    data = build_baddy_add(20.5, 8, 3, 5, "baddyninja.png")
    assert data == bytes([41 + 32, 16 + 32, 3 + 32, 5 + 32]) + b"baddyninja.png"


def test_build_baddy_add_clamps_power_like_server():
    data = build_baddy_add(1, 1, 0, 99, "")
    assert data[3] == 12 + 32   # server hard-limits to 6 hearts


# -- putnpc -----------------------------------------------------------------

def test_putnpc_sends_wire_packet_and_spawns_nothing_locally():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (playerenters) { putnpc barrel.png,throw.txt,18,17; }")
    before = dict(client.npcs)
    gs1.trigger_npc_event(5, "playerenters")
    assert _sent(client, PacketID.PLI_PUTNPC) == [
        build_putnpc("barrel.png", "throw.txt", 18, 17)]
    # No local ghost: the server echo IS the NPC (and joins blocking/touch
    # through the normal client.npcs path when it arrives).
    assert client.npcs == before


def test_putnpc_takes_expression_coordinates():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (playerenters) { putnpc a.png,b.txt,x+2,y-1; }",
                   x=10.0, y=9.0)
    gs1.trigger_npc_event(5, "playerenters")
    assert _sent(client, PacketID.PLI_PUTNPC) == [
        build_putnpc("a.png", "b.txt", 12.0, 8.0)]


# -- putcomp / putnewcomp / removecompus ------------------------------------

def test_putcomp_uses_reference_default_power_and_image():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (playerenters) { putcomp shootingsoldier,44,44; }")
    gs1.trigger_npc_event(5, "playerenters")
    # shootingsoldier = type 3, default power 3, default image baddyblue.png
    # (LevelBaddy.cpp:29-40).
    assert _sent(client, PacketID.PLI_BADDYADD) == [
        build_baddy_add(44, 44, 3, 3, "baddyblue.png")]


def test_putnewcomp_overrides_image_and_power():
    client = _fake_connected_client()
    gs1 = _npc_gs1(
        client, 5,
        "if (playerenters) { putnewcomp redsoldier,18,44,baddyninja.png,5; }")
    gs1.trigger_npc_event(5, "playerenters")
    assert _sent(client, PacketID.PLI_BADDYADD) == [
        build_baddy_add(18, 44, 2, 5, "baddyninja.png")]


def test_baddy_name_resolution_spider_alias_and_numeric():
    from pyreborn.gs1_client import _baddy_type_from_name
    assert _baddy_type_from_name("spider") == 6      # aliased to octopus
    assert _baddy_type_from_name("OCTOPUS") == 6     # case-insensitive
    assert _baddy_type_from_name("9") == 9
    assert _baddy_type_from_name("frog") == 5
    assert _baddy_type_from_name("nosuch") == 0      # falls back gray


def test_removecompus_marks_dead_and_broadcasts_mode():
    client = _fake_connected_client()
    client.baddies[1] = {"x": 5, "y": 5, "power": 2, "mode": 0}
    client.baddies[3] = {"x": 9, "y": 9, "power": 4, "mode": 2}
    gs1 = _npc_gs1(client, 5, "if (playerenters) { removecompus; }")
    gs1.trigger_npc_event(5, "playerenters")
    assert client.baddies[1]["mode"] == int(BDMODE.DEAD)
    assert client.baddies[3]["mode"] == int(BDMODE.DEAD)
    sent = _sent(client, PacketID.PLI_BADDYPROPS)
    assert sorted(sent) == sorted([
        build_baddy_props(1, {BDPROP.MODE: int(BDMODE.DEAD)}),
        build_baddy_props(3, {BDPROP.MODE: int(BDMODE.DEAD)}),
    ])


# -- putleaps ---------------------------------------------------------------

def test_putleaps_fires_callback_and_rejects_bad_type():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, (
        "if (playerenters) { putleaps 3,10.5,12; putleaps 6,1,1; }"))
    seen = []
    gs1.on_putleaps = lambda t, x, y: seen.append((t, x, y))
    gs1.trigger_npc_event(5, "playerenters")
    # type >= 6 is rejected (TInitStatics.cpp:3581-3582)
    assert seen == [(3, 10.5, 12.0)]


def test_leap_frame_tables_are_consistent():
    from pyreborn.game.render_effects import EffectsRenderMixin as E
    # reference frame counts: leapslen = {7, 4, 4, 4, 4, 8}
    assert [len(t) for t in E._LEAP_FRAMES] == [7, 4, 4, 4, 4, 8]
    for leap_type, frames in enumerate(E._LEAP_FRAMES):
        for frame in frames:
            assert 1 <= len(frame) <= 4
            for sprite, dx, dy in frame:
                assert sprite in E._LEAP_SPRITE_RECTS, (leap_type, sprite)
                assert -128 <= dx <= 127 and -128 <= dy <= 127
    for rect in E._LEAP_SPRITE_RECTS.values():
        x, y, w, h = rect
        assert w > 0 and h > 0


# -- attachplayertoobj / detachplayer ---------------------------------------

def _attach_setup(npc_x=10.0, npc_y=5.0, player_x=12.0, player_y=6.0):
    client = _fake_connected_client()
    client.player.x, client.player.y = player_x, player_y
    gs1 = _npc_gs1(client, 9, "if (playerenters) { attachplayertoobj 0,9; }",
                   x=npc_x, y=npc_y)
    gs1.trigger_npc_event(9, "playerenters")
    return client, gs1


def test_attach_follows_npc_movement_with_offset_preserved():
    client, gs1 = _attach_setup()
    assert gs1._player_attach == {"npc_id": 9, "last_x": 10.0, "last_y": 5.0}
    client.npcs[9]["x"], client.npcs[9]["y"] = 11.0, 5.5
    gs1.process_timeouts(0.05)
    assert (client.player.x, client.player.y) == (13.0, 6.5)
    # the slaved move is announced like any move
    assert client._protocol.sent, "attach follow should send a position"


def test_attach_keeps_player_relative_after_own_movement():
    client, gs1 = _attach_setup()
    client.player.x = 14.0          # player walks around on the ride
    client.npcs[9]["x"] = 12.0      # NPC moves +2
    gs1.process_timeouts(0.05)
    assert client.player.x == 16.0  # own offset change preserved


def test_attach_is_noop_for_non_npc_objecttype_and_unknown_id():
    client = _fake_connected_client()
    client.player.x = client.player.y = 1.0
    gs1 = _npc_gs1(client, 9, (
        "if (playerenters) { attachplayertoobj 1,9; attachplayertoobj 0,77; }"))
    gs1.trigger_npc_event(9, "playerenters")
    assert gs1._player_attach is None


def test_detachplayer_stops_following():
    client, gs1 = _attach_setup()
    gs1.load_script("npc_9b", "if (timeout2) { detachplayer; }", npc_id=9)
    gs1.trigger_event("timeout2", name="npc_9b")
    assert gs1._player_attach is None
    client.npcs[9]["x"] = 20.0
    gs1.process_timeouts(0.05)
    assert client.player.x == 12.0


def test_attach_self_detaches_when_npc_despawns():
    client, gs1 = _attach_setup()
    del client.npcs[9]
    gs1.process_timeouts(0.05)
    assert gs1._player_attach is None


def test_attach_cleared_on_level_change():
    client, gs1 = _attach_setup()
    gs1.clear()                     # level-change engine reload path
    assert gs1._player_attach is None


# -- say <n> ----------------------------------------------------------------

def _sign_client():
    client = _fake_connected_client()
    client._current_level_name = "adventurerpub.nw"
    client.signs["adventurerpub.nw"] = {
        (10, 10): "Welcome to the pub!",
        (20, 10): "No brawling.#bEver.",
    }
    client.sign_lists["adventurerpub.nw"] = [
        (10, 10, "Welcome to the pub!"),
        (20, 10, "No brawling.#bEver."),
    ]
    return client


def test_say_numeric_shows_sign_text_via_dialogue_path():
    client = _sign_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { say 1; }")
    shown = []
    gs1.on_say2 = shown.append
    bubbled = []
    gs1.on_say = lambda npc_id, text: bubbled.append(text)
    gs1.trigger_npc_event(5, "playertouchsme")
    # sign index 1 in arrival order; escapes are the dialogue layer's job
    # (on_say2 -> _show_dialogue(classic_font=True) -> format_sign_text)
    assert shown == ["No brawling.#bEver."]
    assert bubbled == []                      # never the literal index
    assert "message" not in client.npcs[5]


def test_say_out_of_range_sign_shows_nothing():
    client = _sign_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { say 7; }")
    shown, bubbled = [], []
    gs1.on_say2 = shown.append
    gs1.on_say = lambda npc_id, text: bubbled.append(text)
    gs1.trigger_npc_event(5, "playertouchsme")
    assert shown == [] and bubbled == []


def test_message_still_sets_the_chat_bubble():
    client = _sign_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { message Hi there; }")
    bubbled = []
    gs1.on_say = lambda npc_id, text: bubbled.append(text)
    gs1.trigger_npc_event(5, "playertouchsme")
    assert bubbled == ["Hi there"]
    assert client.npcs[5]["message"] == "Hi there"


def test_sign_lookup_ignores_other_levels():
    client = _sign_client()
    client.signs["elsewhere.nw"] = {(1, 1): "wrong level"}
    gs1 = ClientGS1(client)
    assert gs1.sign_text_by_index(0) == "Welcome to the pub!"
    assert gs1.sign_text_by_index("1") == "No brawling.#bEver."
    assert gs1.sign_text_by_index("bogus") is None


def test_sign_index_survives_stacked_say_only_signs():
    """The live-GTA failure this feature shipped with: say-only signs are all
    parked at "SIGN 0 0" (abermose7.nw stacks five), so the (x,y)-keyed
    client.signs dict collapses them to ONE entry and index addressing dies.
    The ordered client.sign_lists is authoritative."""
    client = _fake_connected_client()
    client._current_level_name = "abermose7.nw"
    texts = ["range rules", "master of bow", "earmuffs offer", "thank you",
             "I see, you have earmuffs\ntoo!\n"]
    client.sign_lists["abermose7.nw"] = [(0, 0, t) for t in texts]
    client.signs["abermose7.nw"] = {(0, 0): texts[-1]}   # what the dict keeps
    gs1 = ClientGS1(client)
    assert gs1.sign_text_by_index(4) == texts[4]
    assert gs1.sign_text_by_index(0) == texts[0]
    assert gs1.sign_text_by_index(5) is None


def test_sign_handler_builds_ordered_list_and_board_restream_resets_it():
    from pyreborn.handlers.level import handle_level_sign, handle_board_packet
    client = _fake_connected_client()
    client._pending_level_name = "abermose7.nw"
    # PLO_LEVELSIGN wire: gchar x, gchar y, encoded text ('A' is itself in
    # the sign alphabet region? use decode via real builder is overkill -
    # feed two signs at the same coords and just assert ordering/reset)
    from pyreborn.packet_codec.level import parse_level_sign  # noqa: F401
    for text in (b"a", b"b"):
        handle_level_sign(client, bytes([0 + 32, 0 + 32]) + text)
    lst = client.sign_lists["abermose7.nw"]
    assert len(lst) == 2                     # dict would have collapsed these
    assert len(client.signs["abermose7.nw"]) == 1
    # a re-streamed board restarts the list (pygserver re-sends static data)
    handle_board_packet(client, bytes(8192))
    assert "abermose7.nw" not in client.sign_lists
    handle_level_sign(client, bytes([0 + 32, 0 + 32]) + b"a")
    assert len(client.sign_lists["abermose7.nw"]) == 1
