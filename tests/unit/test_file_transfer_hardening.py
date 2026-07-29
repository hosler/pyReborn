"""Regression coverage for interrupted and failed file downloads."""

import pyreborn.client as client_module
from pyreborn import Client
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

    assert client._large_file_discarding == filename
    assert filename not in client._received_files
    assert received == []

    client._handle_packet(PacketID.PLO_LARGEFILEEND,
                          filename.encode("latin-1"))

    assert client._large_file_pending is None
    assert client._large_file_discarding is None
    assert filename not in client._received_files


def test_empty_large_file_end_flushes_pending_filename(caplog):
    client = _client()
    filename = "large.bin"
    client._pending_files.add(filename)
    client._handle_packet(PacketID.PLO_LARGEFILESTART,
                          filename.encode("latin-1"))
    client._handle_packet(PacketID.PLO_FILE,
                          _file_packet(filename, b"complete"))

    client._handle_packet(PacketID.PLO_LARGEFILEEND, b"")

    assert client._received_files[filename] == b"complete"
    assert client._large_file_pending is None
    assert filename not in client._pending_files
    assert filename in caplog.text


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
    client._large_file_pending = "large.bin"
    client._large_file_discarding = "discard.bin"
    client._large_file_buffer.extend(b"stale")
    client._large_file_expected_size = 99
    client._pending_files.add("pending.dat")
    client._failed_files.add("failed.dat")
    client._file_attempts["failed.dat"] = 2

    assert client.connect() is True

    assert client._large_file_pending is None
    assert client._large_file_discarding is None
    assert client._large_file_buffer == bytearray()
    assert client._large_file_expected_size == 0
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
