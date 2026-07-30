"""Regression coverage for bounded draining of the native socket transport."""

import os
import socket
import struct

import pytest

import pyreborn.protocol as protocol_module
from pyreborn.protocol import Protocol


class _CountingSocket:
    def __init__(self, sock):
        self.sock = sock
        self.received = 0

    def setblocking(self, flag):
        self.sock.setblocking(flag)

    def recv(self, size):
        chunk = self.sock.recv(size)
        self.received += len(chunk)
        return chunk

    def fileno(self):
        return self.sock.fileno()


def _connected_protocol(sock):
    proto = Protocol("127.0.0.1", 0)
    proto.socket = _CountingSocket(sock)
    proto.connected = True
    proto.first_packet = False
    proto.codec.recv_packet = lambda data: b" " + data + b"\n"
    return proto


def _framed_payload(frame_count):
    return b"".join(struct.pack(">H", 1) + bytes([i % 251])
                    for i in range(frame_count))


def _preload(sock, data):
    offset = 0
    while offset < len(data):
        offset += os.write(sock.fileno(), data[offset:])


def test_single_call_drains_more_than_one_recv_chunk():
    receiver, sender = socket.socketpair()
    try:
        proto = _connected_protocol(receiver)
        wire = _framed_payload(30000)
        assert len(wire) > 65536
        _preload(sender, wire)

        packets = proto.recv_packets(timeout=0)

        assert len(packets) == 30000
        assert proto.socket.received == len(wire)
    finally:
        receiver.close()
        sender.close()


def test_byte_budget_leaves_remainder_for_next_call(monkeypatch):
    receiver, sender = socket.socketpair()
    try:
        budget = 50000
        monkeypatch.setattr(protocol_module, "MAX_SOCKET_DRAIN_BYTES", budget)
        proto = _connected_protocol(receiver)
        wire = _framed_payload(30000)
        _preload(sender, wire)

        first_packets = proto.recv_packets(timeout=0)

        assert proto.socket.received == budget
        assert len(first_packets) < 30000

        second_packets = proto.recv_packets(timeout=0)

        assert len(first_packets) + len(second_packets) == 30000
        assert proto.socket.received == len(wire)
    finally:
        receiver.close()
        sender.close()


def test_clean_eof_marks_protocol_disconnected():
    receiver, sender = socket.socketpair()
    try:
        proto = _connected_protocol(receiver)
        wire = _framed_payload(1)
        _preload(sender, wire)
        sender.close()

        assert proto.recv_packets(timeout=0) == [(0, b"\x00")]
        assert proto.connected is False
    finally:
        receiver.close()
