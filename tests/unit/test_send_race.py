"""Regression: concurrent send_packet() must never corrupt the outbound stream.

The GEN_3/4/5 codecs carry a STATEFUL cipher iterator: the order bytes are
encrypted must match the order they hit the wire. Before the fix, send_packet
did `encrypt (advance iterator) ... sendall` with no lock, so two threads could
interleave (wire order != encrypt order) and desync the server's decrypt
stream. The server then reads garbage packet/prop ids. A player-prop id it
cannot map (>=83) makes GServer-v2's constructPropFor throw -> the whole process
SIGABRTs (remote DoS, reproduced live against gs2emu).

This test drives many threads through send_packet against a fake socket that
captures the true wire order (with a tiny sleep to widen the interleave
window), then decodes the captured stream with a single fresh in-codec. If any
send interleaved, decoding desyncs and the recovered packet multiset will not
match what was sent. With the _send_lock in place it always matches.
"""
import threading
import time

import pytest

from reborn_protocol import Gen5Codec
from pyreborn.protocol import Protocol


class _FakeSocket:
    """Captures sendall() bytes in true wire order under its own lock."""
    def __init__(self):
        self._wire = bytearray()
        self._lock = threading.Lock()

    def setblocking(self, _flag):
        pass

    def sendall(self, data):
        # Sleep OUTSIDE the append but INSIDE the caller's critical section:
        # widens the window where an unlocked caller would interleave. The
        # append itself is atomic so the fake never scrambles bytes on its own.
        time.sleep(0.0005)
        with self._lock:
            self._wire.extend(data)


def _decode_stream(wire: bytes, key: int):
    """Split length-prefixed frames and decrypt them in wire order with one
    fresh in-codec, mirroring how the server reads the connection."""
    codec = Gen5Codec(key)
    out = []
    i = 0
    while i + 2 <= len(wire):
        length = (wire[i] << 8) | wire[i + 1]
        i += 2
        frame = bytes(wire[i:i + length])
        i += length
        dec = codec.recv_packet(frame)
        if dec is None:
            raise AssertionError("frame failed to decode (stream desync)")
        out.append(dec)
    assert i == len(wire), "trailing bytes: frame lengths desynced"
    return out


def test_concurrent_send_packet_stream_is_not_corrupted():
    proto = Protocol("127.0.0.1", 0, version="6.037")
    proto.socket = _FakeSocket()
    proto.connected = True
    key = proto.encryption_key

    n_threads = 16
    per_thread = 40
    # Each thread sends distinct, identifiable payloads so we can verify the
    # exact multiset survives. packet_id 6 == PLI_PLAYERPROPS (the real crash
    # carrier); payload byte pattern is unique per (thread, seq).
    expected = []

    def worker(tid):
        for seq in range(per_thread):
            payload = bytes([tid & 0x3F, seq & 0x3F]) * 8
            expected.append(bytes([6 + 32]) + payload + b"\n")
            assert proto.send_packet(6, payload)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    recovered = _decode_stream(bytes(proto.socket._wire), key)

    # Every frame decoded cleanly and the exact payloads round-tripped.
    assert len(recovered) == n_threads * per_thread
    assert sorted(recovered) == sorted(expected)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
