"""Regression tests for bounded protocol and client state handling."""

import struct
import zlib

import pytest

import pyreborn.client as client_module
import pyreborn.protocol as protocol_module
from pyreborn import Client
from pyreborn.packets import PacketID
from pyreborn.protocol import Protocol, WebSocketProtocol


class _FailingSocket:
    def setblocking(self, _flag):
        pass

    def sendall(self, _data):
        raise OSError("simulated partial send")


def test_failed_send_marks_connection_disconnected():
    proto = Protocol("127.0.0.1", 0)
    proto.socket = _FailingSocket()
    proto.connected = True

    assert proto.send_packet(1, b"payload") is False
    assert proto.connected is False


def test_bounded_decompress_rejects_output_over_cap(monkeypatch):
    monkeypatch.setattr(protocol_module, "MAX_DECOMPRESSED_SIZE", 64)
    compressed = zlib.compress(b"x" * 65)

    with pytest.raises(protocol_module.DecompressionLimitError):
        protocol_module._decompress_bounded(compressed)


def test_websocket_drops_oversized_first_packet(monkeypatch):
    monkeypatch.setattr(protocol_module, "MAX_DECOMPRESSED_SIZE", 64)
    proto = WebSocketProtocol("ws://proxy", "server", 1)
    compressed = zlib.compress(b"x" * 65)
    proto.recv_buffer = struct.pack(">H", len(compressed)) + compressed

    proto._process_buffer()

    assert proto.first_packet is False
    assert proto.pending_packets == []


@pytest.mark.parametrize("protocol_cls", [Protocol, WebSocketProtocol])
def test_raw_data_size_is_clamped_to_zero(protocol_cls):
    if protocol_cls is Protocol:
        proto = protocol_cls("127.0.0.1", 0)
        packets = []
        decrypted = bytes([100 + 32, 0, 0, 0, 10])
        proto.first_packet = False
        proto.codec.recv_packet = lambda _data: decrypted
        proto.recv_buffer = struct.pack(">H", 1) + b"x"

        class _ReadableSocket:
            def setblocking(self, _flag):
                pass

            def recv(self, _size):
                raise BlockingIOError

        proto.socket = _ReadableSocket()
        proto.connected = True
        original_select = protocol_module.select.select
        protocol_module.select.select = lambda *_args: ([proto.socket], [], [])
        try:
            proto.recv_buffer = struct.pack(">H", 1) + b"x"
            packets = proto.recv_packets()
        finally:
            protocol_module.select.select = original_select
        assert packets == [(100, b"\x00\x00\x00")]
    else:
        proto = protocol_cls("ws://proxy", "server", 1)
        proto._parse_packets(bytes([100 + 32, 0, 0, 0, 10]))

    assert proto.raw_data_expected == 0


class _SendResult:
    connected = True

    def __init__(self, result):
        self.result = result

    def send_packet(self, _packet_id, _data=b""):
        return self.result


def _connected_client():
    client = Client("localhost", 14900)
    client._authenticated = True
    client._protocol = _SendResult(True)
    return client


def test_failed_warp_send_restores_previous_state():
    client = _connected_client()
    client._current_level_name = "before.nw"
    client._pending_level_name = "before.nw"
    client.player.x = 12.0
    client.player.y = 13.0
    client.levels["before.nw"] = [1] * 4096
    client.tiles = client.levels["before.nw"]
    client._tiles_level_name = "before.nw"
    client._protocol = _SendResult(False)

    assert client.warp_to_level("after.nw", 4.0, 5.0) is False
    assert client._current_level_name == "before.nw"
    assert (client.player.x, client.player.y) == (12.0, 13.0)
    assert client._awaiting_warp_confirm == ""
    assert client._warp_fallback is None


def _file_packet(filename, data):
    encoded_name = filename.encode("latin-1")
    return b" " * 5 + bytes([len(encoded_name) + 32]) + encoded_name + data


def test_large_file_exceeding_announced_size_is_aborted():
    client = _connected_client()
    filename = "large.bin"
    client._pending_files.add(filename)
    client._large_file_transfers[filename] = {
        "buffer": bytearray(), "expected_size": 1,
        "modtime": 0, "discarding": False,
    }
    oversized = b"x" * (client_module.LARGE_FILE_SIZE_SLACK + 2)

    client._handle_packet(PacketID.PLO_FILE, _file_packet(filename, oversized))

    assert client._large_file_transfers[filename]["discarding"]
    assert client._large_file_transfers[filename]["buffer"] == bytearray()
    assert filename in client.failed_files
    assert not client.is_file_pending(filename)


def test_large_file_absolute_cap_applies_without_announced_size(monkeypatch):
    monkeypatch.setattr(client_module, "MAX_LARGE_FILE_SIZE", 4)
    client = _connected_client()
    filename = "large.bin"
    client._large_file_transfers[filename] = {
        "buffer": bytearray(), "expected_size": 0,
        "modtime": 0, "discarding": False,
    }

    client._handle_packet(PacketID.PLO_FILE, _file_packet(filename, b"12345"))

    assert filename in client.failed_files
    assert client._large_file_transfers[filename]["discarding"]


def test_bounded_lru_refreshes_reads_and_evicts_oldest():
    cache = client_module.BoundedLRU(2)
    cache["first"] = 1
    cache["second"] = 2
    assert cache["first"] == 1
    cache["third"] = 3

    assert "first" in cache
    assert "second" not in cache
    assert cache["third"] == 3
