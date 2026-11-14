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


def _gint3(v):
    return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32,
                  (v & 0x7F) + 32])


def _npc(client, npc_id, x):
    """PLO_NPCPROPS carrying X2, encoded by the NPC_PROPS table."""
    from reborn_protocol.props import NPC_PROPS, encode_value
    desc = next(d for d in NPC_PROPS.values() if d.name == "X2")
    client._handle_packet(PacketID.PLO_NPCPROPS,
                          _gint3(npc_id) + bytes([desc.id + 32])
                          + encode_value(desc, x))


def test_a_revisited_level_restores_its_cached_npcs_once():
    client = _client()
    client._npc_level = "a.nw"
    _npc(client, 41, 10.0)
    assert client.warp_to_level("b.nw", 12.0, 14.0)
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("b.nw"))
    assert 41 not in client.npcs
    # back: the warp is confirmed and a.nw's NPC returns from the cache
    assert client.warp_to_level("a.nw", 12.0, 14.0)
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("a.nw"))
    assert list(client.npcs) == [41]
    assert client.npcs[41]['x'] == 10.0
    # a second PLAYERWARP naming the same level restores nothing twice
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("a.nw"))
    assert list(client.npcs) == [41]
    # the re-streamed props overwrite the cached copy by id
    client._npc_level = "a.nw"
    _npc(client, 41, 20.0)
    assert list(client.npcs) == [41]
    assert client.npcs[41]['x'] == 20.0


def test_a_second_requested_warp_confirms_after_the_first_cleared_pending():
    client = _client()
    assert client.warp_to_level("b.nw", 12.0, 14.0)
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("b.nw"))
    assert client._awaiting_warp_confirm == ""
    assert client.warp_to_level("c.nw", 8.0, 9.0)
    assert client._awaiting_warp_confirm == "c.nw"
    client._handle_packet(PacketID.PLO_PLAYERWARP, _warp("c.nw"))
    assert client._awaiting_warp_confirm == ""
    assert client._warp_fallback is None
    assert client._current_level_name == "c.nw"
    assert client._level_scope == "c.nw"
    # and the second one can still be refused and rolled back
    assert client.warp_to_level("d.nw", 8.0, 9.0)
    client._handle_packet(PacketID.PLO_WARPFAILED, b"d.nw")
    assert client._awaiting_warp_confirm == ""
    assert client._current_level_name == "c.nw"
