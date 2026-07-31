"""The list-server client on top of the shared reborn_protocol codec.

Pinned against `tests/fixtures/listserver_session_live.json`, a recording of a
real listserver.graal.in:14922 discovery query taken with the previous
hand-rolled copy of the codec: the same key must produce the same outbound
bytes, and the same inbound bytes must produce the same parsed list.
"""

import ast
import json
import zlib
from pathlib import Path

import pytest

import pyreborn.listserver as listserver_module
from reborn_protocol.codec import Gen5Codec
from reborn_protocol.encryption import (
    GAME_COMPRESSION,
    LIST_SERVER_COMPRESSION,
    CompressionType,
)
from pyreborn.listserver import (
    LSPacketID,
    ListServerClient,
    ListServerSession,
    build_response,
    parse_server_list,
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "listserver_session_live.json")
    .read_text()
)

# The fixture stores bundle payloads; feed() consumes the framed wire form.
RECV_BUNDLES = [bytes.fromhex(frame) for frame in FIXTURE["recv_frames"]]
RECV_WIRE = b"".join(len(b).to_bytes(2, "big") + b for b in RECV_BUNDLES)


def _session():
    return ListServerSession(encryption_key=FIXTURE["encryption_key"])


def test_init_packet_matches_the_recorded_frame():
    assert _session().build_init_packet().hex() == FIXTURE["sent_init_frame"]


def test_login_packet_matches_the_recorded_frame():
    session = _session()
    session.build_init_packet()  # Gen2-framed; must not touch the GEN_5 LCG
    frame = session.build_login_packet(FIXTURE["dummy_account"],
                                       FIXTURE["dummy_password"])
    assert frame.hex() == FIXTURE["sent_login_frame"]


def test_recorded_bundles_decode_to_the_recorded_server_list():
    response = build_response(_session().feed(RECV_WIRE),
                              "listserver.graal.in")
    expected = FIXTURE["expected"]
    assert response.success
    assert response.status == expected["status"]
    assert response.site_url == expected["site_url"]
    assert response.donate_url == expected["donate_url"]
    assert [vars(entry) for entry in response.servers] == expected["servers"]


def test_a_frame_split_across_reads_stays_buffered_until_complete():
    session = _session()
    packets = []
    for cut in range(0, len(RECV_WIRE), 137):  # arbitrary chunking
        packets.extend(session.feed(RECV_WIRE[cut:cut + 137]))

    ids = [packet_id for packet_id, _ in packets]
    assert ids[0] == LSPacketID.PLO_SVRLIST
    assert set(ids) >= {LSPacketID.PLO_SVRLIST, LSPacketID.PLO_STATUS,
                        LSPacketID.PLO_SITEURL, LSPacketID.PLO_UPGURL}
    whole = build_response(_session().feed(RECV_WIRE), "listserver.graal.in")
    assert build_response(packets, "listserver.graal.in") == whole


def test_session_never_upgrades_to_bz2():
    """The recorded witness: a bundle over the game session's 8192-byte bz2
    threshold still goes out as ZLIB on the list-server session."""
    payload = bytes.fromhex(FIXTURE["oversize_bundle"]["payload"])
    assert len(payload) > 0x2000

    session = _session()
    frame = session.codec.send_packet(payload)
    assert frame.hex() == FIXTURE["oversize_bundle"]["frame"]
    assert frame[2] == CompressionType.ZLIB
    assert session.codec.compression is LIST_SERVER_COMPRESSION


def test_game_session_would_have_used_bz2_for_the_same_bundle():
    """Proves the policy is load-bearing, not decoration."""
    payload = bytes.fromhex(FIXTURE["oversize_bundle"]["payload"])
    frame = Gen5Codec(FIXTURE["encryption_key"]).send_packet(payload)
    assert frame[2] == CompressionType.BZ2
    assert Gen5Codec().compression is GAME_COMPRESSION


def test_first_bundle_may_be_plain_zlib_without_a_type_byte():
    """The server's out codec is ENCRYPT_GEN_2 until it reads our init packet
    (graal-serverlist PlayerConnection.cpp:42)."""
    bundle = bytes([LSPacketID.PLO_SITEURL + 32]) + b"https://example.test\n"
    compressed = zlib.compress(bundle)
    packets = _session().feed(len(compressed).to_bytes(2, "big") + compressed)
    assert packets == [(LSPacketID.PLO_SITEURL, b"https://example.test")]


def test_first_bundle_fallback_does_not_poison_later_bundles():
    """A GEN_5 first bundle (what live listservers actually send) must not
    leave the plain-zlib attempt armed for the rest of the session."""
    session = _session()
    first = session.feed(RECV_WIRE[:2 + len(RECV_BUNDLES[0])])
    second = session.feed(RECV_WIRE[2 + len(RECV_BUNDLES[0]):])
    assert first and second
    assert not session._first_packet


def _wire_string(raw: bytes) -> bytes:
    return bytes([len(raw) + 32]) + raw


def _entry_packet(name: bytes, ip: bytes = b"127.0.0.1") -> bytes:
    fields = [name, b"English", b"desc", b"url", b"2.22", b"1", ip, b"14900"]
    return bytes([33, 40]) + b"".join(_wire_string(field) for field in fields)


def test_list_server_text_is_cp1252_not_latin1():
    entry = parse_server_list(_entry_packet(b"Alice\x92s"), "host.test")[0]
    assert entry.name == "Alice’s"


def test_auto_address_resolves_against_the_client_host_it_was_asked_for():
    client = ListServerClient("list.example.test")
    entry = client._parse_server_list(_entry_packet(b"H Test", b"$AUTO"))[0]
    assert entry.ip == "list.example.test" and entry.auto_address_substituted


def test_a_length_prefix_below_the_offset_cannot_rewind_the_reader():
    """The shared reader clamps a sub-+32 length to 0. The private copy this
    module used to carry advanced pos by the negative value instead, which
    then read a negative index and raised IndexError."""
    truncated = bytes([33, 40, 0x00])  # 1 server, 8 fields, name length -32
    entries = parse_server_list(truncated, "host.test")
    assert [entry.name for entry in entries] == [""]


@pytest.mark.parametrize("packet_id, attribute", [
    (LSPacketID.PLO_STATUS, "status"),
    (LSPacketID.PLO_SITEURL, "site_url"),
    (LSPacketID.PLO_UPGURL, "donate_url"),
])
def test_text_packets_land_on_their_response_field(packet_id, attribute):
    response = build_response([(packet_id, b"text")], "host.test")
    assert getattr(response, attribute) == "text"
    assert not response.success


def test_error_packet_clears_success():
    response = build_response([(LSPacketID.PLO_SVRLIST, bytes([32])),
                               (LSPacketID.PLO_ERROR, b"nope")], "host.test")
    assert response.error == "nope" and not response.success


# ---------------------------------------------------------------------------
# WebSocket adapter
#
# WebSocketListServerClient only exists under `if IS_BROWSER:`, so it cannot be
# imported here. Re-exec just that class body with a stubbed `window` to keep
# the browser path from rotting silently; this is the only coverage it has.
# ---------------------------------------------------------------------------

class _StubArray(list):
    """Stands in for a JS Uint8Array/ArrayBuffer."""

    @property
    def byteLength(self):
        return len(self)

    @property
    def buffer(self):
        return bytes(self)


class _StubEvent:
    def __init__(self, data):
        self.data = data


def _websocket_client_class():
    tree = ast.parse(Path(listserver_module.__file__).read_text())
    guard = next(node for node in tree.body
                 if isinstance(node, ast.If)
                 and getattr(node.test, 'id', '') == 'IS_BROWSER'
                 and any(isinstance(b, ast.ClassDef) for b in node.body))
    class_def = next(b for b in guard.body if isinstance(b, ast.ClassDef))

    class _StubSocket:
        def __init__(self, url):
            self.url = url
            self.sent = []
            self.readyState = 1

        def send(self, data):
            self.sent.append(data if isinstance(data, str) else bytes(data))

        def close(self):
            pass

    class _StubWindow:
        WebSocket = type('WebSocket', (), {'new': staticmethod(_StubSocket)})
        Uint8Array = type('Uint8Array', (), {'new': staticmethod(
            lambda arg: _StubArray(bytes(arg)
                                   if isinstance(arg, (bytes, bytearray, list))
                                   else [0] * arg))})

    namespace = dict(listserver_module.__dict__)
    namespace['window'] = _StubWindow
    exec(compile(ast.Module(body=[class_def], type_ignores=[]),
                 listserver_module.__file__, 'exec'), namespace)
    return namespace['WebSocketListServerClient']


@pytest.fixture
def websocket_client():
    client = _websocket_client_class()('list.example.test', 14922,
                                       proxy_url='ws://proxy.test')
    assert client.connect()
    client._ws.onopen(None)
    client._ws.onmessage(_StubEvent('{"type": "connected"}'))
    assert client.connected
    return client


def test_websocket_adapter_sends_the_same_frames_as_the_socket_client(
        websocket_client):
    session = _session()
    websocket_client._session = session

    assert websocket_client._send_init_packet()
    assert websocket_client._send_login_packet(FIXTURE["dummy_account"],
                                               FIXTURE["dummy_password"])
    proxy_hello, init, login = websocket_client._ws.sent
    assert json.loads(proxy_hello) == {"host": "list.example.test",
                                       "port": 14922}
    assert init.hex() == FIXTURE["sent_init_frame"]
    assert login.hex() == FIXTURE["sent_login_frame"]


def test_websocket_adapter_reassembles_a_bundle_split_across_messages(
        websocket_client):
    bundle = (bytes([LSPacketID.PLO_SVRLIST + 32])
              + _entry_packet(b"H Test", b"$AUTO") + b"\n"
              + bytes([LSPacketID.PLO_STATUS + 32]) + b"hello\n")
    frame = zlib.compress(bundle)
    wire = len(frame).to_bytes(2, "big") + frame

    websocket_client._ws.onmessage(_StubEvent(_StubArray(wire[:5])))
    assert websocket_client.get_received_packets() == []
    websocket_client._ws.onmessage(_StubEvent(_StubArray(wire[5:])))

    response = build_response(websocket_client.get_received_packets(),
                              websocket_client.host)
    assert response.success and response.status == "hello"
    entry = response.servers[0]
    assert entry.ip == "list.example.test" and entry.auto_address_substituted
    assert entry.player_count == 1


def test_status_body_decodes_as_cp1252():
    """PLO_STATUS/SITEURL/UPGURL/ERROR bodies are list-server text, so they use
    the same cp1252 codepage as the length-prefixed fields. 0x92 is a right
    single quote there. Latin-1 would yield the U+0092 control character."""
    body = b"Rusty\x92s server"
    response = build_response([(LSPacketID.PLO_STATUS, body)], "")
    assert response.status == "Rusty’s server"
    assert "\x92" not in response.status
