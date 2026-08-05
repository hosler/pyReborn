"""Client FileTransferMixin methods."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from .asset_paths import normalize_asset_name, server_cache_dir
from .packets import (
    PacketID, build_board_modify, build_update_class, build_update_file,
    build_update_gani, build_update_script, build_wantfile,
)

class FileTransferMixin:
    def modify_board(self, x: int, y: int, width: int, height: int, tiles) -> bool:
        """
        Edit a rectangle of the current level's board (PLI_BOARDMODIFY).

        Args:
            x, y: top-left tile coordinate of the edit (0-63)
            width, height: size of the edit rectangle
            tiles: flat list of width*height raw tile ids, row-major

        Returns:
            True if the packet was sent. The server does NOT echo the change
            back to the sender (sendPacketToOneLevelPart/sendPacketToNearby
            exclude the originating player id - see
            PlayerClientPackets.cpp msgPLI_BOARDMODIFY), only to other
            players on the level, so this applies the edit to our own cached
            board immediately (matching real client behavior of editing
            optimistically rather than waiting for a self-echo that never
            arrives).
        """
        if not self.connected or not self._authenticated:
            return False
        if len(tiles) < width * height:
            return False

        # The level the SERVER will apply this to is the one the player is
        # standing in (its own `self.level`), so the optimistic local patch
        # has to use that same level - segment-aware, because on a gmap the
        # board is one segment. It used to read _pending_level_name first,
        # but that is stream-routing state: an adjacent-level PRELOAD moves
        # it without moving the player, and the edit then patched the
        # preloaded neighbour's cached board while the painter's own view
        # never changed.
        level_name = (self.get_current_level_from_position()
                      or self._current_level_name)
        if level_name:
            self._apply_board_modify(level_name, {
                'layer': 0, 'x': x, 'y': y, 'width': width, 'height': height,
                'tiles': list(tiles[:width * height]),
            })

        data = build_board_modify(x, y, width, height, tiles)
        return self._protocol.send_packet(PacketID.PLI_BOARDMODIFY, data)

    def request_weapon_bytecode(self, weapon_name: str) -> bool:
        """Request a weapon's GS2 bytecode (PLI_UPDATESCRIPT). Reply arrives
        as PLO_NPCWEAPONSCRIPT -> client.gs2_bytecode['weapon'][name]."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_script(weapon_name)
        return self._protocol.send_packet(PacketID.PLI_UPDATESCRIPT, data)

    def request_gani_bytecode(self, gani_name: str, checksum: int = 0) -> bool:
        """Request a gani's GS2 bytecode (PLI_UPDATEGANI. Name without .gani).
        Replies: PLO_GANISCRIPT (if checksum differs) + PLO_LOADGANI."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_gani(gani_name, checksum)
        return self._protocol.send_packet(PacketID.PLI_UPDATEGANI, data)

    def request_class_bytecode(self, class_name: str, checksum: int = 0) -> bool:
        """Request a script class's GS2 bytecode (PLI_UPDATECLASS). Reply
        arrives as PLO_LOADSCRIPT -> client.gs2_bytecode['class'][name]."""
        if not self.connected or not self._authenticated:
            return False
        data = build_update_class(class_name, checksum)
        return self._protocol.send_packet(PacketID.PLI_UPDATECLASS, data)

    def request_level(self, level_name: str) -> bool:
        """
        Request an adjacent GMAP level.

        Args:
            level_name: Name of the level to request (e.g., "chicken2.nw")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Build packet: GUInt5 (modtime=0) + level name
        data = bytearray()
        # modtime = 0, encoded as 5 GCHARs
        for _ in range(5):
            data.append(32)  # 0 + 32
        data.extend(level_name.encode('latin-1'))

        sent = self._protocol.send_packet(PacketID.PLI_ADJACENTLEVEL, data)
        if sent:
            self._adjacent_level_requests.add(level_name)
        return sent

    def request_file(self, filename: str) -> bool:
        """
        Request a file from the server.

        Args:
            filename: Name of the file to request (e.g., "image.png")

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        cached_data = self.get_file(filename)
        cached_modtime = self._cached_file_modtime(filename)
        if cached_data is not None and cached_modtime is not None:
            return self.request_file_if_modified(filename, cached_modtime)

        self._pending_files.add(filename)
        data = build_wantfile(filename)
        return self._protocol.send_packet(PacketID.PLI_WANTFILE, data)

    def request_file_if_modified(self, filename: str, mod_time: int) -> bool:
        """Ask the server to send a file only when its cached copy is stale."""
        if not self.connected or not self._authenticated:
            return False

        self._pending_files.add(filename)
        data = build_update_file(filename, mod_time)
        return self._protocol.send_packet(PacketID.PLI_UPDATEFILE, data)

    def get_file(self, filename: str) -> Optional[bytes]:
        """
        Get a previously downloaded file.

        Args:
            filename: Name of the file

        Returns:
            File data as bytes, or None if not downloaded
        """
        data = self._received_files.get(filename)
        if data is not None:
            return data

        key = normalize_asset_name(filename)
        if not key:
            return None
        data = self._received_files.get(key)
        if data is not None:
            return data
        try:
            data = (server_cache_dir(self.host, self.port) / key).read_bytes()
        except (OSError, ValueError, TypeError):
            return None
        try:
            metadata = self._load_cache_index().get(key)
            # The server modtime only describes what SHOULD be in this path.
            # A truncated pics1.png once remained at modtime 0 forever and,
            # because the download tier wins path lookup, hid a good user
            # copy. Legacy integers deliberately fail this check: hashing and
            # blessing their existing bytes would certify the corruption this
            # metadata is meant to detect.
            if (
                not isinstance(metadata, dict)
                or len(data) != metadata.get("size")
                or hashlib.sha256(data).hexdigest() != metadata.get("sha256")
            ):
                self._invalidate_cached_file(filename)
                return None
        except (OSError, ValueError, TypeError):
            self._invalidate_cached_file(filename)
            return None
        # This is both the byte cache and the verification verdict. Later hot
        # SpriteManager/GaniParser reads return above without touching disk or
        # hashing again; bytes placed here by a wire handler are trusted too.
        self._received_files[filename] = data
        self._received_files[key] = data
        return data

    def has_file(self, filename: str) -> bool:
        """Check if a file has been downloaded."""
        return self.get_file(filename) is not None

    def _load_cache_index(self) -> Dict[str, object]:
        """Load this server's advisory cache metadata once for the session."""
        if self._cache_index is not None:
            return self._cache_index

        index = {}
        try:
            raw = json.loads(
                (server_cache_dir(self.host, self.port) / "index.json").read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(raw, dict):
                for key, value in raw.items():
                    key = str(key)
                    if normalize_asset_name(key) != key:
                        continue
                    try:
                        if isinstance(value, dict):
                            modtime = int(value["modtime"])
                            size = int(value["size"])
                            digest = value["sha256"]
                            if (
                                size < 0
                                or not isinstance(digest, str)
                                or len(digest) != 64
                                or any(c not in "0123456789abcdef" for c in digest)
                            ):
                                continue
                            index[key] = {
                                "modtime": modtime,
                                "size": size,
                                "sha256": digest,
                            }
                        # Retain legacy metadata only so loading old indexes is
                        # harmless. get_file() refuses it, preventing upgrade
                        # from blessing bytes that may already be poisoned.
                        elif not isinstance(value, bool):
                            index[key] = int(value)
                    except (KeyError, ValueError, TypeError):
                        continue
        except (OSError, ValueError, TypeError):
            pass
        self._cache_index = index
        return index

    def _cached_file_modtime(self, filename: str) -> Optional[int]:
        """Return stored server metadata for a cached file, when available."""
        key = normalize_asset_name(filename)
        if not key:
            return None
        metadata = self._load_cache_index().get(key)
        if not isinstance(metadata, dict):
            return None
        return metadata.get("modtime")

    @staticmethod
    def _atomic_cache_write(path: Path, data: bytes) -> None:
        """Replace one cache file without exposing a partially written copy."""
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
            os.replace(temporary_name, path)
            temporary_name = None
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def _store_cached_file(
        self, filename: str, file_data: bytes, mod_time: int
    ) -> None:
        """Persist a completed download, ignoring every cache failure."""
        if not self.persist_downloads:
            return
        key = normalize_asset_name(filename)
        # Empty assets are not legitimate downloads. A zero-byte tileset from
        # a cut-off large transfer was persisted and then shadowed a good user
        # copy across every restart, so never create that artifact again.
        if not key or not file_data:
            return
        try:
            directory = server_cache_dir(self.host, self.port)
            directory.mkdir(parents=True, exist_ok=True)
            self._atomic_cache_write(directory / key, file_data)
            index = self._load_cache_index()
            index[key] = {
                "modtime": int(mod_time),
                "size": len(file_data),
                "sha256": hashlib.sha256(file_data).hexdigest(),
            }
            encoded = json.dumps(index, sort_keys=True).encode("utf-8")
            self._atomic_cache_write(directory / "index.json", encoded)
        except (OSError, ValueError, TypeError):
            pass

    def _invalidate_cached_file(self, filename: str) -> None:
        """Discard memory and disk copies after a server update notice."""
        key = normalize_asset_name(filename)
        if not key:
            return
        for received_name in list(self._received_files):
            if normalize_asset_name(received_name) == key:
                self._received_files.pop(received_name, None)
        try:
            (server_cache_dir(self.host, self.port) / key).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        try:
            index = self._load_cache_index()
            if key not in index:
                return
            index.pop(key, None)
            directory = server_cache_dir(self.host, self.port)
            encoded = json.dumps(index, sort_keys=True).encode("utf-8")
            self._atomic_cache_write(directory / "index.json", encoded)
        except (OSError, ValueError, TypeError):
            pass

    def is_file_pending(self, filename: str) -> bool:
        """Check if a file download is pending."""
        return filename in self._pending_files

    def did_file_fail(self, filename: str) -> bool:
        """True once a file has been written off and will not be re-requested.

        A single refusal is NOT enough - see server_refused() if you want to
        know whether the server said no at all. This is the gate the asset
        layer checks before re-asking, so it deliberately stays False while
        retries remain.
        """
        return filename in self._failed_files

    def server_refused(self, filename: str) -> bool:
        """True if the server has answered PLO_FILESENDFAILED at least once.

        Distinct from did_file_fail(): this reports the server's answer, that
        reports our decision to stop asking. A caller diagnosing "why is this
        asset missing" wants this one - otherwise an explicit refusal is
        indistinguishable from a request still in flight.
        """
        return self._file_attempts.get(filename, 0) > 0

    @property
    def failed_files(self) -> set:
        """Filenames written off after exhausting their retry budget."""
        return self._failed_files
