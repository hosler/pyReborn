from pyreborn import Client
from pyreborn.packets import BDPROP, PacketID, build_baddy_props


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


def test_live_item_packet_ignores_stale_adjacent_preload_attribution():
    client = Client("localhost", 14900)
    client._current_level_name = "chicken1.nw"
    client._pending_level_name = "chicken1.nw"
    client.gmap_width = 2
    client.gmap_height = 1
    client.gmap_grid = {(0, 0): "chicken1.nw", (1, 0): "chicken8.nw"}
    client._adjacent_level_requests.add("chicken8.nw")

    client._handle_packet(PacketID.PLO_LEVELNAME, b"chicken8.nw")

    # PLO_ITEMADD carries gchar half-tile coordinates followed by item id.
    client._handle_packet(PacketID.PLO_ITEMADD, bytes((32 + 14, 32 + 18, 33)))

    assert client._pending_level_name == "chicken1.nw"
    assert client.items == {"chicken1.nw": {(7.0, 9.0): "bluerupee"}}
    assert "chicken8.nw" not in client.items


def test_baddy_props_update_finds_the_existing_owning_level():
    client = Client("localhost", 14900)
    client._current_level_name = "east.nw"
    client.baddies = {"west.nw": {5: {"id": 5, "power": 3}}}

    client._handle_packet(
        PacketID.PLO_BADDYPROPS,
        build_baddy_props(5, {BDPROP.POWERIMAGE: (1, "baddygray.png")}))

    assert client.baddies["west.nw"][5]["power"] == 1
    assert "east.nw" not in client.baddies
