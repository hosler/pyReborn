from pyreborn import Client
from pyreborn.packets import PacketID


def _chest_packet(opened, x, y, item=None, sign=0):
    data = bytes((32 + int(opened), 32 + x, 32 + y))
    if item is not None:
        data += bytes((32 + item, 32 + sign))
    return data


def test_chest_helpers_keep_identical_coordinates_independent():
    client = Client("localhost", 14900)

    client.chests.setdefault("west.nw", {})[(12, 18)] = False
    client.chests.setdefault("east.nw", {})[(12, 18)] = False
    client.set_chest_opened("west.nw", 12, 18)

    assert client.get_chest_opened("west.nw", 12, 18) is True
    assert client.get_chest_opened("east.nw", 12, 18) is False
    assert client.chests_in_level("west.nw") == {(12, 18): True}
    assert client.chests_in_level("missing.nw") == {}


def test_chest_packet_uses_the_sign_stream_attribution_rule():
    client = Client("localhost", 14900)
    client._current_level_name = "player.nw"
    client._pending_level_name = "preloaded.nw"

    client._handle_packet(
        PacketID.PLO_LEVELCHEST, _chest_packet(False, 7, 9, item=1))

    assert client.chests == {"preloaded.nw": {(7, 9): False}}
    assert client.chest_items == {"preloaded.nw": {(7, 9): "bluerupee"}}
    assert "player.nw" not in client.chests
