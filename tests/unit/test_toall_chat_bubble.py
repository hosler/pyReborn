"""PLO_TOALL updates the speaker's in-level chat text as well as on_chat."""
from pyreborn.handlers.chat import handle_toall


class _Client:
    def __init__(self):
        self.players = {7: {'nickname': 'tb1', 'x': 30.0, 'y': 30.5}}
        self.heard = []
        self.on_chat = lambda pid, msg: self.heard.append((pid, msg))


def _toall(player_id, message):
    # [player_id:GShort][len:GChar][message raw] - packet_codec/level.py parse_chat
    body = message.encode('latin-1')
    return bytes([((player_id >> 7) & 0x7F) + 32, (player_id & 0x7F) + 32, len(body) + 32]) + body


def test_toall_stores_chat_on_known_player():
    client = _Client()
    handle_toall(client, _toall(7, "hello"))
    assert client.heard == [(7, "hello")]
    assert client.players[7]['chat'] == "hello"


def test_toall_from_unknown_player_only_fires_callback():
    client = _Client()
    handle_toall(client, _toall(9, "hi"))
    assert client.heard == [(9, "hi")]
    assert 9 not in client.players
