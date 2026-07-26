"""File-download packets, including the large-file chunk protocol (files over
32000 bytes arrive as repeated PLO_FILE chunks bracketed by
PLO_LARGEFILESTART/PLO_LARGEFILEEND).
"""

import logging

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


def _large_file_caps():
    """(absolute cap, announced-size slack) for an in-flight large transfer.

    Read from pyreborn.client at call time rather than imported: client.py owns
    both constants and tests/unit/test_security_correctness.py monkeypatches
    MAX_LARGE_FILE_SIZE on that module.
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

        # Files over 32000 bytes arrive as repeated PLO_FILE chunks
        # bracketed by PLO_LARGEFILESTART/...END (each chunk resends
        # the full modtime+filename header - see
        # server/src/player/Player.cpp Player::sendFile). Append
        # rather than overwrite while a large transfer is in flight.
        if client._large_file_pending == filename:
            max_size, size_slack = _large_file_caps()
            new_size = len(client._large_file_buffer) + len(file_data)
            announced_limit = (
                client._large_file_expected_size + size_slack)
            if (new_size > max_size
                    or (client._large_file_expected_size > 0
                        and new_size > announced_limit)):
                logger.warning(
                    "Aborting oversized file transfer for %r", filename)
                client._large_file_pending = None
                client._large_file_buffer = bytearray()
                client._large_file_expected_size = 0
                client._failed_files.add(filename)
                client._pending_files.discard(filename)
            else:
                client._large_file_buffer.extend(file_data)
        else:
            client._received_files[filename] = file_data
            client._pending_files.discard(filename)
            # A downloaded .gmap file is the world grid - parse it.
            if filename.endswith('.gmap'):
                try:
                    client.load_gmap(file_data.decode('latin-1', errors='replace'))
                    client.gmap_name = filename
                    # Now that the grid is known, pull in the neighbouring
                    # segments so the world renders stitched instead of a
                    # lone current segment.
                    client.request_adjacent_levels()
                except Exception:
                    pass
            if client.on_file:
                client.on_file(filename, file_data)


@handles(PacketID.PLO_FILESENDFAILED)
def handle_file_send_failed(client, data):
    # File send failed
    filename = parse_filesendfailed(data)
    if filename:
        client._failed_files.add(filename)
        client._pending_files.discard(filename)


@handles(PacketID.PLO_LARGEFILESTART)
def handle_large_file_start(client, data):
    # Large file transfer starts (packet 68) - subsequent PLO_FILE chunks
    # for this filename must be appended, not treated as complete files.
    filename = parse_large_file_marker(data)
    client._large_file_pending = filename
    client._large_file_buffer = bytearray()
    client._large_file_expected_size = 0


@handles(PacketID.PLO_LARGEFILESIZE)
def handle_large_file_size(client, data):
    # Large file total size (packet 84) - informational, arrives right
    # after LARGEFILESTART.
    client._large_file_expected_size = parse_large_file_size(data)


@handles(PacketID.PLO_LARGEFILEEND)
def handle_large_file_end(client, data):
    # Large file transfer ends (packet 69) - flush the accumulated
    # buffer through the same path a normal PLO_FILE download takes.
    filename = parse_large_file_marker(data)
    if client._large_file_pending == filename:
        file_data = bytes(client._large_file_buffer)
        client._large_file_pending = None
        client._large_file_buffer = bytearray()
        client._large_file_expected_size = 0
        client._received_files[filename] = file_data
        client._pending_files.discard(filename)
        if filename.endswith('.gmap'):
            try:
                client.load_gmap(file_data.decode('latin-1', errors='replace'))
                client.gmap_name = filename
                client.request_adjacent_levels()
            except Exception:
                pass
        if client.on_file:
            client.on_file(filename, file_data)


@handles(PacketID.PLO_FILEUPTODATE)
def handle_file_uptodate(client, data):
    # Server confirms our cached copy is current (packet 45) - resolves a
    # request_file_if_modified() call with no data transfer.
    filename = parse_file_uptodate(data)
    if filename:
        client._uptodate_files.add(filename)
        client._pending_files.discard(filename)
        if client.on_file_uptodate:
            client.on_file_uptodate(filename)
