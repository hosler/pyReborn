"""Update-package (.gupd) progress tracking.

Mirrors the reference client's package events: PLO_UPDATEPACKAGESIZE starts a
package (TClient.cpp:2772-2787, 5518-5534), every PLO_FILE chunk of a file the
package lists adds to its progress (:2565-2578), PLO_UPDATEPACKAGEDONE marks it
downloaded and fires onUpdatePackageDownloaded, then onPackagesDownloadComplete
once nothing is outstanding (:2116-2150), and a failed .gupd fires
onUpdatePackageFailed (:2368-2370).

Everything a server can drive is bounded: MAX_UPDATE_PACKAGES tracked packages,
UPDATE_PACKAGE_FILES_MAX FILE slots each, UPDATE_PACKAGE_NAME_MAX bytes of
name, GUPD_BYTES_MAX bytes of .gupd text (the last three live in
packet_codec/files.py), and MAX_REQUESTED_FILES remembered file requests.
"""

import logging
import zlib
from dataclasses import dataclass, field
from typing import List, Set

from .asset_paths import normalize_asset_name
from .client_callbacks import emit
from .packet_codec.files import (
    UPDATE_PACKAGE_NAME_MAX,
    gupd_name_reserved,
    parse_gupd,
    parse_update_package_done,
    parse_update_package_size,
)

logger = logging.getLogger(__name__)

MAX_UPDATE_PACKAGES = 32
MAX_REQUESTED_FILES = 4096
#: Seconds without a 105, a file chunk or a 106 before a requested package is
#: written off as failed (expire_stalled). A server that never answers a 159
#: would otherwise leave the package "downloading" forever.
PACKAGE_STALL_TIMEOUT = 120.0


@dataclass
class UpdatePackage:
    """One package's download state: `size` bytes announced by PLO 105,
    `received` bytes of its files seen since, `done` after PLO 106."""
    name: str
    size: int = 0
    received: int = 0
    done: bool = False
    failed: bool = False
    downloading: bool = False   # True only after OUR 159 went out
    files: List[str] = field(default_factory=list)
    blocked: Set[int] = field(default_factory=set)
    names: Set[str] = field(default_factory=set)  # normalised `files`
    last_activity: float = 0.0

    def as_dict(self) -> dict:
        return {'size': self.size, 'received': self.received,
                'done': self.done}


def track_package(client, name: str):
    """Return the tracked package for `name`, creating it unless the table is
    full or the name is unusable (None)."""
    packages = client._update_packages
    package = packages.get(name)
    if package is not None:
        return package
    if (not name or len(name) > UPDATE_PACKAGE_NAME_MAX
            or len(packages) >= MAX_UPDATE_PACKAGES):
        logger.warning("update package table full or name unusable: %.40r",
                       name)
        return None
    package = packages[name] = UpdatePackage(name)
    return package


def load_package_files(client, package: UpdatePackage, data: bytes) -> None:
    """Fill `package.files` from .gupd bytes."""
    parsed = parse_gupd(data)
    package.files = parsed['files']
    package.blocked = parsed['blocked']
    package.names = {normalize_asset_name(f) for f in package.files}
    if parsed['truncated']:
        logger.warning("update package %r truncated while parsing", package.name)


def gupd_arrived(client, filename: str, data: bytes) -> None:
    """A .gupd landed through the ordinary file path: track and parse it
    (FourPlay TClient.cpp:2024-2027)."""
    package = track_package(client, filename)
    if package is not None:
        load_package_files(client, package, data)


def file_chunk(client, filename: str, length: int) -> None:
    """Add one PLO_FILE chunk to the package this client requested that lists
    the file. Only packages with our own request in flight count, and the
    lookup is one set membership per such package."""
    key = normalize_asset_name(filename)
    for package in client._update_packages.values():
        if package.downloading and not package.done and key in package.names:
            package.received += length
            package.last_activity = client.clock.frame_now()
            emit(client, 'on_update_package_progress',
                 package.name, package.received, package.size)
            return


def handle_package_size(client, data: bytes) -> None:
    parsed = parse_update_package_size(data)
    if parsed is None:
        return
    name, size = parsed
    package = client._update_packages.get(name)
    if package is None or not package.downloading or package.done:
        return  # not asked for by us (reference: create=false -> ignored)
    package.size = size
    package.received = 0
    package.last_activity = client.clock.frame_now()
    emit(client, 'on_update_package_progress', name, 0, size)


def handle_package_done(client, data: bytes) -> None:
    name = parse_update_package_done(data)
    package = client._update_packages.get(name)
    if package is None or not package.downloading:
        return
    package.done = True
    package.downloading = False
    emit(client, 'on_update_package_downloaded', name)
    if not any(p.downloading for p in client._update_packages.values()):
        emit(client, 'on_packages_download_complete')


def _fail(client, package: UpdatePackage) -> None:
    package.failed = True
    package.downloading = False
    emit(client, 'on_update_package_failed', package.name)


def cancel_package(client, name: str) -> bool:
    """Give up on a requested package: it becomes failed (and fires
    on_update_package_failed). False if it was not downloading."""
    package = client._update_packages.get(name)
    if package is None or not package.downloading:
        return False
    _fail(client, package)
    return True


def expire_stalled(client, now: float = None) -> list:
    """Fail every downloading package idle for PACKAGE_STALL_TIMEOUT seconds.
    Client.update() calls this every frame. Returns the names expired."""
    now = client.clock.frame_now() if now is None else now
    candidates = [p for p in client._update_packages.values()
                  if p.downloading
                  and now - p.last_activity >= PACKAGE_STALL_TIMEOUT]
    expired = []
    for package in candidates:
        # A failed-callback may have re-requested this package: test again.
        if not (package.downloading
                and now - package.last_activity >= PACKAGE_STALL_TIMEOUT):
            continue
        logger.warning("update package %r stalled for %.0fs; giving up",
                       package.name, PACKAGE_STALL_TIMEOUT)
        _fail(client, package)
        expired.append(package.name)
    return expired


def gupd_failed(client, filename: str) -> None:
    """The server refused a .gupd (PLO_FILESENDFAILED). Like the reference,
    stay quiet while another .gupd is still on its way (unsorted.cpp:996-1002).
    """
    package = client._update_packages.get(filename)
    if package is not None:
        package.failed = True
        package.downloading = False
    if any(str(n).lower().endswith('.gupd') for n in client._pending_files):
        return
    emit(client, 'on_update_package_failed', filename)


def note_requested(client, filename: str) -> None:
    key = normalize_asset_name(filename)
    if key:
        client._requested_files[key] = True


def was_requested(client, filename: str) -> bool:
    return normalize_asset_name(filename) in client._requested_files


def file_crc(client, filename: str):
    """CRC32 of a file we hold, or None when we do not have it (or the name
    is reserved). Reads through peek_file: a server-chosen name must never
    make the cache delete anything."""
    if gupd_name_reserved(filename):
        return None
    data = client.peek_file(filename)
    if data is None:
        return None
    return zlib.crc32(data) & 0xFFFFFFFF
