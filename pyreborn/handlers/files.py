"""The client handles file-download packets.

This includes the large-file chunk protocol. Files larger than 32000 bytes
arrive as repeated PLO_FILE chunks between PLO_LARGEFILESTART and
PLO_LARGEFILEEND.
"""

import logging

from ..asset_paths import normalize_asset_name
from ..packets import (
    PacketID,
    parse_file,
    parse_file_uptodate,
    parse_filesendfailed,
    parse_large_file_marker,
    parse_large_file_size,
)
from .registry import handles

logger = logging.getLogger(__name__)

# How many PLO_FILESENDFAILED answers a name absorbs before it is written off
# for the session. One transient refusal used to poison an asset permanently,
# with nothing logged; three strikes with a warning each is the compromise.
_MAX_FILE_ATTEMPTS = 3

# A normal client has only a handful of asset downloads in flight. Sixteen
# leaves room for a burst while bounding the bytearray owners a buggy server
# can create; evicting the oldest lets current traffic recover instead of
# making every later LARGEFILESTART fail behind abandoned transactions.
MAX_CONCURRENT_LARGE_FILE_TRANSFERS = 16


def adopt_gmap(client, filename: str, blob: bytes) -> bool:
    """Build the world grid from a .gmap's bytes. True if the grid was built.

    EVERY path that resolves a .gmap request has to do this, not only the ones
    that transfer bytes. A server answers a revalidation with
    PLO_FILEUPTODATE and sends nothing, so on the second run against a gmap
    server - once the file is in the download cache - the transfer branches
    below never fire. Without this the client keeps `gmap_width == 0`, no
    neighbouring segment is ever requested, and the player cannot walk off the
    edge of their own level: the world is one lone segment with nothing
    stitched to it.
    """
    try:
        client.load_gmap(blob.decode('latin-1', errors='replace'))
    except Exception:
        return False
    client.gmap_name = filename
    # Now that the grid is known, pull in the neighbouring segments so the
    # world renders stitched instead of a lone current segment.
    client.request_adjacent_levels()
    return True


def _large_file_caps():
    """Return (absolute cap, announced-size slack) for an active large transfer.

    The function reads the values from pyreborn.client at call time. Client.py
    owns both constants. Tests/unit/test_security_correctness.py monkeypatches
    MAX_LARGE_FILE_SIZE in that module.
    """
    from .. import client as client_module
    return client_module.MAX_LARGE_FILE_SIZE, client_module.LARGE_FILE_SIZE_SLACK


@handles(PacketID.PLO_FILE)
def handle_file(client, data):
    # File transfer
    file_info = parse_file(data, no_modtime=client._file_no_modtime)
    if file_info and file_info['filename']:
        filename = file_info['filename']
        file_data = file_info['data']
        mod_time = file_info['mod_time']

        # Files over 32000 bytes arrive as repeated PLO_FILE chunks
        # bracketed by PLO_LARGEFILESTART/...END (each chunk resends
        # the full modtime+filename header - see
        # server/src/player/Player.cpp Player::sendFile). Append
        # rather than overwrite while a large transfer is in flight.
        transfer = client._large_file_transfers.get(filename)
        if transfer is not None:
            if transfer['discarding']:
                return
            if not transfer['buffer']:
                transfer['modtime'] = mod_time
            max_size, size_slack = _large_file_caps()
            new_size = len(transfer['buffer']) + len(file_data)
            announced_limit = transfer['expected_size'] + size_slack
            if (new_size > max_size
                    or (transfer['expected_size'] > 0
                        and new_size > announced_limit)):
                logger.warning(
                    "Aborting oversized file transfer for %r", filename)
                transfer['discarding'] = True
                transfer['buffer'] = bytearray()
                transfer['expected_size'] = 0
                client._failed_files.add(filename)
                client._pending_files.discard(filename)
            else:
                transfer['buffer'].extend(file_data)
        else:
            client._received_files[filename] = file_data
            client._store_cached_file(filename, file_data, mod_time)
            client._pending_files.discard(filename)
            # Arrived, so earlier refusals were transient - drop the strikes
            # rather than leaving the name one failure from being written off.
            client._file_attempts.pop(filename, None)
            # A downloaded .gmap file is the world grid - parse it.
            if filename.endswith('.gmap'):
                adopt_gmap(client, filename, file_data)
            if client.on_file:
                client.on_file(filename, file_data)


@handles(PacketID.PLO_FILESENDFAILED)
def handle_file_send_failed(client, data):
    # File send failed
    filename = parse_filesendfailed(data)
    if filename:
        client._pending_files.discard(filename)
        attempts = client._file_attempts.get(filename, 0) + 1
        client._file_attempts[filename] = attempts
        # _failed_files means "written off, stop asking" - it is what gates
        # re-requests. A refusal only lands there once the retry budget is
        # spent; until then the name stays requestable. Callers that want
        # "did the server say no at all" ask Client.server_refused().
        if attempts >= _MAX_FILE_ATTEMPTS:
            client._failed_files.add(filename)
            logger.warning(
                "Server refused file %r (%d attempts) - giving up",
                filename, attempts)
        else:
            logger.warning(
                "Server refused file %r (attempt %d of %d)",
                filename, attempts, _MAX_FILE_ATTEMPTS)
        if client.on_file_send_failed:
            client.on_file_send_failed(filename)


@handles(PacketID.PLO_LARGEFILESTART)
def handle_large_file_start(client, data):
    # Large file transfer starts (packet 68) - subsequent PLO_FILE chunks
    # for this filename must be appended, not treated as complete files.
    filename = parse_large_file_marker(data)
    transfers = client._large_file_transfers
    # Reassignment alone preserves dict order. Pop first so a same-name
    # restart is both a clean reset and the target of the filename-less SIZE
    # packet which immediately follows START.
    transfers.pop(filename, None)
    if len(transfers) >= MAX_CONCURRENT_LARGE_FILE_TRANSFERS:
        evicted = next(iter(transfers))
        transfers.pop(evicted)
        logger.warning(
            "Evicting oldest incomplete large file transfer for %r", evicted)
    transfers[filename] = {
        'buffer': bytearray(),
        'expected_size': 0,
        'modtime': 0,
        'discarding': False,
    }


@handles(PacketID.PLO_LARGEFILESIZE)
def handle_large_file_size(client, data):
    # Large file total size (packet 84) - informational, arrives right
    # after LARGEFILESTART. The packet has no filename, so insertion order
    # identifies the start it belongs to even while older files keep flowing.
    if client._large_file_transfers:
        filename = next(reversed(client._large_file_transfers))
        client._large_file_transfers[filename]['expected_size'] = (
            parse_large_file_size(data))


@handles(PacketID.PLO_LARGEFILEEND)
def handle_large_file_end(client, data):
    # Large file transfer ends (packet 69) - only the named transaction can
    # complete. The old global slot let one file's END flush another's bytes.
    filename = parse_large_file_marker(data)
    transfer = client._large_file_transfers.pop(filename, None)
    if transfer is None:
        return
    if transfer['discarding']:
        return
    file_data = bytes(transfer['buffer'])
    expected_size = transfer['expected_size']
    if not file_data or (expected_size > 0 and len(file_data) != expected_size):
        # A short image once reached both the persistent cache and the
        # renderer's never-retry set, shadowing a good user copy on every
        # later run. Leave the request retryable and never publish uncertain
        # bytes to either consumer.
        logger.warning(
            "Discarding incomplete large file transfer for %r: "
            "received %d bytes, expected %d",
            filename, len(file_data), expected_size)
        client._pending_files.discard(filename)
        return
    mod_time = transfer['modtime']
    client._received_files[filename] = file_data
    client._store_cached_file(filename, file_data, mod_time)
    client._pending_files.discard(filename)
    client._file_attempts.pop(filename, None)
    if filename.endswith('.gmap'):
        adopt_gmap(client, filename, file_data)
    if client.on_file:
        client.on_file(filename, file_data)


@handles(PacketID.PLO_FILEUPTODATE)
def handle_file_uptodate(client, data):
    # Server confirms our cached copy is current (packet 45) - resolves a
    # request_file_if_modified() call with no data transfer.
    filename = parse_file_uptodate(data)
    if filename:
        cached = client.get_file(filename)
        # The answer to a .gmap revalidation carries no bytes, so this is the
        # only place the grid can be built on a warm cache (see adopt_gmap).
        if cached and filename.endswith('.gmap'):
            adopt_gmap(client, filename, cached)
        client._uptodate_files.add(filename)
        key = normalize_asset_name(filename)
        for pending_name in list(client._pending_files):
            if normalize_asset_name(pending_name) == key:
                client._pending_files.discard(pending_name)
        if client.on_file_uptodate:
            client.on_file_uptodate(filename)


@handles(PacketID.PLO_UPDATEPACKAGEISUPDATED)
def handle_update_package_is_updated(client, data):
    """Invalidate a file named by a server-side update notification."""
    filename = data.decode('latin-1', errors='replace')
    if filename:
        client._invalidate_cached_file(filename)
