"""Update packages (.gupd): PLI 159, PLO 105 / 106 / 187.

Wire vectors come from the 2026-11-11 oracle notes (GServer-v2 origin/beta4
PlayerClientPackets.cpp:1548-1595; client side Preagonal/FourPlay TClient.cpp:
263-339 and TUpdatePackage.cpp:327-471). Vectors here omit the leading packet
id byte, the way a handler receives them.
"""

import zlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyreborn import Client
from pyreborn import update_packages as up
from pyreborn.packets import (
    GUPD_BYTES_MAX, PacketID, UPDATE_PACKAGE_FILES_MAX,
    build_update_package_request, parse_gupd, parse_update_package_done,
    parse_update_package_size,
)

REQUEST_159 = bytes.fromhex("29 62 61 73 65 2e 67 75 70 64 21"
                            " 2d 95 56 9d 8f 20 20 20 20 20")
SIZE_105 = bytes.fromhex("29 62 61 73 65 2e 67 75 70 64 20 20 20 27 88")
DONE_106 = bytes.fromhex("62 61 73 65 2e 67 75 70 64")
IS_UPDATED_187 = bytes.fromhex("78 2e 70 6e 67")

GUPD = (b"GRPKG001\nNAME base\nVERSION 1.0\nFILE levels/a.png\n"
        b"FILE b.gani\nFILE sub\\a.png\nfile c.txt\nFILE start.exe\n")


def _client():
    client = Client('localhost', 14900)
    client._authenticated = True
    client._protocol = SimpleNamespace(connected=True,
                                       send_packet=Mock(return_value=True))
    return client


def _chunk(name, data):
    return (bytes([32] * 5) + bytes([len(name) + 32]) + name.encode() + data)


# -- codec ---------------------------------------------------------------

def test_159_vector():
    assert build_update_package_request(
        'base.gupd', False, [0xDEADBEEF, None]) == REQUEST_159


def test_159_reinstall_is_type_2_and_blocked_slot():
    out = build_update_package_request('p.gupd', True, [None, 'blocked'])
    assert out == b'&p.gupd"' + b'     ' + b'    !'


def test_105_vector():
    assert parse_update_package_size(SIZE_105) == ('base.gupd', 1000)


@pytest.mark.parametrize('data', [b'', b' ', bytes([32 + 9]) + b'short',
                                  bytes([32 + 9]) + b'base.gupd' + b'  '])
def test_105_truncated_is_rejected(data):
    assert parse_update_package_size(data) is None


def test_106_vector_and_bounds():
    assert parse_update_package_done(DONE_106) == 'base.gupd'
    assert parse_update_package_done(b'') == ''
    assert parse_update_package_done(b'x' * 224) == ''


def test_gupd_file_lines():
    parsed = parse_gupd(GUPD)
    # basename only, repeated basename keeps its first slot, case-insensitive
    # FILE keyword, and the exe keeps a (blocked) slot
    assert parsed['files'] == ['a.png', 'b.gani', 'c.txt', 'start.exe']
    assert parsed['blocked'] == {3}


def test_gupd_needs_the_header_line():
    assert parse_gupd(b"FILE a.png\n")['files'] == []


def test_gupd_caps():
    many = b"GRPKG001\n" + b"".join(b"FILE f%d.png\n" % i for i in range(2000))
    parsed = parse_gupd(many)
    assert len(parsed['files']) == UPDATE_PACKAGE_FILES_MAX
    assert parsed['truncated']
    huge = b"GRPKG001\n" + b"#" * (GUPD_BYTES_MAX + 10) + b"\nFILE late.png\n"
    assert parse_gupd(huge)['files'] == []
    assert parse_gupd(b"GRPKG001\nFILE " + b"x" * 600 + b"\n")['files'] == []


# -- client flow -----------------------------------------------------------

def test_gupd_arrival_parses_and_request_sends_crc_in_file_order():
    client = _client()
    client._handle_packet(PacketID.PLO_FILE, _chunk('base.gupd', GUPD))
    package = client.get_update_package('base.gupd')
    assert package.files == ['a.png', 'b.gani', 'c.txt', 'start.exe']
    client._received_files['a.png'] = b'png-bytes'
    client._received_files['c.txt'] = b'text'

    assert client.request_update_package('base.gupd')

    pid, payload = client._protocol.send_packet.call_args.args
    assert pid == PacketID.PLI_UPDATEPACKAGEREQUESTFILE
    expected = build_update_package_request(
        'base.gupd', False,
        [zlib.crc32(b'png-bytes'), None, zlib.crc32(b'text'), 'blocked'])
    assert payload == expected
    assert payload.startswith(b'\x29base.gupd!')


def test_reinstall_blanks_every_slot():
    client = _client()
    client._handle_packet(PacketID.PLO_FILE, _chunk('base.gupd', GUPD))
    client._received_files['a.png'] = b'png-bytes'
    client.request_update_package('base.gupd', reinstall=True)
    payload = client._protocol.send_packet.call_args.args[1]
    assert payload == (b'\x29base.gupd"' + b'     ' * 3 + b'    !')


def test_request_offline_or_bad_name_sends_nothing():
    client = _client()
    assert not client.request_update_package('')
    assert not client.request_update_package('x' * 224)
    client._authenticated = False
    assert not client.request_update_package('base.gupd')
    client._protocol.send_packet.assert_not_called()


def test_events_progress_downloaded_complete():
    client = _client()
    events = []
    client.on_update_package_progress = lambda *a: events.append(('p',) + a)
    client.on_update_package_downloaded = lambda n: events.append(('d', n))
    client.on_packages_download_complete = lambda: events.append(('c',))
    client._handle_packet(PacketID.PLO_FILE, _chunk('base.gupd', GUPD))
    client.request_update_package('base.gupd')

    client._handle_packet(PacketID.PLO_UPDATEPACKAGESIZE, SIZE_105)
    client._handle_packet(PacketID.PLO_FILE, _chunk('a.png', b'x' * 300))
    client._handle_packet(PacketID.PLO_FILE, _chunk('other.png', b'y' * 50))
    package = client.get_update_package('base.gupd')
    assert package.as_dict() == {'size': 1000, 'received': 300, 'done': False}
    assert events == [('p', 'base.gupd', 0, 1000),
                      ('p', 'base.gupd', 300, 1000)]

    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, DONE_106)
    assert package.done
    assert events[-2:] == [('d', 'base.gupd'), ('c',)]


def test_complete_waits_for_every_downloading_package():
    client = _client()
    done = []
    client.on_packages_download_complete = lambda: done.append(1)
    client.request_update_package('a.gupd')
    client.request_update_package('b.gupd')
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, b'a.gupd')
    assert done == []
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, b'b.gupd')
    assert done == [1]


def test_unrequested_package_packets_are_ignored():
    client = _client()
    client._handle_packet(PacketID.PLO_UPDATEPACKAGESIZE, SIZE_105)
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, DONE_106)
    assert client._update_packages == {}


def test_failed_gupd_fires_once_nothing_else_pending():
    client = _client()
    failed = []
    client.on_update_package_failed = failed.append
    client._pending_files.add('other.gupd')
    client._handle_packet(PacketID.PLO_FILESENDFAILED, b'base.gupd')
    assert failed == []           # another .gupd is still on its way
    client._pending_files.discard('other.gupd')
    client._handle_packet(PacketID.PLO_FILESENDFAILED, b'base.gupd')
    assert failed == ['base.gupd']
    client._handle_packet(PacketID.PLO_FILESENDFAILED, b'x.png')
    assert failed == ['base.gupd']


def test_package_table_is_bounded():
    client = _client()
    for index in range(up.MAX_UPDATE_PACKAGES + 10):
        client._handle_packet(PacketID.PLO_FILE,
                              _chunk('p%d.gupd' % index, GUPD))
    assert len(client._update_packages) == up.MAX_UPDATE_PACKAGES
    assert not client.request_update_package('late.gupd')


def test_187_rerequests_only_files_this_session_asked_for():
    client = _client()
    client._received_files['x.png'] = b'old'
    client._received_files['y.png'] = b'old'
    client.request_file_if_modified('x.png', 5)        # asked for it
    client._protocol.send_packet.reset_mock()

    client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, IS_UPDATED_187)
    assert 'x.png' not in client._received_files       # cache dropped
    pid, payload = client._protocol.send_packet.call_args.args
    assert (pid, payload) == (PacketID.PLI_WANTFILE, b'x.png')

    client._protocol.send_packet.reset_mock()
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, b'y.png')
    assert 'y.png' not in client._received_files       # still invalidated
    client._protocol.send_packet.assert_not_called()   # but never requested


def test_187_oversized_name_is_dropped():
    client = _client()
    client._received_files['z'] = b'1'
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, b'z' * 300)
    assert client._received_files['z'] == b'1'


def test_reconnect_resets_package_state():
    client = _client()
    client.request_update_package('a.gupd')
    client.request_file('x.png')
    client._reset_file_transfer_state()
    assert client._update_packages == {} and len(client._requested_files) == 0


# -- review fixes ------------------------------------------------------------

def test_reserved_names_keep_their_slot_but_are_never_hashed(
        tmp_path, monkeypatch):
    """`FILE index.json` used to make request_update_package delete the
    client's own cache index (get_file found no per-file metadata and
    invalidated it)."""
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    from pyreborn.asset_paths import server_cache_dir
    client = _client()
    client.host = 'evil.example'
    directory = server_cache_dir('evil.example', 14900)
    directory.mkdir(parents=True, exist_ok=True)
    client._store_cached_file('real.png', b'x' * 10, 5)
    index = directory / 'index.json'
    index.write_bytes(b'{}')   # a file the package must not be able to touch
    gupd = (b"GRPKG001\nFILE index.json\nFILE real.png\nFILE ..\nFILE .hid\n"
            b"FILE a\x00b\n")
    client._handle_packet(PacketID.PLO_FILE, _chunk('p.gupd', gupd))
    client._cache_index = None

    assert parse_gupd(gupd)['blocked'] == {0, 2, 3, 4}
    assert client.request_update_package('p.gupd')

    assert index.exists() and (directory / 'real.png').exists()
    payload = client._protocol.send_packet.call_args.args[1]
    real = zlib.crc32(b'x' * 10)
    assert payload == build_update_package_request(
        'p.gupd', False, ['blocked', real, 'blocked', 'blocked', 'blocked'])


def test_peek_file_never_invalidates(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    from pyreborn.asset_paths import server_cache_dir
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'orphan.png').write_bytes(b'no metadata')
    assert client.peek_file('orphan.png') is None
    assert (directory / 'orphan.png').exists()


def test_unsolicited_package_cannot_start_or_count_progress():
    client = _client()
    complete = []
    client.on_packages_download_complete = lambda: complete.append(1)
    client._handle_packet(PacketID.PLO_FILE, _chunk('base.gupd', GUPD))
    package = client.get_update_package('base.gupd')   # tracked, not requested
    client._handle_packet(PacketID.PLO_UPDATEPACKAGESIZE, SIZE_105)
    assert not package.downloading and package.size == 0
    client._handle_packet(PacketID.PLO_FILE, _chunk('a.png', b'x' * 10))
    assert package.received == 0
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, DONE_106)
    assert not package.done and complete == []


def test_chunk_lookup_is_one_normalisation_per_chunk(monkeypatch):
    client = _client()
    for i in range(up.MAX_UPDATE_PACKAGES):
        client._handle_packet(PacketID.PLO_FILE, _chunk(
            'p%d.gupd' % i, b"GRPKG001\n" + b"".join(
                b"FILE f%d_%d.png\n" % (i, j) for j in range(512))))
    client.request_update_package('p0.gupd')
    calls = []
    real = up.normalize_asset_name
    monkeypatch.setattr(up, 'normalize_asset_name',
                        lambda n: calls.append(n) or real(n))
    up.file_chunk(client, 'zz.png', 5)
    assert len(calls) == 1


def test_failed_send_leaves_the_package_untouched():
    client = _client()
    client._protocol.send_packet.return_value = False
    assert not client.request_update_package('a.gupd')
    package = client.get_update_package('a.gupd')
    assert not package.downloading


def test_stalled_package_fails_after_the_timeout_and_unblocks_completion(
        monkeypatch):
    client = _client()
    failed, complete = [], []
    client.on_update_package_failed = failed.append
    client.on_packages_download_complete = lambda: complete.append(1)
    clock = [1000.0]
    monkeypatch.setattr(up, '_now', lambda: clock[0])
    client.request_update_package('a.gupd')
    client.request_update_package('b.gupd')
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, b'a.gupd')
    assert complete == []                      # b is still outstanding

    clock[0] += up.PACKAGE_STALL_TIMEOUT - 1
    assert up.expire_stalled(client) == []
    clock[0] += 1
    assert up.expire_stalled(client) == ['b.gupd']
    assert failed == ['b.gupd']
    package = client.get_update_package('b.gupd')
    assert package.failed and not package.downloading

    # a later request starts clean and completes normally
    client.request_update_package('b.gupd')
    client._handle_packet(PacketID.PLO_UPDATEPACKAGEDONE, b'b.gupd')
    assert complete == [1]


def test_progress_resets_the_stall_clock_and_update_expires(monkeypatch):
    client = _client()
    failed = []
    client.on_update_package_failed = failed.append
    clock = [0.0]
    monkeypatch.setattr(up, '_now', lambda: clock[0])
    client._handle_packet(PacketID.PLO_FILE, _chunk('base.gupd', GUPD))
    client.request_update_package('base.gupd')
    clock[0] = up.PACKAGE_STALL_TIMEOUT - 1
    client._handle_packet(PacketID.PLO_FILE, _chunk('a.png', b'x'))
    clock[0] = up.PACKAGE_STALL_TIMEOUT + 50
    assert up.expire_stalled(client) == []
    clock[0] += up.PACKAGE_STALL_TIMEOUT
    client._protocol.recv_packets = lambda timeout=0.01: []
    client.update()                       # the per-frame hook
    assert failed == ['base.gupd']


def test_cancel_reports_failed():
    client = _client()
    failed = []
    client.on_update_package_failed = failed.append
    client.request_update_package('a.gupd')
    assert client.cancel_update_package('a.gupd')
    assert failed == ['a.gupd']
    assert not client.cancel_update_package('a.gupd')


def test_failed_callback_that_rerequests_is_not_failed_twice():
    client = _client()
    fired = []

    def on_failed(name):
        fired.append(name)
        client.request_update_package('b.gupd')       # retry the other one

    client.on_update_package_failed = on_failed
    client.request_update_package('a.gupd')
    client.request_update_package('b.gupd')
    for package in client._update_packages.values():
        package.last_activity -= 1000

    assert up.expire_stalled(client) == ['a.gupd']
    assert fired == ['a.gupd']
    assert client.get_update_package('b.gupd').downloading


def test_187_never_touches_the_cache_index_or_unknown_names(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    from pyreborn.asset_paths import server_cache_dir
    client = _client()
    directory = server_cache_dir(client.host, client.port)
    directory.mkdir(parents=True, exist_ok=True)
    client._store_cached_file('real.png', b'x', 1)
    assert (directory / 'index.json').exists()

    for name in (b'index.json', b'INDEX.JSON', b'.hidden', b'never-cached.png'):
        client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, name)
    assert (directory / 'index.json').exists()
    assert (directory / 'real.png').exists()

    client._handle_packet(PacketID.PLO_UPDATEPACKAGEISUPDATED, b'real.png')
    assert not (directory / 'real.png').exists()       # a real entry goes
    assert (directory / 'index.json').exists()


def test_a_server_cannot_store_over_the_index():
    client = _client()
    client._store_cached_file('index.json', b'{"x": 1}', 1)
    assert 'index.json' not in client._load_cache_index()
