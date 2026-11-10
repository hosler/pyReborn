"""V4 script packets use the same state and VM delivery as modern packets."""

import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyreborn import Client
from pyreborn.gs2_client import ClientGS2
from pyreborn.protocol import Protocol, WebSocketProtocol
import pyreborn.protocol as protocol_module
from reborn_protocol.gs2 import Op


def _gint(value, size):
    return bytes(((value >> (7 * shift)) & 127) + 32
                 for shift in reversed(range(size)))


def _named(name, bytecode):
    return bytes([len(name) + 32]) + name.encode('latin-1') + bytecode


def _header(kind, name, crc=b''):
    fields = [kind.encode(), name.encode(), b'1', b'', crc]
    return b','.join(b'"' + field.replace(b'"', b'""') + b'"'
                     if b',' in field or b'"' in field else field
                     for field in fields)


def _bytecode():
    segments = [(1, b'\0' * 4), (2, b'\0' * 4 + b'onCreated\0'),
                (3, b'line\nname\0'), (4, bytes([Op.OP_RET]))]
    return b''.join(struct.pack('>II', kind, len(body)) + body
                    for kind, body in segments) + b'\n'


def _client():
    client = Client('localhost', 14900)
    client._authenticated = True
    client._protocol = SimpleNamespace(connected=True, send_packet=Mock(return_value=True))
    client.on_gs2_bytecode = Mock()
    runtime = ClientGS2(client).attach()
    return client, runtime


def _raw_packets(packet_id, payload, transport, monkeypatch):
    raw = bytes([packet_id + 32]) + payload + b'\n'
    chunks = [bytes([100 + 32]) + _gint(len(raw), 3) + b'\n' + raw[:4],
              raw[4:] + bytes([10 + 32]) + b'\n']
    if transport == 'websocket':
        proto = WebSocketProtocol('ws://localhost', 'localhost', 14900)
        proto._parse_packets(chunks[0])
        assert proto.pending_packets == [(100, _gint(len(raw), 3))]
        proto.pending_packets.clear()
        proto._parse_packets(chunks[1])
        packets = proto.pending_packets
    else:
        proto = Protocol('localhost', 14900)
        proto.connected = True
        proto.first_packet = False
        proto.codec.recv_packet = lambda data: data

        class Socket:
            chunk = b''

            def setblocking(self, flag):
                pass

            def recv(self, size):
                if not self.chunk:
                    raise BlockingIOError
                data, self.chunk = self.chunk, b''
                return data

        proto.socket = Socket()
        monkeypatch.setattr(protocol_module.select, 'select',
                            lambda *args: ([proto.socket], [], []))
        proto.socket.chunk = struct.pack('>H', len(chunks[0])) + chunks[0]
        assert proto.recv_packets() == [(100, _gint(len(raw), 3))]
        proto.socket.chunk = struct.pack('>H', len(chunks[1])) + chunks[1]
        packets = proto.recv_packets()
    assert packets == [(packet_id, payload), (10, b'')]
    assert proto.raw_data_expected == 0
    assert proto.raw_data_buffer == b''
    return packets[0]


@pytest.mark.parametrize('transport', ['native', 'websocket'])
@pytest.mark.parametrize('kind,empty', [
    ('weapon', False), ('weapon', True), ('class', False), ('class', True),
])
def test_v4_bytecode_matches_modern_delivery(kind, empty, transport, monkeypatch):
    name = 'TestScript'
    blob = b'' if empty else _bytecode()
    old, old_runtime = _client()
    modern, modern_runtime = _client()
    old.gs1_host = SimpleNamespace(receive_class_source=Mock())
    modern.gs1_host = SimpleNamespace(receive_class_source=Mock())
    old_id = 132 if kind == 'weapon' else 133
    header = _header(kind, name)
    modern_id = 140 if kind == 'weapon' or empty else 197
    modern_payload = _gint(len(header), 2 if modern_id == 140 else 1) + header + blob

    old._handle_packet(*_raw_packets(old_id, _named(name, blob), transport, monkeypatch))
    modern._handle_packet(*_raw_packets(modern_id, modern_payload, transport, monkeypatch))

    assert old.gs2_bytecode == modern.gs2_bytecode
    assert old.gs2_bytecode[kind][name] == blob
    for client in (old, modern):
        info = client.gs2_script_headers[name]
        assert (info['type'], info['name'], info['bytecode']) == (kind, name, blob)
    assert old_runtime._prev_bytecode_cb.call_args_list == modern_runtime._prev_bytecode_cb.call_args_list
    old_runtime._prev_bytecode_cb.assert_called_once_with(kind, name, blob)
    assert old.gs1_host.receive_class_source.call_args_list == modern.gs1_host.receive_class_source.call_args_list
    if kind == 'class' and not empty:
        old.gs1_host.receive_class_source.assert_called_once_with(name, blob)
    if not empty:
        old_vm = old_runtime.vms[kind][name.lower()]
        modern_vm = modern_runtime.vms[kind][name.lower()]
        assert old_vm.has_function('onCreated')
        assert old_vm.container.code == modern_vm.container.code


def test_v4_hash_matches_modern_header_and_crc_request_cache():
    name = 'TestWeapon'
    old, _ = _client()
    modern, _ = _client()
    for crc in (b'!"#,$', b'!"#,$', b'!"#,%'):
        old._handle_packet(193, crc + name.encode())
        modern._handle_packet(197, _header('weapon', name, crc))
        assert old._gs2_requested == modern._gs2_requested
        assert old.gs2_script_headers[name]['crc'] == crc.decode('latin-1')
        assert old._protocol.send_packet.call_args_list == modern._protocol.send_packet.call_args_list
    assert old._protocol.send_packet.call_count == 2
    assert old.gs2_bytecode['weapon'] == {}
    old._protocol.send_packet.assert_called_with(158, name.encode())


def test_v4_hash_retries_after_unsent_request():
    client, _ = _client()
    client._protocol.send_packet.side_effect = [False, True]
    payload = _gint(123, 5) + b'TestWeapon'
    client._handle_packet(193, payload)
    assert client._gs2_requested == set()
    client._handle_packet(193, payload)
    assert len(client._gs2_requested) == 1
    assert client._protocol.send_packet.call_count == 2
