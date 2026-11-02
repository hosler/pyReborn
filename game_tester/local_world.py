"""Throwaway, loopback-only pygserver worlds using the real network clients.

Logout all clients before snapshot/restore. Running servers are restarted to
flush account saves and discard pygserver's account cache. Only account JSON
is persistent in pygserver today; server flags and transient NPC/world state
are not checkpointed. stop() retains the temp directory for logs and snapshots;
close() (also context-manager exit) removes it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import weakref

READY_MARKER = "Server listening on"
STARTUP_TIMEOUT = 20.0
SHUTDOWN_TIMEOUT = 10.0
_WORLDS = weakref.WeakSet()

# from_server_dir fixes levels_dir to root/world. Set host programmatically:
# serverip/localip configure advertisements, not the listening interface.
_BOOTSTRAP = """
import asyncio, logging, random, signal, sys
from pygserver.config import ServerConfig
from pygserver.server import GameServer
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
async def main():
    random.seed(0)
    config = ServerConfig.from_server_dir(sys.argv[1])
    config.host = '127.0.0.1'
    config.enable_listserver = False
    config.villager_count = 0
    server = GameServer(config)
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, done.set)
    task = asyncio.create_task(server.start())
    stopping = asyncio.create_task(done.wait())
    await asyncio.wait((task, stopping), return_when=asyncio.FIRST_COMPLETED)
    if task.done():
        stopping.cancel()
        await task
    else:
        await server.stop()
        await task
asyncio.run(main())
"""


def local_world_for(host, port):
    """Find an active local harness so GameBots can register automatically."""
    return next((w for w in _WORLDS if w.port == port and
                 host in (w.host, "localhost") and w.running), None)


class LocalWorld:
    """Own an isolated server directory; prepare() needs no sockets/server."""

    host = "127.0.0.1"

    def __init__(self, world_dir, *, gmaps=None, start_level=None,
                 start_xy=None, accounts=("testbot1", "testbot2"), port=None,
                 extra_options=None):
        self.world_dir = Path(world_dir).resolve()
        if not self.world_dir.is_dir():
            raise NotADirectoryError(self.world_dir)
        self.gmaps = [gmaps] if isinstance(gmaps, str) else list(gmaps or ())
        self.start_level = start_level
        if self.start_level is None:
            default = self.world_dir / "onlinestartlocal.nw"
            levels = sorted(self.world_dir.rglob("*.nw"))
            if not default.is_file() and not levels:
                raise ValueError("world has no .nw levels; specify start_level")
            self.start_level = default.name if default.is_file() else levels[0].name
        self.start_xy = tuple(start_xy) if start_xy is not None else (30.0, 30.5)
        if len(self.start_xy) != 2:
            raise ValueError("start_xy must contain X and Y")
        self.accounts = tuple(accounts)
        for name in self.accounts:
            self._safe_name(name)
        self.port = port
        self.extra_options = dict(extra_options or {})
        reserved = {"serverport", "noverifylogin", "staff", "gmaps",
                    "startlevel", "startx", "starty"}
        if reserved.intersection(k.lower() for k in self.extra_options):
            raise ValueError("extra_options cannot override LocalWorld settings")
        self.server_dir = Path(tempfile.mkdtemp(prefix="local_world_"))
        self.log_path = self.server_dir / "server.log"
        self._process = None
        self._bots = weakref.WeakSet()
        self._prepared = False
        self._previous_environment = None
        _WORLDS.add(self)

    @staticmethod
    def _safe_name(name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"unsafe account/snapshot name: {name!r}")
        return name

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    def prepare(self):
        """Generate config and fresh accounts once, without launching a server."""
        if not self._prepared:
            for name in ("config", "accounts", "npcs", "weapons", "snapshots"):
                (self.server_dir / name).mkdir()
            (self.server_dir / "world").symlink_to(self.world_dir, target_is_directory=True)
            for name in self.accounts:
                self._seed_account(name)
            self._prepared = True
        options = dict(self.extra_options)
        options.update(serverport=self.port if self.port is not None else 0,
                       noverifylogin="true", staff=",".join(self.accounts),
                       gmaps=",".join(self.gmaps), startlevel=self.start_level,
                       startx=self.start_xy[0], starty=self.start_xy[1])
        lines = []
        for key, value in options.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if any(c in str(key) + value for c in "\r\n") or "=" in str(key):
                raise ValueError("server options must be single-line key/value pairs")
            lines.append(f"{key} = {value}\n")
        (self.server_dir / "config" / "serveroptions.txt").write_text("".join(lines))
        return self

    def _seed_account(self, name):
        # Use the server's own defaults/serializer, including inventory fields.
        from pygserver.account import Account
        self._safe_name(name)
        account = Account(account_name=name, level_name=self.start_level,
                          x=self.start_xy[0], y=self.start_xy[1],
                          is_staff=name in self.accounts)
        account.set_password("testpass")
        (self.server_dir / "accounts" / f"{name}.json").write_text(
            json.dumps(account.to_dict(), indent=2) + "\n")

    def register_bot(self, bot):
        """Track a GameBot before login; seed dynamic daemon accounts as well."""
        self.prepare()
        self._bots.add(bot)
        # Only names that are safe as file names get a pre-seeded account;
        # anything else (spaces, dots, non-ASCII) is still tracked and the
        # server creates its account on login, as a bare server would.
        try:
            self._safe_name(bot.name)
        except ValueError:
            return bot
        path = self.server_dir / "accounts" / f"{bot.name}.json"
        if not path.exists():
            self._seed_account(bot.name)
        return bot

    def _command(self):
        return [sys.executable, "-u", "-c", _BOOTSTRAP, str(self.server_dir)]

    def start(self):
        if self.running:
            return self
        self.prepare()
        if self.port is None:
            # Only this step needs a socket; filesystem tests can use prepare().
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((self.host, 0))
                self.port = sock.getsockname()[1]
            self.prepare()
        env = dict(os.environ, PYGSERVER_QA="1",
                   PYGSERVER_ACCOUNTS_DIR=str(self.server_dir / "accounts"),
                   PYTHONHASHSEED="0")
        # Honor the same sibling-checkout override as the original fixture.
        checkout = Path(os.environ.get("PYGSERVER_DIR",
                        Path(__file__).resolve().parents[2] / "pygserver"))
        with self.log_path.open("wb") as log:
            self._process = subprocess.Popen(
                self._command(), cwd=str(checkout), env=env,
                stdout=log, stderr=subprocess.STDOUT)
        try:
            self._wait_for_ready()
        except BaseException:
            self.stop()
            raise
        # QA reset helpers execute in the parent, not in the subprocess. Keep
        # both account-store formats confined to this throwaway directory.
        if self._previous_environment is None:
            self._previous_environment = {
                key: os.environ.get(key) for key in
                ("PYGSERVER_ACCOUNTS_DIR", "GSERVER_ACCOUNTS_DIR")}
            for key in self._previous_environment:
                os.environ[key] = str(self.server_dir / "accounts")
        return self

    def _wait_for_ready(self):
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                tail = self.log_tail()
                if "PermissionError" in tail and ("socket" in tail or "bind" in tail):
                    raise PermissionError(f"pygserver socket permission denied:\n{tail}")
                raise RuntimeError(f"pygserver exited early (code={self._process.returncode}):\n{tail}")
            if READY_MARKER in self.log_tail():
                return
            time.sleep(0.1)
        raise TimeoutError(f"pygserver not ready within {STARTUP_TIMEOUT}s:\n{self.log_tail()}")

    def log_tail(self, chars=4000):
        try:
            with self.log_path.open("rb") as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - chars))
                return log.read().decode(errors="replace")
        except OSError:
            return "(no server log available)"

    def stop(self):
        if self.running:
            self._process.terminate()
            try:
                self._process.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=SHUTDOWN_TIMEOUT)

    def _require_logged_out(self):
        connected = [b.name for b in self._bots if b.connected]
        if connected:
            raise RuntimeError(f"log out registered bots before snapshot/restore: {connected}")

    def snapshot(self, name):
        """Copy account JSON after logout; flush a running server first."""
        self._safe_name(name)
        self.prepare()
        self._require_logged_out()
        dest = self.server_dir / "snapshots" / name
        if dest.exists():
            raise FileExistsError(dest)
        restart = self.running
        self.stop()
        try:
            dest.mkdir()
            shutil.copytree(self.server_dir / "accounts", dest / "accounts")
        finally:
            if restart:
                self.start()
        return dest

    def restore(self, name):
        """Restore account files exactly, deleting accounts created since snapshot.

        All clients must be logged out, including clients outside this process.
        Registered connected GameBots are rejected. A running server restarts to
        discard its cached accounts (and transient flags/NPC/level changes).
        """
        self._safe_name(name)
        self._require_logged_out()
        source = self.server_dir / "snapshots" / name / "accounts"
        if not source.is_dir():
            raise FileNotFoundError(source)
        restart = self.running
        self.stop()
        try:
            accounts = self.server_dir / "accounts"
            shutil.rmtree(accounts)
            shutil.copytree(source, accounts)
        finally:
            if restart:
                self.start()

    def close(self):
        self.stop()
        if self._previous_environment is not None:
            for key, previous in self._previous_environment.items():
                if os.environ.get(key) == str(self.server_dir / "accounts"):
                    if previous is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous
            self._previous_environment = None
        shutil.rmtree(self.server_dir, ignore_errors=True)
        _WORLDS.discard(self)

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.close()
            raise

    def __exit__(self, *exc):
        self.close()


def add_world_arguments(parser, *, gmap_suite=False):
    """Shared CLI flags; the QA CLI retains its existing bare --gmap suite."""
    parser.add_argument("--world", type=Path, metavar="DIR", help="Run a throwaway loopback pygserver world")
    parser.add_argument("--start", nargs=3, metavar=("LEVEL", "X", "Y"), help="Fresh account start level and tile position")
    parser.add_argument("--gmap", nargs="?" if gmap_suite else None,
                        const=True if gmap_suite else None, default=None,
                        metavar="NAME", help="GMAP filename" + ("; without NAME runs the GMAP suite" if gmap_suite else ""))


def world_from_arguments(args, *, accounts=("testbot1", "testbot2")):
    start = args.start
    return LocalWorld(args.world, gmaps=args.gmap if isinstance(args.gmap, str) else None,
                      start_level=start[0] if start else None,
                      start_xy=(float(start[1]), float(start[2])) if start else None,
                      accounts=accounts)
