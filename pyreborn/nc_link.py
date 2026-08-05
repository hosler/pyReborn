"""Run an NPC Control client on a worker thread for in-game tools."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Optional, Tuple

from .nc_client import NCClient
from .packets import PacketID

logger = logging.getLogger(__name__)

NC_PROOF_TIMEOUT = 6.0
NC_REQUEST_TIMEOUT = 6.0
MAX_NOTICES = 60

# The weapon and level lists, level dumps, and weapon replies are NC query
# results that an ordinary game session is never sent. NPC and class replies
# are likewise emitted only on the NC surface when an NPC server is running.
# NC status chat also qualifies: the server sends it specifically to announce
# NC login and operation results, rather than as ordinary player chat.
_EVIDENCE_IDS = frozenset({
    PacketID.PLO_NC_WEAPONLISTGET, PacketID.PLO_NC_LEVELLIST,
    PacketID.PLO_NC_LEVELDUMP, PacketID.PLO_NC_WEAPONGET,
    PacketID.PLO_NC_NPCATTRIBUTES, PacketID.PLO_NC_NPCADD,
    PacketID.PLO_NC_NPCDELETE, PacketID.PLO_NC_NPCSCRIPT,
    PacketID.PLO_NC_NPCFLAGS, PacketID.PLO_NC_CLASSGET,
    PacketID.PLO_NC_CLASSADD, PacketID.PLO_NC_CLASSDELETE,
    PacketID.PLO_RC_CHAT,
})

IDLE = "idle"
CONNECTING = "connecting"
READY = "ready"
DENIED = "denied"
ERROR = "error"
CLOSED = "closed"


@dataclass(frozen=True)
class NCSnapshot:
    """An immutable state copy that the render thread may safely retain."""

    state: str = IDLE
    status: str = ""
    account: str = ""
    npcs: Tuple[Tuple[int, Dict[str, Any]], ...] = ()
    npc_attributes: Tuple[Tuple[int, Tuple[str, ...]], ...] = ()
    npc_scripts: Tuple[Tuple[int, str], ...] = ()
    npc_flags: Tuple[Tuple[int, Tuple[str, ...]], ...] = ()
    local_npcs: Tuple[Tuple[str, str], ...] = ()
    weapons: Tuple[str, ...] = ()
    weapon_list_loaded: bool = False
    last_weapon: Dict[str, Any] = field(default_factory=dict)
    classes: Tuple[str, ...] = ()
    class_list_loaded: bool = False
    last_class: Dict[str, Any] = field(default_factory=dict)
    levels: Tuple[str, ...] = ()
    notices: Tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.state == READY

    @property
    def weapon_list(self) -> Tuple[str, ...]:
        return self.weapons

    @property
    def class_list(self) -> Tuple[str, ...]:
        return self.classes

    @property
    def level_list(self) -> Tuple[str, ...]:
        return self.levels


class _LinkedNCClient(NCClient):
    """NC client that records proof of type acceptance, and keeps EVERY reply.

    `NCClient` keeps only the LAST script/flags reply (`_last_npc_script`,
    `_last_npc_flags`), which is fine for a caller that asks for one thing at
    a time. The link is not that caller: an export asks for every NPC's
    script at once, and a single `update()` can deliver a dozen replies. Read
    afterwards, eleven of them are already gone. So each reply is banked HERE,
    as the packet arrives, and `_rebuild_snapshot` reads the banks.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saw_nc_packet = False
        self.weapon_list_loaded = False
        self.class_list_loaded = False
        self.npc_attributes: Dict[int, Tuple[str, ...]] = {}
        self.npc_scripts: Dict[int, str] = {}
        self.npc_flags: Dict[int, Tuple[str, ...]] = {}
        self.local_npcs: Dict[str, str] = {}
        self._npc_attribute_requests: deque[int] = deque()
        self._local_npc_requests: deque[str] = deque()
        self._npc_attribute_outstanding: Optional[Tuple[float, int]] = None
        self._local_npc_outstanding: Optional[Tuple[float, str]] = None

    def get_npc(self, npc_id: int) -> bool:
        self._npc_attribute_requests.append(npc_id)
        self.pump_correlated_requests()
        return True

    def get_local_npcs(self, level: str) -> bool:
        self._local_npc_requests.append(level)
        self.pump_correlated_requests()
        return True

    def pump_correlated_requests(self) -> None:
        """Expire dead sends, then allow one wire request of each kind."""
        now = time.monotonic()
        if (self._npc_attribute_outstanding is not None
                and now - self._npc_attribute_outstanding[0]
                >= NC_REQUEST_TIMEOUT):
            self._npc_attribute_outstanding = None
        if (self._local_npc_outstanding is not None
                and now - self._local_npc_outstanding[0]
                >= NC_REQUEST_TIMEOUT):
            self._local_npc_outstanding = None

        if (self._npc_attribute_outstanding is None
                and self._npc_attribute_requests):
            npc_id = self._npc_attribute_requests.popleft()
            if super().get_npc(npc_id):
                self._npc_attribute_outstanding = (now, npc_id)
            else:
                self._npc_attribute_requests.appendleft(npc_id)
        if (self._local_npc_outstanding is None
                and self._local_npc_requests):
            level = self._local_npc_requests.popleft()
            if super().get_local_npcs(level):
                self._local_npc_outstanding = (now, level)
            else:
                self._local_npc_requests.appendleft(level)

    def _handle_packet(self, packet_id: int, data: bytes):
        if packet_id in _EVIDENCE_IDS:
            self.saw_nc_packet = True
        super()._handle_packet(packet_id, data)

        if packet_id == PacketID.PLO_NC_WEAPONLISTGET:
            self.weapon_list_loaded = True
            # Class names are startup announcements rather than a separately
            # queryable list. The requested weapon-list reply is the ordered
            # startup barrier after those announcements, including none.
            self.class_list_loaded = True

        if (packet_id == PacketID.PLO_NC_NPCATTRIBUTES
                and self._npc_attribute_outstanding is not None):
            _requested_at, npc_id = self._npc_attribute_outstanding
            self._npc_attribute_outstanding = None
            self.npc_attributes[npc_id] = tuple(self._last_npc_attributes)
        elif (packet_id == PacketID.PLO_NC_LEVELDUMP
              and self._local_npc_outstanding is not None):
            _requested_at, level = self._local_npc_outstanding
            self._local_npc_outstanding = None
            self.local_npcs[level] = self._last_level_dump
        elif packet_id == PacketID.PLO_NC_NPCSCRIPT:
            record = self._last_npc_script or {}
            if record.get("id") is not None:
                self.npc_scripts[int(record["id"])] = str(
                    record.get("script", ""))
        elif packet_id == PacketID.PLO_NC_NPCFLAGS:
            record = self._last_npc_flags or {}
            if record.get("id") is not None:
                self.npc_flags[int(record["id"])] = tuple(
                    record.get("flags", ()))

        # A reply after we timed out its exact request can still race the next
        # send; without a correlation id on the wire that ambiguity is
        # unavoidable. Serializing requests makes this the only such window.
        self.pump_correlated_requests()


class NCLink:
    """A background NPC Control session with queued, non-blocking commands."""

    def __init__(self, host: str, port: int, account: str, password: str,
                 version: str = "6.037"):
        self.host = host
        self.port = port
        self.account = account
        self._password = password
        self.version = version
        self._lock = threading.Lock()
        self._commands: "queue.Queue[Callable[[NCClient], None]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._notices: deque = deque(maxlen=MAX_NOTICES)
        self._npc_attributes: Dict[int, Tuple[str, ...]] = {}
        self._npc_scripts: Dict[int, str] = {}
        self._npc_flags: Dict[int, Tuple[str, ...]] = {}
        self._local_npcs: Dict[str, str] = {}
        self._snapshot = NCSnapshot(account=account)

    @property
    def snapshot(self) -> NCSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def state(self) -> str:
        return self.snapshot.state

    @property
    def available(self) -> bool:
        return self.state == READY

    @property
    def started(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        """Start or reconnect, except after a definitive access denial."""
        if self.state == DENIED:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._password:
            self._set_state(DENIED, "no password available for an NC login")
            return
        self._clear_commands()
        with self._lock:
            self._snapshot = replace(
                self._snapshot, weapons=(), weapon_list_loaded=False,
                classes=(), class_list_loaded=False)
        stop_event = threading.Event()
        self._stop = stop_event
        self._set_state(CONNECTING, f"connecting to {self.host}:{self.port}...")
        self._thread = threading.Thread(target=self._run, args=(stop_event,), name="pyreborn-nc",
                                        daemon=True)
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is not None and not thread.is_alive():
            self._thread = None

    def _run(self, stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or self._stop
        nc: Optional[_LinkedNCClient] = None
        try:
            nc = _LinkedNCClient(self.host, self.port, self.version)
            nc.on_nc_message = self._note
            if not nc.connect():
                if stop_event.is_set():
                    return
                self._set_state(ERROR, "could not open an NC connection")
                return
            if not nc.login(self.account, self._password, timeout=15.0):
                if stop_event.is_set():
                    return
                reason = nc.disconnect_reason or "server refused the NC login"
                self._set_state(DENIED, reason)
                return
            proof = self._await_nc_proof(nc, stop_event)
            if proof is not True:
                if stop_event.is_set():
                    return
                if proof is None:
                    self._set_state(CLOSED, "NC connection dropped")
                    return
                self._set_state(DENIED, "this account has no NC access on this server")
                return
            self._set_state(READY, "NC session active")
            self._pump_until_stopped(nc, stop_event)
        except Exception as exc:  # noqa: BLE001 - a dead staff link is isolated
            logger.warning("NC link failed: %s", exc, exc_info=True)
            self._set_state(ERROR, f"{type(exc).__name__}: {exc}")
        finally:
            self._clear_commands()
            if nc is not None:
                try:
                    nc.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            if self.state in (CONNECTING, READY):
                self._set_state(CLOSED, "NC session closed")

    def _await_nc_proof(self, nc: _LinkedNCClient,
                        stop_event: Optional[threading.Event] = None) -> Optional[bool]:
        """Wait for an NC-only packet; authentication alone proves nothing."""
        nc.get_weapon_list()
        nc.get_level_list()
        stop_event = stop_event or self._stop
        deadline = time.time() + NC_PROOF_TIMEOUT
        while time.time() < deadline and not stop_event.is_set():
            nc.update(timeout=0.1)
            if nc.saw_nc_packet:
                return True
            if not nc.connected:
                return None
        return False

    def _pump_until_stopped(self, nc: _LinkedNCClient,
                            stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or self._stop
        while not stop_event.is_set():
            if not nc.connected:
                self._set_state(CLOSED, "NC connection dropped")
                return
            self._drain_commands(nc)
            nc.pump_correlated_requests()
            nc.update(timeout=0.05)
            self._rebuild_snapshot(nc)

    def _drain_commands(self, nc: NCClient) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                command(nc)
            except Exception as exc:  # noqa: BLE001 - one edit must not end NC
                logger.warning("NC command failed: %s", exc, exc_info=True)
                self._note(f"command failed: {type(exc).__name__}: {exc}")

    def _clear_commands(self) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def _note(self, text: str) -> None:
        with self._lock:
            self._notices.append(text)
            self._snapshot = replace(self._snapshot, notices=tuple(self._notices))

    def _set_state(self, state: str, status: str) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, state=state, status=status)

    def _rebuild_snapshot(self, nc: NCClient) -> None:
        # Scripts and flags come from the banks the client fills as each
        # packet arrives (see _LinkedNCClient): polling the "last reply"
        # fields here dropped every reply but one whenever a batch of them
        # landed inside the same update().
        self._npc_attributes.update(getattr(nc, "npc_attributes", {}))
        self._npc_scripts.update(getattr(nc, "npc_scripts", {}))
        self._npc_flags.update(getattr(nc, "npc_flags", {}))
        self._local_npcs.update(getattr(nc, "local_npcs", {}))
        npcs = tuple((npc_id, dict(values))
                     for npc_id, values in sorted(nc.npcs.items()))
        with self._lock:
            self._snapshot = NCSnapshot(
                state=self._snapshot.state, status=self._snapshot.status,
                account=self.account, npcs=npcs,
                npc_attributes=tuple(sorted(self._npc_attributes.items())),
                npc_scripts=tuple(sorted(self._npc_scripts.items())),
                npc_flags=tuple(sorted(self._npc_flags.items())),
                local_npcs=tuple(sorted(self._local_npcs.items())),
                weapons=tuple(nc._weapon_list),
                weapon_list_loaded=getattr(nc, "weapon_list_loaded", False),
                last_weapon=dict(nc._last_weapon), classes=tuple(nc.classes),
                class_list_loaded=getattr(nc, "class_list_loaded", False),
                last_class=dict(nc._last_class),
                levels=tuple(nc._level_list), notices=tuple(self._notices))

    def _submit(self, fn: Callable[[NCClient], None]) -> bool:
        if self.state != READY:
            return False
        self._commands.put(fn)
        return True

    def ping_npcs(self) -> bool:
        return self._submit(lambda nc: nc.ping_npcs())

    def get_npc(self, npc_id: int) -> bool:
        return self._submit(lambda nc: nc.get_npc(npc_id))

    def delete_npc(self, npc_id: int) -> bool:
        return self._submit(lambda nc: nc.delete_npc(npc_id))

    def reset_npc(self, npc_id: int) -> bool:
        return self._submit(lambda nc: nc.reset_npc(npc_id))

    def get_npc_script(self, npc_id: int) -> bool:
        return self._submit(lambda nc: nc.get_npc_script(npc_id))

    def warp_npc(self, npc_id: int, x: float, y: float, level: str) -> bool:
        return self._submit(lambda nc: nc.warp_npc(npc_id, x, y, level))

    def get_npc_flags(self, npc_id: int) -> bool:
        return self._submit(lambda nc: nc.get_npc_flags(npc_id))

    def set_npc_script(self, npc_id: int, script: str) -> bool:
        return self._submit(lambda nc: nc.set_npc_script(npc_id, script))

    def set_npc_flags(self, npc_id: int, flags: str) -> bool:
        return self._submit(lambda nc: nc.set_npc_flags(npc_id, flags))

    def add_npc(self, name: str, npc_id: int, npc_type: str, scripter: str,
                level: str, x: float, y: float) -> bool:
        return self._submit(lambda nc: nc.add_npc(
            name, npc_id, npc_type, scripter, level, x, y))

    def get_local_npcs(self, level: str) -> bool:
        return self._submit(lambda nc: nc.get_local_npcs(level))

    def edit_class(self, class_name: str) -> bool:
        return self._submit(lambda nc: nc.edit_class(class_name))

    def add_class(self, class_name: str, script: str) -> bool:
        return self._submit(lambda nc: nc.add_class(class_name, script))

    def delete_class(self, class_name: str) -> bool:
        return self._submit(lambda nc: nc.delete_class(class_name))

    def get_weapon_list(self) -> bool:
        return self._submit(lambda nc: nc.get_weapon_list())

    def get_weapon(self, weapon: str) -> bool:
        return self._submit(lambda nc: nc.get_weapon(weapon))

    def add_weapon(self, weapon: str, image: str, code: str) -> bool:
        return self._submit(lambda nc: nc.add_weapon(weapon, image, code))

    def delete_weapon(self, weapon: str) -> bool:
        return self._submit(lambda nc: nc.delete_weapon(weapon))

    def get_level_list(self) -> bool:
        return self._submit(lambda nc: nc.get_level_list())
