"""
pyreborn - RC link

Runs an :class:`~pyreborn.rc_client.RCClient` on its own thread so a graphical
client can hold an RC session open alongside its game connection.

RC is a SEPARATE connection in this protocol. The reference server hands an
RC login to its own player class (GServer-v2 `PlayerRC`), and a game-client
connection never handles RC packets at all - it bubbles them to the base
handler, which drops them. So in-game RC tools cannot ride the game socket;
they need a second login that announces client type RC2.

That second login blocks (connect + handshake + waiting for the RC welcome),
which a frame loop cannot afford, so everything happens on a worker thread:

    link = RCLink(host, port, account, password, version)
    link.start()                 # returns immediately
    ...
    snap = link.snapshot         # immutable, safe to read from any thread
    link.say("hello other staff")

The worker owns the RCClient outright. Callers never touch it: reads go
through :attr:`snapshot` (rebuilt after every pump under a lock) and writes go
through the command queue. Every public command is therefore non-blocking and
safe to call from the render thread.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .packets import PacketID
from .rc_client import RCClient

logger = logging.getLogger(__name__)

# How long to wait for the server to prove it accepted us as an RC before
# giving up. The proof is an RC-only packet (see _EVIDENCE_IDS); a plain
# authenticated login is NOT proof, because a server that ignores the client
# type logs us in as an ordinary player and drops RC packets silently.
RC_PROOF_TIMEOUT = 6.0

# Chat/notice backlogs. RC chat on a busy server is chatty, so the log is
# bounded rather than unbounded-and-scrolled.
MAX_MESSAGES = 500
MAX_NOTICES = 60

# Packets only an RC connection is ever sent. Any one of them proves the
# session; PLO_RC_CHAT and PLO_RC_MAXUPLOADFILESIZE both arrive unprompted
# during an RC login, and the rest answer the probes _login sends.
_EVIDENCE_IDS = frozenset({
    PacketID.PLO_RC_CHAT,
    PacketID.PLO_RC_MAXUPLOADFILESIZE,
    PacketID.PLO_RC_SERVERFLAGSGET,
    PacketID.PLO_RC_SERVEROPTIONSGET,
    PacketID.PLO_RC_ACCOUNTLISTGET,
    PacketID.PLO_RC_FOLDERCONFIGGET,
    PacketID.PLO_RC_FILEBROWSER_DIR,
    PacketID.PLO_RC_FILEBROWSER_DIRLIST,
})

# Link states.
IDLE = "idle"
CONNECTING = "connecting"
READY = "ready"
DENIED = "denied"
ERROR = "error"
CLOSED = "closed"


def rc_download_dir(host: str, port: int) -> Path:
    """Where RC file-browser downloads are written.

    Deliberately NOT the asset download cache: those files are the server's
    art, keyed by normalized basename and revalidated on every login. An RC
    download is an admin pulling a specific file to look at, and clobbering a
    cache entry with it would poison the cache.
    """
    root = os.environ.get("PYREBORN_RC_DOWNLOAD_DIR")
    base = Path(root) if root else Path.home() / ".local" / "share" / "pyreborn" / "rc_downloads"
    return base / f"{host}_{port}"


@dataclass(frozen=True)
class RCSnapshot:
    """An immutable copy of the RC session state, safe to read mid-frame."""

    state: str = IDLE
    status: str = ""
    account: str = ""
    messages: Tuple[str, ...] = ()
    notices: Tuple[str, ...] = ()
    players: Tuple[Dict[str, Any], ...] = ()
    server_flags: Tuple[str, ...] = ()
    option_lines: Tuple[str, ...] = ()
    folder_config: Tuple[str, ...] = ()
    accounts: Tuple[str, ...] = ()
    folder: str = ""
    files: Tuple[Dict[str, Any], ...] = ()
    folders: Tuple[str, ...] = ()
    account_info: Dict[str, Any] = field(default_factory=dict)
    player_props: Dict[str, Any] = field(default_factory=dict)
    player_rights: Dict[str, Any] = field(default_factory=dict)
    player_comments: Dict[str, Any] = field(default_factory=dict)
    player_ban: Dict[str, Any] = field(default_factory=dict)
    max_upload_size: int = 0

    @property
    def available(self) -> bool:
        return self.state == READY


class _LinkedRCClient(RCClient):
    """RCClient that reports whether the server ever answered as an RC would."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saw_rc_packet = False

    def _handle_packet(self, packet_id: int, data: bytes):
        if packet_id in _EVIDENCE_IDS:
            self.saw_rc_packet = True
        super()._handle_packet(packet_id, data)


class RCLink:
    """A background RC session for a graphical client.

    Args:
        host/port: same server the game connection is on.
        account/password: the credentials the game connection logged in with.
        version: protocol version string, matched to the game connection.
        download_dir: where file-browser downloads land (defaults to
            :func:`rc_download_dir`).
    """

    def __init__(self, host: str, port: int, account: str, password: str,
                 version: str = "6.037",
                 download_dir: Optional[Path] = None):
        self.host = host
        self.port = port
        self.account = account
        self._password = password
        self.version = version
        self.download_dir = Path(download_dir) if download_dir else rc_download_dir(host, port)

        self._lock = threading.Lock()
        self._commands: "queue.Queue[Callable[[RCClient], None]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._messages: deque = deque(maxlen=MAX_MESSAGES)
        self._notices: deque = deque(maxlen=MAX_NOTICES)
        self._snapshot = RCSnapshot(account=account)

    # -- lifecycle --------------------------------------------------------

    @property
    def snapshot(self) -> RCSnapshot:
        """The most recent state copy. Cheap; call it once per frame."""
        with self._lock:
            return self._snapshot

    @property
    def state(self) -> str:
        return self.snapshot.state

    @property
    def available(self) -> bool:
        return self.snapshot.state == READY

    @property
    def started(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        """Begin connecting. Idempotent, and returns immediately."""
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._password:
            self._set_state(DENIED, "no password available for an RC login")
            return
        self._clear_commands()
        stop_event = threading.Event()
        self._stop = stop_event
        self._set_state(CONNECTING, f"connecting to {self.host}:{self.port}...")
        self._thread = threading.Thread(target=self._run, args=(stop_event,), name="pyreborn-rc",
                                        daemon=True)
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        """Tear the session down and wait briefly for the worker to exit."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is not None and not thread.is_alive():
            self._thread = None

    # -- worker -----------------------------------------------------------

    def _run(self, stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or self._stop
        rc: Optional[_LinkedRCClient] = None
        try:
            rc = _LinkedRCClient(self.host, self.port, self.version)
            self._wire_callbacks(rc)

            if not rc.connect():
                if stop_event.is_set():
                    return
                self._set_state(ERROR, "could not open an RC connection")
                return

            if not rc.login(self.account, self._password, timeout=15.0):
                if stop_event.is_set():
                    return
                reason = rc.disconnect_reason or "server refused the RC login"
                self._set_state(DENIED, reason)
                return

            if not self._await_rc_proof(rc, stop_event):
                if stop_event.is_set():
                    return
                self._set_state(DENIED, "this account has no RC access on this server")
                return

            self._set_state(READY, "RC session active")
            self._pump_until_stopped(rc, stop_event)
        except Exception as exc:  # noqa: BLE001 - a dead RC link must never
            # take the game client down with it.
            logger.warning("RC link failed: %s", exc, exc_info=True)
            self._set_state(ERROR, f"{type(exc).__name__}: {exc}")
        finally:
            self._clear_commands()
            if rc is not None:
                try:
                    rc.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            # Only a still-live session becomes CLOSED here. A DENIED/ERROR
            # verdict, or the more specific "connection dropped", is the
            # answer the panel needs to show.
            if self.state in (CONNECTING, READY):
                self._set_state(CLOSED, "RC session closed")

    def _await_rc_proof(self, rc: _LinkedRCClient,
                        stop_event: Optional[threading.Event] = None) -> bool:
        """Wait for a packet only an RC is sent (see _EVIDENCE_IDS).

        Servers that send the RC welcome chat prove it unprompted. For any
        that do not, the probes below are read-only requests whose answers are
        RC-only packets, so a real RC session always produces one and a
        rejected one produces nothing.
        """
        rc.list_rcs()
        rc.get_server_flags()
        stop_event = stop_event or self._stop
        deadline = time.time() + RC_PROOF_TIMEOUT
        while time.time() < deadline and not stop_event.is_set():
            rc.update(timeout=0.1)
            if rc.saw_rc_packet:
                return True
            if not rc.connected:
                return False
        return False

    def _pump_until_stopped(self, rc: _LinkedRCClient,
                            stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or self._stop
        while not stop_event.is_set():
            if not rc.connected:
                self._set_state(CLOSED, "RC connection dropped")
                return
            self._drain_commands(rc)
            rc.update(timeout=0.05)
            self._rebuild_snapshot(rc)

    def _drain_commands(self, rc: RCClient) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                command(rc)
            except Exception as exc:  # noqa: BLE001 - one bad admin action
                # must not end the session.
                logger.warning("RC command failed: %s", exc, exc_info=True)
                self._note(f"command failed: {type(exc).__name__}: {exc}")

    def _clear_commands(self) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    # -- callbacks --------------------------------------------------------

    def _wire_callbacks(self, rc: RCClient) -> None:
        rc.on_rc_chat = self._on_rc_chat
        rc.on_admin_message = self._on_admin_message
        rc.on_filebrowser_message = self._note
        rc.on_file = self._on_file

    def _on_rc_chat(self, message: str) -> None:
        self._append_message(message)

    def _on_admin_message(self, admin: str, message: str) -> None:
        self._append_message(f"[admin] {admin}: {message}")

    def _on_file(self, filename: str, data: bytes) -> None:
        """Write an RC download to disk and say where it went."""
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            # Basename only: the server names the file, and a path in that
            # name must not let it write outside the download directory.
            target = self.download_dir / Path(filename).name
            target.write_bytes(data)
        except OSError as exc:
            self._note(f"could not save {filename}: {exc}")
            return
        self._note(f"saved {target}")

    def _append_message(self, text: str) -> None:
        with self._lock:
            self._messages.append(text)
            self._publish_log()

    def _note(self, text: str) -> None:
        with self._lock:
            self._notices.append(text)
            self._publish_log()

    def _publish_log(self) -> None:
        """Push the chat/notice backlogs into the snapshot immediately.

        Callers hold the lock. Chat and notices arrive from callbacks, and
        waiting for the next pump to publish them would lose them entirely
        whenever the worker is not pumping - a failed download, for one, is
        reported while the link is still finishing a command.
        """
        self._snapshot = replace(self._snapshot,
                                 messages=tuple(self._messages),
                                 notices=tuple(self._notices))

    # -- state ------------------------------------------------------------

    def _set_state(self, state: str, status: str) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, state=state, status=status)

    def _rebuild_snapshot(self, rc: RCClient) -> None:
        players = tuple(sorted(
            (dict(p) for p in rc.players.values()),
            key=lambda p: str(p.get('account', '')).lower()))
        with self._lock:
            self._snapshot = RCSnapshot(
                state=self._snapshot.state,
                status=self._snapshot.status,
                account=self.account,
                messages=tuple(self._messages),
                notices=tuple(self._notices),
                players=players,
                server_flags=tuple(rc._server_flags),
                option_lines=tuple(rc._server_option_lines),
                folder_config=tuple(rc._folder_config.get('lines', ())),
                accounts=tuple(rc._account_list),
                folder=rc.file_current_folder,
                files=tuple(dict(f) for f in rc.file_list),
                folders=tuple(rc.file_folders),
                account_info=dict(rc._last_account),
                player_props=dict(rc._last_player_props),
                player_rights=dict(rc._last_player_rights),
                player_comments=dict(rc._last_player_comments),
                player_ban=dict(rc._last_player_ban),
                max_upload_size=rc.max_upload_size,
            )

    # -- commands ---------------------------------------------------------
    #
    # Every one of these is enqueued for the worker, so they return
    # immediately and never touch the socket from the caller's thread.

    def _submit(self, fn: Callable[[RCClient], None]) -> bool:
        if self.state != READY:
            return False
        self._commands.put(fn)
        return True

    # chat / broadcast
    def say(self, message: str) -> bool:
        return self._submit(lambda rc: rc.rc_say(message))

    def admin_message(self, message: str) -> bool:
        return self._submit(lambda rc: rc.admin_message(message))

    # players
    def refresh_rcs(self) -> bool:
        return self._submit(lambda rc: rc.list_rcs())

    def kick(self, player_id: int) -> bool:
        return self._submit(lambda rc: rc.kick_player(player_id))

    def warp_player(self, player_id: int, x: float, y: float, level: str) -> bool:
        return self._submit(lambda rc: rc.warp_player(player_id, x, y, level))

    def player_props(self, player_id: int) -> bool:
        return self._submit(lambda rc: rc.get_player_props(player_id))

    def player_props_by_name(self, account: str) -> bool:
        return self._submit(lambda rc: rc.get_player_props_by_name(account))

    def rights(self, account: str) -> bool:
        return self._submit(lambda rc: rc.get_player_rights(account))

    def set_rights(self, account: str, rights: int, admin_ip: str = '*.*.*.*',
                   folders=()) -> bool:
        return self._submit(
            lambda rc: rc.set_player_rights(account, rights, admin_ip, folders))

    def comments(self, account: str) -> bool:
        return self._submit(lambda rc: rc.get_player_comments(account))

    def set_comments(self, account: str, comments: str) -> bool:
        return self._submit(lambda rc: rc.set_player_comments(account, comments))

    def ban_status(self, account: str) -> bool:
        return self._submit(lambda rc: rc.get_ban_status(account))

    def ban(self, account: str, banned: bool = True, reason: str = "") -> bool:
        return self._submit(lambda rc: rc.ban_player(account, banned, reason))

    # accounts
    def refresh_accounts(self) -> bool:
        return self._submit(lambda rc: rc.get_account_list())

    def account_info(self, account: str) -> bool:
        return self._submit(lambda rc: rc.get_account(account))

    def create_account(self, account: str, password: str, email: str = "") -> bool:
        return self._submit(lambda rc: rc.create_account(account, password, email))

    def delete_account(self, account: str) -> bool:
        return self._submit(lambda rc: rc.delete_account(account))

    # server
    def refresh_flags(self) -> bool:
        return self._submit(lambda rc: rc.get_server_flags())

    def set_flags(self, flags: Dict[str, str]) -> bool:
        return self._submit(lambda rc: rc.set_server_flags(flags))

    def refresh_options(self) -> bool:
        return self._submit(lambda rc: rc.get_server_options())

    def set_options(self, options_text: str) -> bool:
        return self._submit(lambda rc: rc.set_server_options(options_text))

    def refresh_folder_config(self) -> bool:
        return self._submit(lambda rc: rc.get_folder_config())

    def update_levels(self) -> bool:
        return self._submit(lambda rc: rc.update_levels())

    # file browser
    def files_start(self) -> bool:
        return self._submit(lambda rc: rc.filebrowser_start())

    def files_cd(self, folder: str) -> bool:
        return self._submit(lambda rc: rc.filebrowser_cd(folder))

    def files_end(self) -> bool:
        return self._submit(lambda rc: rc.filebrowser_end())

    def files_download(self, filename: str) -> bool:
        return self._submit(lambda rc: rc.filebrowser_download(filename))

    def files_delete(self, filename: str) -> bool:
        return self._submit(lambda rc: rc.filebrowser_delete(filename))

    def files_rename(self, old_name: str, new_name: str) -> bool:
        return self._submit(lambda rc: rc.filebrowser_rename(old_name, new_name))

    def files_move(self, destination_dir: str, filename: str) -> bool:
        return self._submit(lambda rc: rc.filebrowser_move(destination_dir, filename))

    def folder_delete(self, folder: str) -> bool:
        return self._submit(lambda rc: rc.folder_delete(folder))

    def files_upload(self, local_path: str) -> bool:
        """Upload a local file into the RC's current folder.

        The read happens on the worker thread, so a large or missing file
        stalls nothing and reports through the notice log.
        """
        path = Path(local_path).expanduser()

        def _upload(rc: RCClient) -> None:
            try:
                data = path.read_bytes()
            except OSError as exc:
                self._note(f"could not read {path}: {exc}")
                return
            limit = rc.max_upload_size
            if limit and len(data) > limit:
                self._note(f"{path.name} is {len(data)} bytes, over the "
                           f"server's {limit}-byte upload limit")
                return
            if rc.filebrowser_upload(path.name, data):
                # "sent", not "uploaded": the bytes are on the wire, and only
                # the server's own file-browser message says whether they
                # were written. Claiming success here would hide a server
                # that accepts the packet and discards it.
                self._note(f"sent {path.name} ({len(data)} bytes) — waiting "
                           f"for the server's answer")
            else:
                self._note(f"upload of {path.name} was not sent")

        return self._submit(_upload)
