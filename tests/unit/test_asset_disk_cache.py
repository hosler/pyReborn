"""Persistent download-cache and conditional-request coverage."""

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


def test_completed_download_is_cached_with_modtime(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()

    client._handle_packet(
        PacketID.PLO_FILE,
        _file_packet("Levels/Example.PNG", b"asset bytes", 123456),
    )

    directory = server_cache_dir(client.host, client.port)
    assert (directory / "example.png").read_bytes() == b"asset bytes"
    assert json.loads((directory / "index.json").read_text()) == {
        "example.png": 123456
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


def test_malformed_index_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True)
    (directory / "index.json").write_text("{bad json")
    (directory / "image.png").write_bytes(b"still usable")

    assert client.get_file("image.png") == b"still usable"
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
