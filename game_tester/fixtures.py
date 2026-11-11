"""Provision QA fixture files in a directory and take them out again.

A fixture a run drops into a server world used to stay behind, and nothing
removed it. `FixtureFile` owns the whole lifecycle so every caller leaves the
tree as it found it:

- a file that already has the right bytes is left alone, and never removed;
- a file with other bytes is replaced, and its original bytes come back;
- a missing file is written, and removed again;
- a directory the fixture had to create is removed too, but only if the
  fixture created it and it is empty by then;
- a symlink at the fixture path is never written through: `install()` refuses
  it (`refused` is set and the caller reports the fixture unprovisioned).

`release()` also refuses to touch a file whose content changed since
`install()`: somebody else owns those bytes now.

Two things have to survive the process, so they live on disk, in the QA state
directory (`$PYREBORN_QA_SERVERS_DIR`, the same one qa_server uses), in one
small JSON file per fixture path:

- the bytes of a replaced original, written BEFORE the fixture overwrites it,
  so a killed run cannot lose the user's file. The next `install()` of that
  path restores a leftover whose owners are all dead before it does anything
  else;
- the owner list (pid + token). Two runs may share one levels directory. The
  file goes away only when its last live owner releases; a second run
  therefore never mistakes the first run's copy for a pre-existing one.

`to_dict()` / `from_dict()` let a manager (game_tester.qa_server) keep the
record across processes, so `qa_server stop` can clean up what `start` made.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import uuid
from typing import Iterator, List, Optional

log = logging.getLogger(__name__)

_MEMO_LIMIT = 1 << 20           # an original larger than this is not kept in memory


def state_dir() -> Path:
    return Path(os.environ.get(
        "PYREBORN_QA_SERVERS_DIR", "~/.local/state/pyreborn/qa_servers")).expanduser().resolve()


def _read_stat(pid: int) -> Optional[str]:
    """The raw /proc/<pid>/stat line, or None where /proc is missing."""
    try:
        return (Path("/proc") / str(pid) / "stat").read_text()
    except OSError:
        return None


def _stat_fields(pid: int) -> Optional[list]:
    """Fields 3.. of the stat line (state first), or None when unreadable."""
    try:
        return _read_stat(pid).rsplit(")", 1)[1].split()
    except (AttributeError, IndexError):
        return None


def _start_time(pid: int) -> Optional[int]:
    """Start time of `pid` in clock ticks (stat field 22), if /proc has it."""
    fields = _stat_fields(pid)
    try:
        return int(fields[19])
    except (TypeError, IndexError, ValueError):
        return None


def _alive(pid: int, start: Optional[int] = None) -> bool:
    """`start` is the owner's recorded start time. A different start time on
    the same pid means the pid was reused, so the owner is dead."""
    fields = _stat_fields(pid)
    if fields is not None:
        if fields[0] in ("Z", "X"):
            return False
        if start is not None:
            current = _start_time(pid)
            if current is not None and current != start:
                return False
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True             # exists, but not ours to signal
    return True


def _write_atomic(path: Path, data: bytes, token: str) -> None:
    """Write through a temp file next to `path`, so a kill never leaves a torn file."""
    temporary = path.with_name(f".{path.name}.{token}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class FixtureFile:
    def __init__(self, directory, name: str, data: bytes):
        self.directory = Path(directory)
        self.name = name
        self.data = bytes(data)
        self.token = uuid.uuid4().hex           # this owner's id in the marker
        self.pid = os.getpid()                  # liveness of this owner
        self.installed = False
        self.refused = False                    # a symlink sits at the path
        self.state = state_dir()                # where the marker lives
        self._memo: Optional[dict] = None       # in-process copy of the marker we created

    @property
    def path(self) -> Path:
        return self.directory / self.name

    # -- on-disk ownership marker ---------------------------------------------

    def _marker_dir(self) -> Path:
        return self.state / "fixture-owners"

    def _marker(self) -> Path:
        real = Path(os.path.realpath(self.directory)) / self.name   # not the symlink route
        key = hashlib.sha1(str(real).encode()).hexdigest()
        return self._marker_dir() / f"{key}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._marker_dir().mkdir(parents=True, exist_ok=True)
        with (self._marker_dir() / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _owner(self, pid: int) -> dict:
        return dict(token=self.token, pid=pid, start=_start_time(pid))

    def _load(self) -> Optional[dict]:
        """The marker with dead owners dropped, or None when there is none or it
        is unreadable. A malformed one keeps whatever backup it still holds."""
        try:
            marker = json.loads(self._marker().read_text())
            if not isinstance(marker, dict):
                raise ValueError("marker is not an object")
            original = marker.get("original")
            if original is not None:
                base64.b64decode(original, validate=True)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as error:
            log.warning("fixture marker %s unreadable (%s); ignored", self._marker(), error)
            return None
        owners = []
        for owner in marker.get("owners") or ():
            if not isinstance(owner, dict) or not isinstance(owner.get("token"), str) \
                    or not isinstance(owner.get("pid"), int):
                continue
            start = owner.get("start")
            if owner["token"] == self.token or _alive(
                    owner["pid"], start if isinstance(start, int) else None):
                owners.append(owner)
        marker["owners"] = owners
        created = marker.get("created_dirs")
        marker["created_dirs"] = [d for d in created if isinstance(d, str)] \
            if isinstance(created, list) else []
        return marker

    def _save(self, marker: dict) -> None:
        temporary = self._marker().with_suffix(".tmp")
        temporary.write_text(json.dumps(marker))
        temporary.replace(self._marker())

    def _undo(self, marker: dict, force: bool = False) -> bool:
        """Put the path back as `marker` found it. True when anything changed.
        `force` skips the content check: our own write failed half-way."""
        path = self.path
        changed = False
        try:
            if not path.is_symlink() and path.is_file() and (
                    force or path.read_bytes() == self.data):
                original = marker.get("original")
                if original is not None:
                    _write_atomic(path, base64.b64decode(original), self.token)
                else:
                    path.unlink()
                changed = True
        except OSError:
            pass
        for directory in reversed(marker.get("created_dirs", ())):
            try:
                Path(directory).rmdir()             # only succeeds when empty
            except OSError:
                break
        self._marker().unlink(missing_ok=True)
        return changed

    # -- lifecycle --------------------------------------------------------------

    def install(self) -> bool:
        """Make the fixture present. True when the file on disk was changed."""
        path = self.path
        if path.is_symlink():
            self.refused = True
            return False
        with self._locked():
            marker = self._load()
            if marker is not None and not marker["owners"]:
                self._undo(marker)      # a killed run's leftovers come back first
                marker = None
            if marker is not None:      # a live run already provisioned this path
                marker["owners"].append(self._owner(self.pid))
                self._save(marker)
                self.installed = True
                if path.is_file() and path.read_bytes() == self.data:
                    return False
                try:
                    _write_atomic(path, self.data, self.token)
                except BaseException:
                    self.installed = False
                    marker["owners"] = [o for o in marker["owners"] if o["token"] != self.token]
                    self._save(marker)
                    raise
                return True
            if path.is_file() and path.read_bytes() == self.data:
                return False            # pre-existing and identical: never ours
            missing = []
            probe = self.directory
            while not probe.exists():
                missing.append(probe)
                if probe.parent == probe:
                    break
                probe = probe.parent
            original = path.read_bytes() if path.is_file() else None
            marker = dict(
                created_dirs=[str(p) for p in reversed(missing)],
                original=(None if original is None
                          else base64.b64encode(original).decode("ascii")),
                owners=[self._owner(self.pid)])
            self._save(marker)          # the backup is on disk before the overwrite
            self.installed = True
            if original is None or len(original) <= _MEMO_LIMIT:
                self._memo = dict(marker)       # lets release() undo if the marker vanishes
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                _write_atomic(path, self.data, self.token)
            except BaseException:
                self.installed = False
                self._undo(marker, force=True)      # a half-written file goes too
                raise
            return True

    def adopt(self, pid: int) -> None:
        """Hand ownership's liveness to `pid` (the server that serves the file)."""
        self.pid = pid
        if not self.installed:
            return
        with self._locked():
            marker = self._load()
            for owner in (marker or {}).get("owners", ()):
                if owner["token"] == self.token:
                    owner.update(self._owner(pid))
                    self._save(marker)

    def release(self) -> bool:
        """Undo install(). True when anything was removed or restored."""
        if not self.installed:
            return False
        self.installed = False
        with self._locked():
            marker = self._load()
            if marker is None and self._memo is not None:
                return self._undo(self._memo)   # the marker vanished: undo from memory
            if marker is None or all(o["token"] != self.token for o in marker["owners"]):
                return False            # already released, or not ours any more
            marker["owners"] = [o for o in marker["owners"] if o["token"] != self.token]
            if marker["owners"]:
                self._save(marker)      # another live run still needs the file
                return False
            return self._undo(marker)

    def to_dict(self) -> dict:
        return dict(directory=str(self.directory), name=self.name,
                    data=base64.b64encode(self.data).decode("ascii"),
                    installed=self.installed, token=self.token, pid=self.pid,
                    state_dir=str(self.state))

    @classmethod
    def from_dict(cls, record: dict) -> "FixtureFile":
        fixture = cls(record["directory"], record["name"],
                      base64.b64decode(record["data"]))
        fixture.installed = bool(record.get("installed"))
        fixture.token = record.get("token", fixture.token)
        fixture.pid = record.get("pid", fixture.pid)
        fixture.state = Path(record.get("state_dir", fixture.state))
        return fixture


@contextmanager
def provisioned_file(directory, name: str, data: bytes) -> Iterator[FixtureFile]:
    """Install a fixture for the duration of a block, even if the block raises."""
    fixture = FixtureFile(directory, name, data)
    try:
        fixture.install()
        yield fixture
    finally:
        fixture.release()


def release_all(records) -> int:
    """Release fixtures recorded as dicts (see qa_server). Returns how many
    files were removed or restored."""
    count = 0
    for record in records or ():
        try:
            count += FixtureFile.from_dict(record).release()
        except (OSError, KeyError, ValueError):
            continue
    return count
