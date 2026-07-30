"""Regression coverage for interrupted and failed file downloads."""

import pyreborn.client as client_module
from pyreborn import Client
from pyreborn.handlers import files as file_handlers
from pyreborn.packets import PacketID


class _Protocol:
    connected = True

    def connect(self):
        return True


def _client():
    client = Client("localhost", 14900)
    client._protocol = _Protocol()
    return client


def _file_packet(filename, data):
    encoded_name = filename.encode("latin-1")
    return b" " * 5 + bytes([len(encoded_name) + 32]) + encoded_name + data


def _gint5(value):
    return bytes(((value >> shift) & 0x7f) + 32
                 for shift in (28, 21, 14, 7, 0))


def _start(client, filename, expected_size=0):
    client._handle_packet(PacketID.PLO_LARGEFILESTART,
                          filename.encode("latin-1"))
    if expected_size:
        client._handle_packet(PacketID.PLO_LARGEFILESIZE,
                              _gint5(expected_size))


def test_oversize_transfer_discards_remaining_chunks(monkeypatch):
    monkeypatch.setattr(client_module, "MAX_LARGE_FILE_SIZE", 4)
    client = _client()
    filename = "large.bin"
    received = []
    client.on_file = lambda name, data: received.append((name, data))

    client._handle_packet(PacketID.PLO_LARGEFILESTART,
                          filename.encode("latin-1"))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet(filename, b"12345"))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet(filename, b"fragment"))

    assert client._large_file_transfers[filename]["discarding"]
    assert filename not in client._received_files
    assert received == []

    client._handle_packet(PacketID.PLO_LARGEFILEEND,
                          filename.encode("latin-1"))

    assert filename not in client._large_file_transfers
    assert filename not in client._received_files


def test_interleaved_large_files_complete_byte_exact():
    client = _client()
    first = b"a" * 60000 + b"b" * 60000
    second = b"c" * 20000 + b"d" * 20000

    _start(client, "first.bin", len(first))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("first.bin", first[:60000]))
    _start(client, "second.bin", len(second))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("second.bin", second[:20000]))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("first.bin", first[60000:]))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("second.bin", second[20000:]))
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"second.bin")
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"first.bin")

    assert client._received_files["first.bin"] == first
    assert client._received_files["second.bin"] == second


def test_short_announced_transfer_is_not_stored_or_cached():
    client = _client()
    stored = []
    received = []
    client._store_cached_file = lambda *args: stored.append(args)
    client.on_file = lambda *args: received.append(args)
    _start(client, "short.bin", 10)
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("short.bin", b"short"))
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"short.bin")

    assert "short.bin" not in client._received_files
    assert "short.bin" not in client._failed_files
    assert stored == []
    assert received == []


def test_zero_byte_large_file_is_never_stored():
    client = _client()
    stored = []
    client._store_cached_file = lambda *args: stored.append(args)
    _start(client, "empty.bin")
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"empty.bin")

    assert "empty.bin" not in client._received_files
    assert stored == []


def test_same_filename_restart_resets_only_that_transfer():
    client = _client()
    _start(client, "first.bin")
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("first.bin", b"discarded"))
    _start(client, "second.bin")
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("second.bin", b"preserved"))
    _start(client, "first.bin")
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet("first.bin", b"replacement"))
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"first.bin")
    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"second.bin")

    assert client._received_files["first.bin"] == b"replacement"
    assert client._received_files["second.bin"] == b"preserved"


def test_transfer_cap_evicts_oldest_and_accepts_new(monkeypatch):
    monkeypatch.setattr(file_handlers,
                        "MAX_CONCURRENT_LARGE_FILE_TRANSFERS", 2)
    client = _client()
    _start(client, "oldest.bin")
    _start(client, "middle.bin")
    _start(client, "newest.bin")

    assert list(client._large_file_transfers) == [
        "middle.bin", "newest.bin",
    ]


def test_send_failure_callback_and_bounded_retry():
    client = _client()
    filename = "temporary.dat"
    failures = []
    client.on_file_send_failed = failures.append

    for expected_attempt in range(1, 4):
        client._pending_files.add(filename)
        client._handle_packet(PacketID.PLO_FILESENDFAILED,
                              filename.encode("latin-1"))
        assert client._file_attempts[filename] == expected_attempt
        assert filename not in client._pending_files
        assert (filename in client._failed_files) is (expected_attempt == 3)

    assert failures == [filename, filename, filename]


def test_connect_clears_stale_file_transfer_state():
    client = _client()
    client._large_file_transfers["large.bin"] = {
        "buffer": bytearray(b"stale"), "expected_size": 99,
        "modtime": 0, "discarding": False,
    }
    client._pending_files.add("pending.dat")
    client._failed_files.add("failed.dat")
    client._file_attempts["failed.dat"] = 2

    assert client.connect() is True

    assert client._large_file_transfers == {}
    assert client._pending_files == set()
    assert client._failed_files == set()
    assert client._file_attempts == {}


def _failed_packet(filename):
    return filename.encode("latin-1")


def test_server_refused_reports_the_first_refusal_but_did_file_fail_does_not():
    """The two questions are different and were conflated.

    did_file_fail() gates re-requests, so it must stay False while retries
    remain. server_refused() reports what the SERVER said. Reporting only the
    former makes an explicit refusal look identical to a request still in
    flight - which is exactly how a missing fixture got mistaken for a broken
    transfer path.
    """
    client = _client()
    name = "absent.png"

    assert not client.server_refused(name)
    assert not client.did_file_fail(name)

    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    assert client.server_refused(name), "first refusal must be visible"
    assert not client.did_file_fail(name), "still retryable after one refusal"

    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    assert not client.did_file_fail(name), "still retryable after two"

    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    assert client.did_file_fail(name), "written off once the budget is spent"
    assert name in client.failed_files


def test_a_file_that_eventually_arrives_clears_its_strikes():
    """A transient refusal must not leave the name one failure from write-off."""
    client = _client()
    name = "flaky.png"

    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    assert client._file_attempts.get(name) == 2

    client._handle_packet(PacketID.PLO_FILE, _file_packet(name, b"bytes"))
    assert client.get_file(name) == b"bytes"
    assert not client.server_refused(name), "strikes should reset on success"

    # A later refusal starts from zero rather than immediately writing it off.
    client._handle_packet(PacketID.PLO_FILESENDFAILED, _failed_packet(name))
    assert not client.did_file_fail(name)
