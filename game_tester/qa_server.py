"""Manage the pygserver processes used by QA on Linux.

An orphan from an earlier session can hold port 14900 with hours-old code.
Records and source timestamps make that process visible before another run.

Backgrounding a subshell can leave its Python child behind when the shell is
killed. Launching Python directly in a new session gives the manager its PID.

Two servers sharing an accounts directory can overwrite each other's saves.
Managed starts refuse that overlap; explicit worlds get private account stores.

Ad hoc launches leave no inventory of what is running or who started it.
The list command shows managed servers and unrecorded runner processes.
A QA script must never background a server by hand: use qa_server run instead.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from .fixtures import release_all, state_dir
from .local_world import READY_MARKER, SHUTDOWN_TIMEOUT, STARTUP_TIMEOUT


@contextmanager
def _locked():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _record_path(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("server names may contain only letters, digits, '_' and '-'")
    return state_dir() / f"{name}.json"


def records():
    return [json.loads(path.read_text()) for path in sorted(state_dir().glob("*.json"))]


def _record(name):
    path = _record_path(name)
    return json.loads(path.read_text()) if path.exists() else None


def source_stamp(checkout):
    checkout = Path(checkout)
    paths = [checkout / "run_server.py", *(checkout / "pygserver").rglob("*.py")]
    newest = 0.0
    for path in paths:
        try:
            newest = max(newest, path.stat().st_mtime)
        except FileNotFoundError:
            pass  # A source file may disappear during an edit.
    return newest


def _process(pid):
    try:
        root = Path("/proc") / str(pid)
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        cmdline = (root / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        age = max(0.0, uptime - int(fields[19]) / os.sysconf("SC_CLK_TCK"))
        try:
            cwd = str((root / "cwd").readlink())
        except OSError:
            cwd = "unknown"
        return dict(pid=int(pid), age=age, cmdline=cmdline, cwd=cwd)
    except (OSError, ValueError, IndexError):
        return None


def is_live(pid):
    process = _process(pid)
    return process is not None and "run_server.py" in process["cmdline"]


def is_stale(record):
    return source_stamp(record["pygserver_dir"]) > record["source_stamp"]


def _listeners():
    """Return LISTEN socket inode -> port for both IP families."""
    listeners = {}
    for name in ("tcp", "tcp6"):
        try:
            lines = (Path("/proc/net") / name).read_text().splitlines()[1:]
        except FileNotFoundError:
            continue  # IPv6 may be disabled.
        for line in lines:
            fields = line.split()
            if fields[3] == "0A":
                listeners[fields[9]] = int(fields[1].rsplit(":", 1)[1], 16)
    return listeners


def _socket_owners(inodes):
    owners = {}
    if not inodes:
        return owners
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / "fd").iterdir():
                try:
                    target = str(fd.readlink())
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    owners[target[8:-1]] = int(process.name)
        except OSError:
            continue  # Inaccessible sockets remain owned by "unknown".
    return owners


def port_holder(port):
    sockets = {inode for inode, number in _listeners().items() if number == port}
    if not sockets:
        return None
    owners = _socket_owners(sockets)
    for pid in owners.values():
        process = _process(pid)
        if process is not None:
            return process
    return dict(pid="unknown", age=None, cmdline="unknown", cwd="unknown")


def orphans():
    managed = {record["pid"] for record in records() if is_live(record["pid"])}
    sockets = _listeners()
    owners = _socket_owners(sockets)
    found = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit() or int(path.name) in managed:
            continue
        process = _process(int(path.name))
        if process is not None and "run_server.py" in process["cmdline"]:
            process["ports"] = sorted({sockets[inode] for inode, pid in owners.items()
                                       if pid == process["pid"]})
            found.append(process)
    return sorted(found, key=lambda process: process["pid"])


def _age(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60}s"
    return f"{seconds}s"


def _identity(process):
    return f"pid={process['pid']} age={_age(process['age'])} cmdline={process['cmdline']}"


def _terminate(pid):
    # Recheck the runner identity before each signal: stale records may have
    # PIDs that now belong to unrelated processes.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not is_live(pid):
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        while time.monotonic() < deadline:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not is_live(pid):
                return
            time.sleep(0.1)
    if is_live(pid):
        raise RuntimeError(f"server pid={pid} did not exit after SIGKILL")


def _log_tail(path):
    with Path(path).open("rb") as log:
        log.seek(0, 2)
        log.seek(max(0, log.tell() - 4000))
        return log.read().decode(errors="replace")


# Directories pygserver creates under its working directory when it starts
# (FileSystem._ensure_directories, run_server.py). A default (no --world)
# server runs in the checkout, so a run on a bare checkout leaves these behind
# as empty, untracked directories; the manager removes the ones it saw appear.
_SERVER_CREATED_DIRS = ("levels", "world", "gani", "images", "sounds", "scripts",
                        "accounts", "npcs", "weapons")


def _launch(checkout, config, log):
    return subprocess.Popen(
        [sys.executable, "run_server.py", str(config)], cwd=str(checkout),
        start_new_session=True, stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ, PYGSERVER_QA="1", PYTHONDONTWRITEBYTECODE="1"))


def _prepare_world(name, source, config):
    """Prepare a private server root, retaining source content and options."""
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    server = state_dir() / f"{name}.world"
    # Only the managed content staging area is rebuilt; keep account saves.
    server.mkdir(exist_ok=True)
    for child in server.iterdir():
        if child.name == "accounts":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    (server / "accounts").mkdir(exist_ok=True)
    (server / "config").mkdir()
    (server / "config" / "serveroptions.txt").symlink_to(config)
    levels = source / "world" if (source / "world").is_dir() else source
    (server / "world").symlink_to(levels, target_is_directory=True)
    for name in ("npcs", "weapons"):
        if levels != source and (source / name).is_dir():
            shutil.copytree(source / name, server / name)
        else:
            (server / name).mkdir()
    for name in ("images", "gani", "sounds", "bodies", "heads", "swords", "shields", "hats"):
        if levels != source and (source / name).is_dir():
            (server / name).symlink_to(source / name, target_is_directory=True)
    return server


def start(name="dev", port=14900, pygserver=None, serverside=True, world=None):
    """Start a server. The caller holds the state lock."""
    path = _record_path(name)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    previous = _record(name)
    if previous and is_live(previous["pid"]):
        raise ValueError(f"name {name!r} already live: {_identity(_process(previous['pid']))}")
    holder = _settled_port_holder(port)
    if holder:
        raise ValueError(f"port {port} is in use: {_identity(holder)}")
    if previous:        # a dead record's leftovers are still ours to remove
        _cleanup(previous)
        path.unlink(missing_ok=True)    # and so is the record: a failed start must not leave it
    checkout = Path(pygserver or os.environ.get(
        "PYGSERVER_DIR", Path(__file__).resolve().parents[2] / "pygserver")).expanduser().resolve()
    if not (checkout / "run_server.py").is_file():
        raise FileNotFoundError(checkout / "run_server.py")
    # File configs use the checkout's accounts directory. Do not allow two
    # managed instances to write it concurrently.
    if world is None:
        for record in records():
            if (not record.get("world") and Path(record["pygserver_dir"]) == checkout
                    and is_live(record["pid"])):
                raise ValueError(f"accounts directory already used by {record['name']!r}: "
                                 f"{_identity(_process(record['pid']))}; use --world for isolation")
    config = state_dir() / f"{name}.serveroptions.txt"
    # A config file that omits these two keys withholds links and signs from
    # the client; the reference's shipped default config sets both. A world's
    # own config (below) overrides them.
    options = "clientsidelinks = true\nclientsidesigns = true\n"
    if world is not None:
        world = str(Path(world).expanduser().resolve())
        original = Path(world) / "config" / "serveroptions.txt"
        if original.is_file():
            options = original.read_text() + "\n"
    options += (f"name = {name}\nserverport = {port}\nnoverifylogin = true\n"
                f"serverside = {str(serverside).lower()}\n")
    config.write_text(options)
    try:
        launch_config = _prepare_world(name, world, config) if world else config
    except BaseException:
        config.unlink(missing_ok=True)
        raise
    # NPC registration (including sparringzone) happens at startup, even
    # though pygserver can discover newly added level files while running.
    # The file lives in the served levels directory (the checkout's `levels/`,
    # or the --world source through the private root's `world` link), because
    # that is the only place pygserver registers level NPCs from. The manager
    # therefore records what it wrote and `stop` removes it; a file that was
    # already there with the right content is left alone and not recorded.
    from .spar_fixture import spar_fixture
    absent_dirs = [] if world else [str(checkout / name) for name in _SERVER_CREATED_DIRS
                                    if not (checkout / name).exists()]
    levels_dir = launch_config / "world" if world else checkout / "levels"
    accounts_dir = launch_config / "accounts" if world else checkout / "accounts"
    fixture = spar_fixture(levels_dir)
    try:
        fixture.install()
        if fixture.refused:
            raise ValueError(f"refusing to install {fixture.path}: a symlink is there")
    except BaseException:
        fixture.release()       # a partial write is unwound
        config.unlink(missing_ok=True)
        raise
    log_path = state_dir() / f"{name}.log"
    record = dict(name=name, port=port, pygserver_dir=str(checkout),
                  config_path=str(config), log_path=str(log_path), started=time.time(),
                  source_stamp=source_stamp(checkout),
                  starter=Path(os.environ["CLAUDE_JOB_DIR"]).name
                  if os.environ.get("CLAUDE_JOB_DIR") else os.getppid(),
                  serverside=serverside, levels_dir=str(levels_dir),
                  accounts_dir=str(accounts_dir),
                  fixtures=[fixture.to_dict()] if fixture.installed else [],
                  created_dirs=absent_dirs)
    if world:
        record["world"] = world
    try:
        with log_path.open("wb") as log:
            process = _launch(checkout, launch_config, log)
    except BaseException:
        fixture.release()
        config.unlink(missing_ok=True)
        raise
    fixture.adopt(process.pid)      # the server now keeps the file alive
    record["fixtures"] = [fixture.to_dict()] if fixture.installed else []
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"pygserver exited early (code={process.returncode}):\n{_log_tail(log_path)}")
            if READY_MARKER in _log_tail(log_path):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError(f"pygserver not ready within {STARTUP_TIMEOUT}s:\n{_log_tail(log_path)}")
        record["pid"] = process.pid
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(path)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=SHUTDOWN_TIMEOUT)
        fixture.release()
        _remove_empty_dirs(absent_dirs)
        config.unlink(missing_ok=True)
        raise
    print(f"{name} {port} {process.pid} {log_path}", flush=True)
    return record


def _settled_port_holder(port, grace=2.0):
    """port_holder, but a LISTEN socket with no owning process is given
    `grace` seconds to disappear. A server that just exited can leave its
    socket in the kernel table for a few milliseconds after /proc stops
    showing the process, which made restart refuse its own port."""
    deadline = time.monotonic() + grace
    while True:
        holder = port_holder(port)
        if holder is None or holder["pid"] != "unknown" or time.monotonic() >= deadline:
            return holder
        time.sleep(0.05)


def stop(record, purge=False):
    """Stop a managed server and remove what `start` provisioned. The log
    and the private account store stay unless `purge` is set."""
    _terminate(record["pid"])
    _settled_port_holder(record["port"], grace=SHUTDOWN_TIMEOUT)
    _cleanup(record)
    _record_path(record["name"]).unlink(missing_ok=True)
    if purge:
        _purge(record["name"])


def _purge(name):
    """Delete a stopped server's log and its `<name>.world` staging
    directory (account store included) from the state directory.

    Only those two fixed names under state_dir() are touched; `_record_path`
    already restricts `name` to [A-Za-z0-9_-]. The staging directory holds
    symlinks into the source world: rmtree unlinks a symlink and never
    descends through it, so the source is never touched. A `.world` that is
    itself a symlink is unlinked, not followed."""
    _record_path(name)      # validates the name
    directory = state_dir()
    (directory / f"{name}.log").unlink(missing_ok=True)
    world = directory / f"{name}.world"
    if world.is_symlink():
        world.unlink()
    elif world.is_dir():
        shutil.rmtree(world)


def _remove_empty_dirs(paths):
    for path in paths or ():
        try:
            Path(path).rmdir()      # only an empty directory goes
        except OSError:
            pass


def _cleanup(record):
    """Remove what `start` provisioned for this record: fixture files it wrote
    (with any directory it created), the empty directories the server created
    in the checkout, and the generated options file. The log and the private
    account store stay, for post-mortems and reruns."""
    release_all(record.get("fixtures"))
    _remove_empty_dirs(record.get("created_dirs"))
    config = record.get("config_path")
    if config:
        Path(config).unlink(missing_ok=True)


def _parameters(record):
    return dict(name=record["name"], port=record["port"],
                pygserver=record["pygserver_dir"], serverside=record["serverside"],
                world=record.get("world"))


def restart(record):
    stop(record)
    return start(**_parameters(record))


def ensure(name="dev", port=14900, fresh=False):
    record = _record(name)
    if record and is_live(record["pid"]):
        if record["port"] != port:
            raise ValueError(f"{name!r} uses port {record['port']}, requested {port}")
        # Older records predate startup fixture provisioning. Restart them
        # once so `run` also guarantees the spar NPC was registered.
        return restart(record) if fresh and (
            is_stale(record) or not record.get("levels_dir")) else record
    if record:
        parameters = _parameters(record)
        parameters["port"] = port
        return start(**parameters)
    return start(name=name, port=port)


def list_servers():
    print("NAME STATUS PORT PID AGE STARTER")
    for record in records():
        live = is_live(record["pid"])
        status = ("stale" if is_stale(record) else "live") if live else "dead"
        print(f"{record['name']} {status} {record['port']} {record['pid']} "
              f"{_age(time.time() - record['started'])} {record['starter']}")
    print("\nORPHANS\nPID AGE PORT CWD CMDLINE")
    for process in orphans():
        ports = ",".join(map(str, process["ports"])) or "unknown"
        print(f"{process['pid']} {_age(process['age'])} {ports} "
              f"{process['cwd']} {process['cmdline']}")


class _SignalExit(BaseException):
    def __init__(self, signum):
        self.signum = signum


def _signal_exit(signum, frame):
    raise _SignalExit(signum)


def _run(args):
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise ValueError("run requires -- CMD ARGS...")
    previous = signal.signal(signal.SIGTERM, _signal_exit)
    record = None
    try:
        with _locked():
            record = ensure(args.name, args.port, fresh=True)
        env = dict(os.environ, PYREBORN_TEST_PORT=str(record["port"]),
                   PYREBORN_QA_PORT=str(record["port"]))
        if record.get("levels_dir"):
            env["PYGSERVER_LEVELS_DIR"] = record["levels_dir"]
            env["PYGSERVER_ACCOUNTS_DIR"] = record["accounts_dir"]
        result = subprocess.run(command, env=env)
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    finally:
        signal.signal(signal.SIGTERM, previous)
        if record is not None and not args.keep:
            with _locked():
                current = _record(args.name)
                if current and current["pid"] == record["pid"]:
                    stop(current)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    launch = commands.add_parser("start")
    launch.add_argument("--name", default="dev")
    launch.add_argument("--port", type=int, default=14900)
    launch.add_argument("--pygserver", type=Path, metavar="DIR")
    mode = launch.add_mutually_exclusive_group()
    mode.add_argument("--serverside", action="store_true", dest="serverside", default=True)
    mode.add_argument("--no-serverside", action="store_false", dest="serverside")
    launch.add_argument("--world", type=Path, metavar="DIR")
    commands.add_parser("list")
    halt = commands.add_parser("stop")
    halt.add_argument("names", nargs="*")
    selection = halt.add_mutually_exclusive_group()
    selection.add_argument("--port", type=int)
    selection.add_argument("--all", action="store_true")
    halt.add_argument("--orphans", action="store_true")
    halt.add_argument("--purge", action="store_true",
                      help="also delete each stopped server's log and its "
                           "<name>.world staging directory (accounts included)")
    again = commands.add_parser("restart")
    again.add_argument("name")
    ready = commands.add_parser("ensure")
    ready.add_argument("--name", default="dev")
    ready.add_argument("--port", type=int, default=14900)
    ready.add_argument("--fresh", action="store_true")
    run = commands.add_parser("run")
    run.add_argument("--name", default="qa")
    run.add_argument("--port", type=int, default=14901)
    run.add_argument("--keep", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)
    commands.add_parser("prune")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.action == "run":
            return _run(args)
        with _locked():
            if args.action == "start":
                start(args.name, args.port, args.pygserver, args.serverside, args.world)
            elif args.action == "list":
                list_servers()
            elif args.action == "stop":
                if args.names and (args.port is not None or args.all):
                    raise ValueError("choose names, --port, or --all")
                if not (args.names or args.port is not None or args.all or args.orphans):
                    raise ValueError("stop requires names, --port, --all, or --orphans")
                selected = records()
                if args.names:
                    selected = [_record(name) for name in args.names]
                    if any(record is None for record in selected):
                        raise ValueError("unknown server name")
                elif args.port is not None:
                    selected = [record for record in selected if record["port"] == args.port]
                elif not args.all:
                    selected = []
                for record in selected:
                    stop(record, purge=args.purge)
                if args.orphans:
                    for process in orphans():
                        _terminate(process["pid"])
            elif args.action == "restart":
                record = _record(args.name)
                if record is None:
                    raise ValueError(f"unknown server {args.name!r}")
                restart(record)
            elif args.action == "ensure":
                ensure(args.name, args.port, args.fresh)
            elif args.action == "prune":
                for record in records():
                    if not is_live(record["pid"]):
                        _cleanup(record)
                        _record_path(record["name"]).unlink()
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"qa_server: {exc}", file=sys.stderr)
        return 2
    except _SignalExit as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
