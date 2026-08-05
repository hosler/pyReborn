"""Descriptor-backed PLAYER state and local display methods."""

from types import SimpleNamespace

from pyreborn.gs2_client import ClientGS2
from pyreborn.packet_codec.common import parse_player_props
from pyreborn.player import Player
from reborn_protocol.props import PLAYER_PROPS, encode_value


class _Pager:
    def __init__(self):
        self.amount = None

    def scroll(self, amount):
        self.amount = amount


def _runtime(player=None):
    client = SimpleNamespace(
        player=player or Player(), players={}, all_players={}, weapons={},
        is_gmap=False, ghost_mode=0, _current_level_name="room.nw")
    runtime = ClientGS2(client)
    return runtime


def test_rating_and_attachnpc_use_descriptor_stream_values():
    payload = b"".join(
        bytes([prop_id + 32]) + encode_value(PLAYER_PROPS[prop_id], value)
        for prop_id, value in ((36, (1725, 83)), (42, (1, 456))))
    props = parse_player_props(payload)
    assert props["rating"] == (1725, 83)
    assert props["attach_npc"] == (1, 456)

    player = Player()
    player.update_from_props(props)
    runtime = _runtime(player)
    assert runtime.player_object.get("rating") == 1725.0
    assert runtime.player_object.get("ratingd") == 83.0


def test_player_read_state_tracks_live_client_state():
    player = Player(animation="jump", status=1, head_image="head17.png")
    player.rating = 1400
    player.rating_deviation = 60
    runtime = _runtime(player)
    game = SimpleNamespace(dialogue_text="reading", dialogue_pager=_Pager())
    runtime.game_shell = game

    surface = runtime.player_object
    assert surface.get("isjumping") == 1.0
    assert surface.get("paused") == 1.0
    assert surface.get("reading") == 1.0
    assert surface.get("headset") == 17.0
    assert surface.get("map") == 0.0
    assert surface.get("isblocking") == 1.0
    assert surface.get("playersindex") == 0.0


def test_player_display_methods_apply_local_effects_only():
    runtime = _runtime()
    game = SimpleNamespace(dialogue_text="page", dialogue_pager=_Pager())
    game._dismiss_dialogue = lambda: setattr(game, "dialogue_text", None)
    runtime.game_shell = game
    player = runtime.player_object

    runtime.host.call_builtin(None, "showemoticon", ["smile"], player)
    assert runtime.client.player.emoticon == "smile"
    runtime.host.call_builtin(None, "hideemoticon", [], player)
    assert runtime.client.player.emoticon == ""
    runtime.host.call_builtin(None, "scrollsign", [3], player)
    assert game.dialogue_pager.amount == 3
    runtime.host.call_builtin(None, "hidesign", [], player)
    assert game.dialogue_text is None


def test_player_flags_are_writable_and_default_false():
    runtime = _runtime()
    player = runtime.player_object
    for key in ("disableapnoheal", "disableapsaint", "disablenpchits"):
        assert player.get(key) == 0.0
        player.set(key, 1)
        assert player.get(key) == 1.0
