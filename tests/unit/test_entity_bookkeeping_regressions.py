from pyreborn import Client
from pyreborn.packet_codec.common import PacketReader
from pyreborn.packets import PacketID, build_bomb_add
from unittest.mock import Mock


def test_bomb_add_localizes_world_coordinates_to_gmap_segment():
    reader = PacketReader(build_bomb_add(70, 22))

    assert reader.read_gchar() / 2 == 6
    assert reader.read_gchar() / 2 == 22


def test_full_level_reset_clears_horses():
    client = Client("localhost", 14900)
    client.horses = {
        "old.nw": {(4.0, 5.0): {"x": 4.0, "y": 5.0}},
    }

    client._reset_level_state()

    assert client.horses == {}


def test_adjacent_request_in_flight_is_not_sent_again_after_crossing():
    client = Client("localhost", 14900)
    client._protocol.connected = True
    client._protocol.send_packet = Mock(return_value=True)
    client._authenticated = True
    client.gmap_width = 2
    client.gmap_height = 2
    client.gmap_grid = {
        (0, 0): "A.nw", (1, 0): "B.nw",
        (0, 1): "C.nw", (1, 1): "D.nw",
    }
    client._current_level_name = "A.nw"
    client._pending_level_name = "A.nw"

    client.request_adjacent_levels()
    client._current_level_name = "B.nw"
    client._pending_level_name = "B.nw"
    client.request_adjacent_levels()

    requests = [call.args[1][5:].decode("latin-1")
                for call in client._protocol.send_packet.call_args_list]
    for level_name in requests:
        if level_name == "D.nw":
            client._handle_packet(PacketID.PLO_LEVELNAME, b"D.nw")
    client._handle_packet(PacketID.PLO_ITEMADD, bytes((46, 50, 33)))

    assert requests.count("D.nw") == 1
    assert client.items_in_level("B.nw") == {(7.0, 9.0): "bluerupee"}
    assert client.items_in_level("D.nw") == {}


def test_bombs_are_independent_per_level_and_ignore_stale_preload():
    client = Client("localhost", 14900)
    client._current_level_name = "chicken1.nw"
    client._pending_level_name = "chicken1.nw"
    client._pending_board_level_name = "chicken8.nw"
    payload = bytes((32, 32, 32 + 12, 32 + 44, 33, 32 + 60))

    client._handle_packet(PacketID.PLO_BOMBADD, payload)

    assert (6.0, 22.0) in client.bombs_in_level("chicken1.nw")
    assert client.bombs_in_level("chicken8.nw") == {}


def _board_layer_payload(layer: int, tile_byte: int) -> bytes:
    return bytes((layer, 0, 0, 64, 64)) + bytes((tile_byte,)) * 8192


def test_adjacent_preload_layers_do_not_replace_active_level_layers():
    client = Client("localhost", 14900)
    client._current_level_name = "myown.nw"
    client._pending_level_name = "myown.nw"
    client.board_layers = {1: b"own-layer"}
    client._board_layers_level_name = "myown.nw"
    client._adjacent_level_requests.add("neighbor.nw")

    client._handle_packet(PacketID.PLO_LEVELNAME, b"neighbor.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, bytes(8192))
    client._handle_packet(PacketID.PLO_BOARDLAYER,
                          _board_layer_payload(2, 7))

    assert client.board_layers == {1: b"own-layer"}
    assert client._board_layers_level_name == "myown.nw"
    assert client._pending_board_level_name == "neighbor.nw"


def test_genuine_level_transfer_attributes_every_board_layer():
    client = Client("localhost", 14900)
    client._current_level_name = "old.nw"
    client._pending_level_name = "old.nw"
    client.board_layers = {1: b"old-layer"}
    client._board_layers_level_name = "old.nw"

    client._handle_packet(PacketID.PLO_LEVELNAME, b"new.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, bytes(8192))
    client._handle_packet(PacketID.PLO_BOARDLAYER,
                          _board_layer_payload(2, 7))
    client._handle_packet(PacketID.PLO_BOARDLAYER,
                          _board_layer_payload(3, 9))

    assert client._board_layers_level_name == "new.nw"
    assert set(client.board_layers) == {2, 3}
    assert client.board_layers[2] == bytes((7,)) * 8192
    assert client.board_layers[3] == bytes((9,)) * 8192


def test_genuine_transfer_clears_layers_when_next_level_has_none():
    client = Client("localhost", 14900)
    client._current_level_name = "A.nw"
    client._pending_level_name = "A.nw"
    client.board_layers = {1: b"old-layer"}
    client._board_layers_level_name = "A.nw"

    client._handle_packet(PacketID.PLO_LEVELNAME, b"B.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, bytes(8192))

    assert client.board_layers == {}
    assert client._board_layers_level_name == ""


def test_bombs_accessor_accepts_the_flat_store_shape():
    client = Client("localhost", 14900)
    bomb = {"power": 2}
    client.bombs = {(4.0, 5.0): bomb}

    assert client.bombs_in_level("any.nw") == {(4.0, 5.0): bomb}
