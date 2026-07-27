import pytest

from pyreborn.client import Client
from pyreborn.packets import PacketID


class _Protocol:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data):
        self.sent.append((packet_id, data))
        return True


def _client(version):
    client = Client(version=version)
    client._protocol = _Protocol()
    client._authenticated = True
    client._remember_appearance = lambda **fields: None
    return client


@pytest.mark.parametrize(("version", "width"), [("2.22", 5), ("6.037", 8)])
def test_send_colors_uses_session_width(version, width):
    client = _client(version)

    assert client.send_colors(range(1, 9))

    assert client._protocol.sent == [
        (PacketID.PLI_PLAYERPROPS,
         bytes([13 + 32]) + bytes(value + 32 for value in range(1, width + 1)))
    ]


def test_send_head_image_supports_preset_and_custom_forms():
    client = _client("6.037")

    assert client.send_head_image(7)
    assert client._protocol.sent[-1][1] == bytes([11 + 32, 7 + 32])

    assert client.send_head_image("custom.png")
    assert client._protocol.sent[-1][1] == (
        bytes([11 + 32, 100 + len("custom.png") + 32]) + b"custom.png")


def test_send_body_image_uses_string_property_encoding():
    client = _client("2.22")

    assert client.send_body_image("body20.png")

    assert client._protocol.sent[-1] == (
        PacketID.PLI_PLAYERPROPS,
        bytes([35 + 32, len("body20.png") + 32]) + b"body20.png")


def test_login_restore_sends_only_properties_the_server_omitted(monkeypatch):
    client = _client("2.22")
    remembered = []
    prefs = type("Saved", (), {
        "appearance_head": "head9.png",
        "appearance_body": "body7.png",
        "appearance_colors": [1, 2, 3, 4, 5],
        "remember_appearance": lambda self, **values: remembered.append(values),
    })()
    monkeypatch.setattr("pyreborn.prefs.Prefs.load", lambda: prefs)
    client.player.head_image = "head44.png"

    client._apply_login_appearance({"head_image": "head44.png"})

    payloads = [payload for _packet_id, payload in client._protocol.sent]
    assert [payload[0] - 32 for payload in payloads] == [35, 13]
    assert remembered[-1] == {"head": "head44.png"}


def test_login_restore_runs_only_once(monkeypatch):
    client = _client("2.22")
    prefs = type("Saved", (), {
        "appearance_head": "head9.png",
        "appearance_body": None,
        "appearance_colors": None,
        "remember_appearance": lambda self, **values: None,
    })()
    monkeypatch.setattr("pyreborn.prefs.Prefs.load", lambda: prefs)

    client._apply_login_appearance({})
    client._apply_login_appearance({})

    assert len(client._protocol.sent) == 1
