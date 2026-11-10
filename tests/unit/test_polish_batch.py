"""Focused coverage for the deferred client polish features."""

from pyreborn.client import Client
from pyreborn.game.setup import append_start_message
from pyreborn.packets import PacketID, parse_newworldtime
from pyreborn.player import Player


def test_start_message_callback_and_chat_lines():
    client = Client()
    chat = []
    seen = []

    def receive(text):
        seen.append(text)
        append_start_message(chat, text)

    client.on_start_message = receive
    client._handle_packet(PacketID.PLO_STARTMESSAGE,
                          b" First\n\nSecond\r\nThird\nFourth\nFifth\nSixth")

    assert seen == [" First\n\nSecond\r\nThird\nFourth\nFifth\nSixth"]
    assert chat == [
        "[server] First", "[server] Second", "[server] Third",
        "[server] Fourth", "[server] Fifth",
    ]


def test_player_hidden_status_bit():
    player = Player(status=0x02)
    assert player.is_hidden
    player.status = 0x01 | 0x08
    assert not player.is_hidden


def test_mode_packets_preserve_input_and_connection_reset_clears_legacy_lock():
    client = Client()
    changes = []
    client.on_fullstop = changes.append

    client._handle_packet(PacketID.PLO_DISABLECLASSICMODE, b"")
    assert client.classic_mode_disabled
    assert not client.input_frozen
    client._handle_packet(PacketID.PLO_FULLSTOP2, b"")
    assert not client.input_frozen
    assert changes == []

    client.input_frozen = True
    client._protocol.connect = lambda: True
    assert client.connect()
    assert not client.input_frozen
    assert changes == [False]


def test_ghost_icon_and_mode_packets_have_independent_state():
    client = Client()
    mode_changes = []
    client.on_ghost_mode = mode_changes.append

    client._handle_packet(PacketID.PLO_GHOSTMODE, b"!")
    client._handle_packet(PacketID.PLO_GHOSTICON, b"!")
    assert client.ghost_mode == 1
    assert client.ghost_icon is True

    client._handle_packet(PacketID.PLO_GHOSTICON, b" ")
    assert client.ghost_mode == 1
    assert client.ghost_icon is False
    assert mode_changes == [1]


def test_newworldtime_decodes_four_gbytes():
    value = 160_000_000
    encoded = bytes(32 + ((value >> shift) & 0x7f)
                    for shift in (21, 14, 7, 0))
    assert parse_newworldtime(encoded) == {"time": value}
