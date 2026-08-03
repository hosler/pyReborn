"""Content-verified download-cache and conditional-request coverage."""

import hashlib
import json

from pyreborn import Client
from pyreborn.asset_paths import normalize_asset_name, server_cache_dir
from pyreborn.packets import PacketID


class _Protocol:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((packet_id, data))
        return True


def _client(host="example.test", port=14900):
    client = Client(host, port)
    client._protocol = _Protocol()
    client._authenticated = True
    return client


def _file_packet(filename, data, mod_time):
    encoded_name = filename.encode("latin-1")
    encoded_time = []
    for shift in (28, 21, 14, 7, 0):
        encoded_time.append(((mod_time >> shift) & 0x7f) + 32)
    return (
        bytes(encoded_time)
        + bytes([len(encoded_name) + 32])
        + encoded_name
        + data
    )


def test_completed_download_is_cached_with_verified_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()

    client._handle_packet(
        PacketID.PLO_FILE,
        _file_packet("Levels/Example.PNG", b"asset bytes", 123456),
    )

    directory = server_cache_dir(client.host, client.port)
    assert (directory / "example.png").read_bytes() == b"asset bytes"
    assert json.loads((directory / "index.json").read_text()) == {
        "example.png": {
            "modtime": 123456,
            "size": 11,
            "sha256": hashlib.sha256(b"asset bytes").hexdigest(),
        }
    }


def test_second_session_reads_cached_file_without_network(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"persisted", 42)
    )
    second = _client()

    assert second.get_file("IMAGE.PNG") == b"persisted"
    assert second.has_file("image.png")
    assert second._protocol.sent == []


def test_unusable_cache_degrades_to_memory_only(tmp_path, monkeypatch):
    cache_root = tmp_path / "not-a-directory"
    cache_root.write_bytes(b"occupied")
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(cache_root))
    client = _client()

    client._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"in memory", 7)
    )

    assert client.get_file("image.png") == b"in memory"
    assert "image.png" not in client._pending_files


def test_malformed_index_is_ignored_and_disk_bytes_are_not_trusted(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True)
    (directory / "index.json").write_text("{bad json")
    (directory / "image.png").write_bytes(b"still usable")

    assert client.get_file("image.png") is None
    assert client._cached_file_modtime("image.png") is None


def test_file_uptodate_resolves_conditional_request_from_disk(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"cached", 99)
    )
    second = _client()

    assert second.request_file("image.png")
    assert second._protocol.sent[0][0] == PacketID.PLI_UPDATEFILE
    assert "image.png" in second._pending_files

    second._received_files.clear()
    second._handle_packet(PacketID.PLO_FILEUPTODATE, b"image.png")

    assert "image.png" not in second._pending_files
    assert second.get_file("image.png") == b"cached"


def test_update_notification_invalidates_memory_and_disk(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()
    client._handle_packet(
        PacketID.PLO_FILE, _file_packet("Folder/Image.PNG", b"old", 10)
    )

    client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, b"image.png")

    key = normalize_asset_name("image.png")
    assert key not in client._received_files
    assert not (server_cache_dir(client.host, client.port) / key).exists()
    assert key not in client._load_cache_index()


def test_same_length_tamper_is_rejected_and_requested_in_full(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"original", 77)
    )
    directory = server_cache_dir(first.host, first.port)
    (directory / "image.png").write_bytes(b"tampered")

    second = _client()
    assert second.get_file("image.png") is None
    assert second.request_file("image.png")
    assert second._protocol.sent[0][0] == PacketID.PLI_WANTFILE
    assert not (directory / "image.png").exists()


def test_truncated_cached_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"complete", 9)
    )
    directory = server_cache_dir(first.host, first.port)
    (directory / "image.png").write_bytes(b"short")

    assert _client().get_file("image.png") is None
    assert not (directory / "image.png").exists()


def test_zero_byte_payload_is_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()

    client._store_cached_file("empty.png", b"", 4)

    directory = server_cache_dir(client.host, client.port)
    assert not (directory / "empty.png").exists()
    assert not (directory / "index.json").exists()


def test_legacy_modtime_entry_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True)
    (directory / "image.png").write_bytes(b"uncertified")
    (directory / "index.json").write_text(json.dumps({"image.png": 42}))

    assert client.get_file("image.png") is None
    assert client._cached_file_modtime("image.png") is None
    assert not (directory / "image.png").exists()


def test_malformed_index_entries_are_dropped_without_raising(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True)
    (directory / "index.json").write_text(json.dumps({
        "bad-size.png": {"modtime": 1, "size": "no", "sha256": "0" * 64},
        "bad-hash.png": {"modtime": 1, "size": 2, "sha256": "not-a-hash"},
        "Folder.PNG": {
            "modtime": 1,
            "size": 2,
            "sha256": "0" * 64,
        },
    }))

    assert client._load_cache_index() == {}


def test_disk_verification_runs_once_per_name(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("image.png", b"cached", 99)
    )
    second = _client()
    real_sha256 = hashlib.sha256
    calls = 0

    def counted_sha256(data):
        nonlocal calls
        calls += 1
        return real_sha256(data)

    # client_files.py is what digests cached payloads; patch it there rather
    # than via pyreborn.client, which no longer touches hashlib at all.
    monkeypatch.setattr("pyreborn.client_files.hashlib.sha256", counted_sha256)
    assert second.get_file("image.png") == b"cached"
    assert second.get_file("image.png") == b"cached"
    assert calls == 1


_GMAP = (
    "GRMAP001\n"
    "WIDTH 2\nHEIGHT 1\n"
    "LEVELNAMES\n"
    '"a.nw","b.nw"\n'
    "LEVELNAMESEND\n"
)


def test_uptodate_gmap_still_builds_the_world_grid(tmp_path, monkeypatch):
    """A revalidated .gmap carries no bytes, and the grid still has to appear.

    The transfer branches only run when the server SENDS the file, so on the
    second run against a gmap server the client kept gmap_width == 0, asked
    for no neighbouring segment, and the player could not walk off the edge of
    their own level.
    """
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    first = _client()
    first._handle_packet(
        PacketID.PLO_FILE, _file_packet("world.gmap", _GMAP.encode(), 7)
    )
    assert first.gmap_width == 2, "sanity: the transfer path builds the grid"

    second = _client()
    second.request_file("world.gmap")
    second._received_files.clear()

    second._handle_packet(PacketID.PLO_FILEUPTODATE, b"world.gmap")

    assert second.gmap_name == "world.gmap"
    assert (second.gmap_width, second.gmap_height) == (2, 1)
    assert sorted(second.gmap_grid.values()) == ["a.nw", "b.nw"]
    assert any(packet_id == PacketID.PLI_ADJACENTLEVEL
               for packet_id, _ in second._protocol.sent), \
        "the neighbours have to be requested, or the world stays one segment"
