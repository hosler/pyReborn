"""A requested warp on the original-client flow is confirmed by its PLAYERWARP.

The original flow (login type PLTYPE_CLIENT: 1.411, 2.17) sends PLO_LEVELNAME
only for the first level (GServer-v2 server/src/player/PlayerClientOriginal.cpp:158-160),
so the warp packet is the only confirmation of a warp the client requested.
"""
from pyreborn import Client
from pyreborn.packets import PacketID


def _g(*values):
    return bytes(32 + v for v in values)


def _warp(level):
    return _g(20, 20) + level.encode()


class _Stub:
    connected = True

    def send_packet(self, packet_id, data):
        return True


def _client():
    client = Client("localhost", 14900, version="2.17")
    client._protocol = _Stub()
    client._authenticated = True
    client._handle_packet(PacketID.PLO_LEVELNAME, b"a.nw")
    client._current_level_name = "a.nw"
    client.player.level = "a.nw"
    client.player.x, client.player.y = 30.0, 30.0
    client.tiles = [1] * 4096
    client.levels["a.nw"] = client.tiles
    client._tiles_level_name = "a.nw"
    return client


def test_the_warp_names_the_pending_destination_and_confirms_it():
    client = _client()
    assert client.warp_to_level("b.nw", 12.0, 14.0)
    assert client._awaiting_warp_confirm == "b.nw"
    # old-level props that were in transit, stamped with the flipped name
    client.items["b.nw"] = {(1.0, 1.0): 1}
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("b.nw"))
    assert client._awaiting_warp_confirm == ""
    assert client._warp_fallback is None
    assert client.items == {}
    assert client._current_level_name == "b.nw"
    assert client._level_scope == "b.nw"

    # a later server-pushed warp is a plain server warp, not a rollback
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("c.nw"))
    assert client._current_level_name == "c.nw"
    assert client._level_scope == "c.nw"
    assert client.player.level == "c.nw"
    assert client._warp_fallback is None


def test_a_refused_requested_warp_still_rolls_back():
    client = _client()
    assert client.warp_to_level("b.nw", 12.0, 14.0)
    client._handle_packet(PacketID.PLO_WARPFAILED, b"b.nw")
    assert client._awaiting_warp_confirm == ""
    assert client._current_level_name == "a.nw"
    assert client._level_scope == "a.nw"
    assert (client.player.x, client.player.y) == (30.0, 30.0)
    assert client.tiles is client.levels["a.nw"]


def test_a_warp_naming_another_level_still_rolls_back_first():
    client = _client()
    assert client.warp_to_level("b.nw", 12.0, 14.0)
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("c.nw"))
    assert client._awaiting_warp_confirm == ""
    assert client._current_level_name == "c.nw"
