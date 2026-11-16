"""Offline lifecycle tests with real child PIDs and temporary manager state."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from game_tester import qa_server as qa


@pytest.fixture
def managed(tmp_path, monkeypatch):
    state = tmp_path / "state"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "run_server.py").write_text("# runner\n")
    (checkout / "pygserver").mkdir()
    (checkout / "pygserver" / "server.py").write_text("# source\n")
    monkeypatch.setenv("PYREBORN_QA_SERVERS_DIR", str(state))
    monkeypatch.setenv("PYGSERVER_DIR", str(checkout))
    monkeypatch.setenv("CLAUDE_JOB_DIR", "/tmp/jobs/offline-test")
    # Stand-ins do not bind sockets; unrelated local listeners cannot affect
    # these tests. The port tests below exercise the real proc readers.
    monkeypatch.setattr(qa, "port_holder", lambda port: None)
    children = []
    launches = []

    def launch(directory, config, log):
        # The arena must exist before the child can index/register its NPCs.
        from game_tester.spar_fixture import SPAR_LEVEL, spar_level_text
        levels = config / "world" if Path(config).is_dir() else directory / "levels"
        assert (levels / SPAR_LEVEL).read_text() == spar_level_text()
        process = subprocess.Popen(
            [sys.executable, "-u", "-c",
             f"import time; print({qa.READY_MARKER!r}, flush=True); time.sleep(120)",
             "run_server.py"],
            cwd=directory, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        children.append(process)
        launches.append(Path(config))
        return process

    monkeypatch.setattr(qa, "_launch", launch)
    yield state, checkout, children, launches
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def read_record(state, name="dev"):
    return json.loads((state / f"{name}.json").read_text())


def test_start_list_stop(managed, capsys):
    state, checkout, children, _ = managed
    assert qa.main(["start"]) == 0
    record = read_record(state)
    assert record["name"] == "dev"
    assert record["port"] == 14900
    assert record["pid"] == children[0].pid
    assert record["pygserver_dir"] == str(checkout)
    assert record["serverside"] is True
    assert record["starter"] == "offline-test"
    assert record["source_stamp"] == qa.source_stamp(checkout)
    assert abs(record["started"] - time.time()) < 5
    assert qa.READY_MARKER in Path(record["log_path"]).read_text()
    assert Path(record["config_path"]).read_text() == (
        "clientsidelinks = true\nclientsidesigns = true\n"
        "name = dev\nserverport = 14900\nnoverifylogin = true\nserverside = true\n")
    assert qa.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "dev live 14900" in output
    assert "ORPHANS" in output
    assert "offline-test" in output
    assert qa.main(["stop", "dev"]) == 0
    assert not qa.is_live(record["pid"])
    assert not (state / "dev.json").exists()
    children[0].wait(timeout=5)


def test_live_name_refusal(managed, capsys):
    assert qa.main(["start"]) == 0
    assert qa.main(["start", "--port", "14902"]) == 2
    error = capsys.readouterr().err
    assert "already live" in error
    assert "pid=" in error and "age=" in error and "run_server.py" in error
    assert len(managed[2]) == 1


def test_refuses_shared_accounts(managed, capsys):
    assert qa.main(["start"]) == 0
    assert qa.main(["start", "--name", "other", "--port", "14902"]) == 2
    assert "accounts directory already used" in capsys.readouterr().err
    assert len(managed[2]) == 1


def test_stale_ensure_restarts_and_preserves_parameters(managed, capsys):
    state, checkout, children, _ = managed
    assert qa.main(["start", "--no-serverside"]) == 0
    original = read_record(state)
    assert not qa.is_stale(original)
    source = checkout / "pygserver" / "server.py"
    newer = original["source_stamp"] + 10
    os.utime(source, (newer, newer))
    assert qa.is_stale(original)
    assert qa.main(["list"]) == 0
    assert "dev stale 14900" in capsys.readouterr().out
    assert qa.main(["ensure"]) == 0
    assert len(children) == 1
    assert qa.main(["ensure", "--fresh"]) == 0
    replacement = read_record(state)
    assert replacement["pid"] != original["pid"]
    assert replacement["source_stamp"] == newer
    assert replacement["serverside"] is False
    assert not qa.is_live(original["pid"])


def test_port_in_use_refusal(managed, monkeypatch, capsys):
    holder = qa._process(os.getpid())
    monkeypatch.setattr(qa, "port_holder", lambda port: holder)
    assert qa.main(["start"]) == 2
    error = capsys.readouterr().err
    assert "port 14900 is in use" in error
    assert f"pid={os.getpid()}" in error
    assert "age=" in error and "cmdline=" in error
    assert managed[2] == []
    assert not list(managed[0].glob("*.json"))
    assert qa.main(["ensure"]) == 2


def test_prune_dead_record(managed, capsys):
    state, _, children, _ = managed
    assert qa.main(["start"]) == 0
    children[0].kill()
    children[0].wait(timeout=5)
    assert qa.main(["list"]) == 0
    assert "dev dead 14900" in capsys.readouterr().out
    assert qa.main(["prune"]) == 0
    assert not (state / "dev.json").exists()


def test_prune_retains_live_record(managed):
    assert qa.main(["start"]) == 0
    assert qa.main(["prune"]) == 0
    assert (managed[0] / "dev.json").exists()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_run_environment_cwd_cleanup_and_exit_code(managed, tmp_path, exit_code):
    state, checkout, children, _ = managed
    output = tmp_path / "command.json"
    command = (
        "import json, os, sys; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(json.dumps([os.getcwd(), "
        "os.environ['PYREBORN_TEST_PORT'], os.environ['PYREBORN_QA_PORT'], "
        "os.environ['PYGSERVER_LEVELS_DIR'], os.environ['PYGSERVER_ACCOUNTS_DIR']])); "
        f"sys.exit({exit_code})")
    assert qa.main(["run", "--", sys.executable, "-c", command, str(output)]) == exit_code
    assert json.loads(output.read_text()) == [os.getcwd(), "14901", "14901",
                                            str(checkout / "levels"),
                                            str(checkout / "accounts")]
    assert not (state / "qa.json").exists()
    assert not qa.is_live(children[0].pid)


def test_run_keeps_server_when_requested(managed):
    assert qa.main(["run", "--keep", "--", sys.executable, "-c", "pass"]) == 0
    record = read_record(managed[0], "qa")
    assert qa.is_live(record["pid"])
    assert qa.main(["stop", "--port", "14901"]) == 0
    assert not (managed[0] / "qa.json").exists()


def test_run_cleans_up_when_command_cannot_launch(managed):
    assert qa.main(["run", "--", "/no-such-qa-test-command"]) == 2
    assert not (managed[0] / "qa.json").exists()
    assert not qa.is_live(managed[2][0].pid)


def test_run_cleans_up_on_termination(managed, monkeypatch):
    def interrupted(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(qa.subprocess, "run", interrupted)
    assert qa.main(["run", "--", "unused"]) == 128 + signal.SIGTERM
    assert not (managed[0] / "qa.json").exists()
    assert not qa.is_live(managed[2][0].pid)


def test_world_isolation_and_restart(managed, tmp_path):
    state, _, children, launches = managed
    source = tmp_path / "world-source"
    (source / "world").mkdir(parents=True)
    (source / "world" / "start.nw").write_text("level")
    (source / "config").mkdir()
    options = "gmaps = test.gmap\nserverport = 12345\nserverside = false\n"
    (source / "config" / "serveroptions.txt").write_text(options)
    (source / "weapons").mkdir()
    (source / "weapons" / "test.txt").write_text("weapon")
    assert qa.main(["start", "--world", str(source)]) == 0
    server = launches[0]
    assert server.is_dir()
    assert (server / "world").resolve() == source / "world"
    config = (server / "config" / "serveroptions.txt").read_text()
    assert "gmaps = test.gmap" in config
    assert config.endswith("serverside = true\n")
    assert "serverport = 14900\n" in config
    assert not (server / "weapons" / "test.txt").is_symlink()
    assert (source / "config" / "serveroptions.txt").read_text() == options
    (server / "accounts" / "saved.json").write_text("{}")
    assert qa.main(["restart", "dev"]) == 0
    assert read_record(state)["world"] == str(source)
    assert (server / "accounts" / "saved.json").exists()
    assert len(children) == 2
    # Another world instance uses a separate accounts directory.
    assert qa.main(["start", "--name", "other", "--port", "14902", "--world", str(source)]) == 0
    assert launches[-1] != server
    assert qa.main(["stop", "--all"]) == 0
    assert not list(state.glob("*.json"))


def test_reused_pid_never_signalled(managed, monkeypatch):
    state, _, _, _ = managed
    assert qa.main(["start"]) == 0
    record = read_record(state)
    record["pid"] = os.getpid()  # This pytest process is not a server runner.
    (state / "dev.json").write_text(json.dumps(record))
    with monkeypatch.context() as patch:
        patch.setattr(qa.os, "kill", lambda *args: pytest.fail("signalled an unrelated PID"))
        assert qa.main(["stop", "dev"]) == 0
    assert not (state / "dev.json").exists()


def test_orphan_report_and_targeted_cleanup(managed, monkeypatch, capsys):
    state, _, children, _ = managed
    assert qa.main(["start"]) == 0
    record = read_record(state)
    assert all(process["pid"] != record["pid"] for process in qa.orphans())
    (state / "dev.json").unlink()
    found = [process for process in qa.orphans() if process["pid"] == record["pid"]]
    assert len(found) == 1
    assert found[0]["age"] >= 0
    assert found[0]["cwd"] == str(managed[1])
    assert "run_server.py" in found[0]["cmdline"]
    assert qa.main(["list"]) == 0
    assert str(record["pid"]) in capsys.readouterr().out.split("ORPHANS")[1]
    # Never touch real unrecorded servers belonging to the developer.
    monkeypatch.setattr(qa, "orphans", lambda: found)
    assert qa.main(["stop", "--orphans"]) == 0
    assert not qa.is_live(children[0].pid)


@pytest.mark.parametrize("family", ["tcp", "tcp6"])
def test_proc_port_holder_orphan_port_and_unknown_fallback(tmp_path, monkeypatch, family, capsys):
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    for name in ("tcp", "tcp6"):
        # Proc's inode column is field 9; non-listening sockets are ignored.
        address = "00000000" if name == "tcp" else "0" * 32
        rows = f"0: {address}:3A34 00000000:0000 01 0:0 0:0 0 1000 0 999\n"
        if name == family:
            rows += f"1: {address}:3A34 00000000:0000 0A 0:0 0:0 0 1000 0 123\n"
        (proc / "net" / name).write_text("header\n" + rows)
    pid = 1234
    root = proc / str(pid)
    (root / "fd").mkdir(parents=True)
    (root / "fd" / "5").symlink_to("socket:[123]")
    (root / "stat").write_text(f"{pid} (runner (worker)) S " + "0 " * 18 + "100\n")
    (root / "cmdline").write_bytes(b"python\0run_server.py\0")
    (root / "cwd").symlink_to(tmp_path, target_is_directory=True)
    (proc / "uptime").write_text("1000 0\n")

    def proc_path(path):
        path = Path(path)
        return proc / path.relative_to("/proc") if path.is_relative_to("/proc") else path

    monkeypatch.setattr(qa, "Path", proc_path)
    monkeypatch.setenv("PYREBORN_QA_SERVERS_DIR", str(tmp_path / "state"))
    assert qa._listeners() == {"123": 14900}
    assert qa._socket_owners({"123"}) == {"123": pid}
    assert qa.port_holder(14900)["pid"] == pid
    assert qa.port_holder(14901) is None
    assert qa.orphans()[0]["ports"] == [14900]
    assert qa.main(["start"]) == 2
    error = capsys.readouterr().err
    assert "pid=1234" in error and "age=" in error and "cmdline=python run_server.py" in error
    monkeypatch.setattr(qa, "_socket_owners", lambda inodes: {})
    assert qa.port_holder(14900)["pid"] == "unknown"


def test_early_exit_has_no_record(managed, monkeypatch, capsys):
    def launch(directory, config, log):
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(9)"],
                                   stdout=log, stderr=subprocess.STDOUT)
        managed[2].append(process)
        return process

    monkeypatch.setattr(qa, "_launch", launch)
    assert qa.main(["start"]) == 2
    assert "exited early (code=9)" in capsys.readouterr().err
    assert not (managed[0] / "dev.json").exists()


def test_launch_uses_python_child_and_new_session(tmp_path, monkeypatch):
    captured = {}

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return "process"

    monkeypatch.setattr(qa.subprocess, "Popen", popen)
    assert qa._launch(tmp_path, tmp_path / "options.txt", "log") == "process"
    assert captured["command"] == [sys.executable, "run_server.py", str(tmp_path / "options.txt")]
    assert captured["cwd"] == str(tmp_path)
    assert captured["start_new_session"] is True
    assert captured["stderr"] == subprocess.STDOUT
    assert captured["stdout"] == "log"
    assert captured["env"]["PYGSERVER_QA"] == "1"


# --- fixtures provisioned by `start` do not outlive the server ---------------

def test_stop_removes_the_fixture_and_the_directory_start_created(managed):
    from game_tester.spar_fixture import SPAR_LEVEL
    state, checkout, _, _ = managed
    assert not (checkout / "levels").exists()
    assert qa.main(["start"]) == 0
    assert (checkout / "levels" / SPAR_LEVEL).is_file()
    assert read_record(state)["fixtures"]
    assert qa.main(["stop", "dev"]) == 0
    assert not (checkout / "levels").exists()
    assert not (state / "dev.serveroptions.txt").exists()


def test_stop_keeps_a_preexisting_matching_fixture_and_its_directory(managed):
    from game_tester.spar_fixture import SPAR_LEVEL, write_spar_fixture
    state, checkout, _, _ = managed
    write_spar_fixture(checkout / "levels")
    (checkout / "levels" / "keep.nw").write_text("level")
    assert qa.main(["start"]) == 0
    assert read_record(state)["fixtures"] == []
    assert qa.main(["stop", "dev"]) == 0
    assert (checkout / "levels" / SPAR_LEVEL).is_file()
    assert (checkout / "levels" / "keep.nw").is_file()


def test_prune_removes_the_fixture_of_a_dead_server(managed):
    from game_tester.spar_fixture import SPAR_LEVEL
    _, checkout, children, _ = managed
    assert qa.main(["start"]) == 0
    children[0].kill()
    children[0].wait(timeout=5)
    assert (checkout / "levels" / SPAR_LEVEL).is_file()
    assert qa.main(["prune"]) == 0
    assert not (checkout / "levels").exists()


def test_failed_start_removes_the_fixture(managed, monkeypatch):
    _, checkout, _, _ = managed

    def launch(directory, config, log):
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(9)"],
                                   stdout=log, stderr=subprocess.STDOUT)
        managed[2].append(process)
        return process

    monkeypatch.setattr(qa, "_launch", launch)
    assert qa.main(["start"]) == 2
    assert not (checkout / "levels").exists()
    assert not (managed[0] / "dev.serveroptions.txt").exists()


def test_launch_failure_removes_the_fixture_and_options_file(managed, monkeypatch):
    state, checkout, _, _ = managed

    def launch(directory, config, log):
        raise OSError("cannot exec")

    monkeypatch.setattr(qa, "_launch", launch)
    assert qa.main(["start"]) == 2
    assert not (checkout / "levels").exists()
    assert not (state / "dev.serveroptions.txt").exists()


def test_partial_fixture_write_is_released(managed, monkeypatch):
    state, checkout, _, _ = managed
    from game_tester import fixtures

    real = fixtures.Path.write_bytes

    def write_bytes(self, data):
        if "qa_sparzone.nw" in self.name:       # the atomic write's temp file
            real(self, data[:5])        # a truncated write, then the failure
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(fixtures.Path, "write_bytes", write_bytes)
    assert qa.main(["start"]) == 2
    assert not (checkout / "levels").exists()
    assert not (state / "dev.serveroptions.txt").exists()


def test_a_symlink_at_the_fixture_path_refuses_the_start(managed, tmp_path):
    from game_tester.spar_fixture import SPAR_LEVEL
    state, checkout, _, _ = managed
    (checkout / "levels").mkdir()
    (checkout / "levels" / SPAR_LEVEL).symlink_to(tmp_path / "nowhere.nw")
    assert qa.main(["start"]) == 2
    assert (checkout / "levels" / SPAR_LEVEL).is_symlink()
    assert not (tmp_path / "nowhere.nw").exists()
    assert not (state / "dev.serveroptions.txt").exists()


def test_failed_restart_over_a_dead_record_leaves_no_record(managed, monkeypatch):
    from game_tester.spar_fixture import SPAR_LEVEL
    state, checkout, children, _ = managed
    assert qa.main(["start"]) == 0
    children[0].kill()
    children[0].wait(timeout=5)
    assert (state / "dev.json").exists()
    monkeypatch.setattr(qa, "_launch", lambda d, c, log: (_ for _ in ()).throw(OSError("x")))
    assert qa.main(["start"]) == 2
    assert not (state / "dev.json").exists()
    # A prune after this must not re-release a file another run owns now.
    from game_tester.spar_fixture import spar_fixture
    live = spar_fixture(checkout / "levels")
    live.install()
    assert qa.main(["prune"]) == 0
    assert (checkout / "levels" / SPAR_LEVEL).is_file()
    live.release()


def test_run_leaves_no_fixture_behind(managed):
    _, checkout, _, _ = managed
    assert qa.main(["run", "--", sys.executable, "-c", "pass"]) == 0
    assert not (checkout / "levels").exists()


def test_stop_removes_empty_directories_the_server_created(managed, monkeypatch):
    """pygserver mkdirs `world/`, `gani/`... in its cwd at startup (they show up
    as empty untracked directories); only those it created, and only if empty."""
    state, checkout, children, _ = managed
    (checkout / "gani").mkdir()                     # already ours: never removed
    real_launch = qa._launch

    def launch(directory, config, log):
        process = real_launch(directory, config, log)
        for name in ("world", "images", "gani"):
            (checkout / name).mkdir(exist_ok=True)
        return process

    monkeypatch.setattr(qa, "_launch", launch)
    assert qa.main(["start"]) == 0
    (checkout / "images" / "kept.png").write_bytes(b"x")   # no longer empty
    assert qa.main(["stop", "dev"]) == 0
    assert not (checkout / "world").exists()
    assert (checkout / "images" / "kept.png").exists()
    assert (checkout / "gani").is_dir()


def _world_source(tmp_path):
    source = tmp_path / "world-source"
    (source / "world").mkdir(parents=True)
    (source / "world" / "start.nw").write_text("level")
    (source / "images").mkdir()
    (source / "images" / "tiles.png").write_bytes(b"png")
    return source


def test_stop_keeps_log_and_world_without_purge(managed, tmp_path):
    state, _, _, launches = managed
    source = _world_source(tmp_path)
    assert qa.main(["start", "--name", "keep", "--world", str(source)]) == 0
    (launches[0] / "accounts" / "saved.json").write_text("{}")
    assert qa.main(["stop", "keep"]) == 0
    assert (state / "keep.log").is_file()
    assert (state / "keep.world" / "accounts" / "saved.json").is_file()


def test_stop_purge_removes_log_and_world_but_not_the_source(managed, tmp_path):
    state, _, children, launches = managed
    source = _world_source(tmp_path)
    assert qa.main(["start", "--name", "gone", "--world", str(source)]) == 0
    assert qa.main(["start", "--name", "stays", "--port", "14902",
                    "--world", str(source)]) == 0
    (launches[0] / "accounts" / "saved.json").write_text("{}")
    assert (launches[0] / "images").is_symlink()
    assert qa.main(["stop", "--purge", "gone"]) == 0
    assert not qa.is_live(children[0].pid)
    assert not (state / "gone.log").exists()
    assert not (state / "gone.world").exists()
    assert not (state / "gone.json").exists()
    # rmtree unlinked the staging symlinks without descending into them.
    assert (source / "world" / "start.nw").read_text() == "level"
    assert (source / "images" / "tiles.png").read_bytes() == b"png"
    # Another server's files are not touched.
    assert (state / "stays.log").is_file()
    assert (state / "stays.world").is_dir()
    assert qa.main(["stop", "--purge", "--all"]) == 0
    assert not (state / "stays.world").exists()
    assert not list(state.glob("*.log"))


def test_purge_unlinks_a_symlinked_world_without_following_it(managed, tmp_path):
    state, _, _, _ = managed
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    state.mkdir(parents=True, exist_ok=True)
    (state / "odd.world").symlink_to(target, target_is_directory=True)
    qa._purge("odd")
    assert not (state / "odd.world").exists()
    assert (target / "keep.txt").read_text() == "x"


# --- staff provisioning (--staff) -------------------------------------------

def _tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


def test_staff_on_a_world_writes_only_into_the_private_root(managed, tmp_path):
    state, checkout, _, _ = managed
    source = _world_source(tmp_path)
    (checkout / "accounts").mkdir()
    before = (_tree(checkout), _tree(source))
    assert qa.main(["start", "--name", "st", "--world", str(source),
                    "--staff", "qastaff", "--staff", "other_one"]) == 0
    record = read_record(state, "st")
    accounts = state / "st.world" / "accounts"
    data = json.loads((accounts / "qastaff.json").read_text())
    assert data["account_name"] == "qastaff"
    assert data["admin_rights"] == 0xFFFFF
    assert data["admin_ip"] == "127.0.0.1"
    assert data["folders"] == ["rw world/*"]
    assert (accounts / "other_one.json").is_file()
    assert "staff = qastaff,other_one\n" in Path(record["config_path"]).read_text()
    assert record["staff"] == ["qastaff", "other_one"]
    # Spar fixture aside (it lives in the source world and is removed on stop),
    # nothing appeared in the checkout or the shared accounts directory.
    assert _tree(checkout / "accounts") == []
    assert qa.main(["stop", "st"]) == 0
    assert (_tree(checkout), _tree(source)) == before
    assert not (accounts / "qastaff.json").exists()
    assert not (accounts / "other_one.json").exists()
    assert not Path(record["config_path"]).exists()


def test_staff_on_the_default_world_stages_a_private_root(managed):
    state, checkout, _, launches = managed
    (checkout / "levels").mkdir()
    (checkout / "weapons").mkdir()
    (checkout / "weapons" / "w.txt").write_text("w")
    (checkout / "gani").mkdir()
    (checkout / "accounts").mkdir()
    assert qa.main(["start", "--name", "dflt", "--staff", "qastaff"]) == 0
    record = read_record(state, "dflt")
    server = state / "dflt.world"
    assert launches[-1] == server
    assert record["staged"] is True
    assert (server / "world").resolve() == (checkout / "levels").resolve()
    assert (server / "weapons" / "w.txt").read_text() == "w"
    assert (server / "gani").resolve() == (checkout / "gani").resolve()
    assert record["accounts_dir"] == str(server / "accounts")
    assert (server / "accounts" / "qastaff.json").is_file()
    assert _tree(checkout / "accounts") == []
    # A staged default does not block a bare default start's accounts check.
    assert qa.main(["stop", "dflt"]) == 0
    assert not (server / "accounts" / "qastaff.json").exists()
    assert _tree(checkout / "accounts") == []


def test_no_staff_option_writes_no_staff_and_keeps_todays_options(managed, tmp_path):
    state, checkout, _, launches = managed
    assert qa.main(["start"]) == 0
    record = read_record(state)
    assert "staff" not in Path(record["config_path"]).read_text()
    assert record["staff"] == []
    assert "staged" not in record
    assert launches[-1] == Path(record["config_path"])
    assert not (state / "dev.world").exists()
    assert qa.main(["stop", "dev"]) == 0
    source = _world_source(tmp_path)
    assert qa.main(["start", "--name", "w", "--world", str(source)]) == 0
    assert "staff" not in Path(read_record(state, "w")["config_path"]).read_text()
    assert _tree(state / "w.world" / "accounts") == []


def test_existing_staff_account_is_refused_before_writes(managed, tmp_path, capsys):
    state, _, _, _ = managed
    source = _world_source(tmp_path)
    accounts = state / "keep.world" / "accounts"
    accounts.mkdir(parents=True)
    saved = accounts / "testbot1.json"
    original = b'{ "x": 7, "admin_rights": 1 }\n'
    saved.write_bytes(original)
    marker = accounts.parent / "keep.txt"
    marker.write_text("untouched")
    config = state / "keep.serveroptions.txt"
    config.write_text("unchanged options\n")
    before = _tree(state)
    assert qa.main(["start", "--name", "keep", "--world", str(source),
                    "--staff", "fresh", "--staff", "testbot1"]) == 2
    assert str(saved) in capsys.readouterr().err
    assert saved.read_bytes() == original
    assert marker.read_text() == "untouched"
    assert config.read_text() == "unchanged options\n"
    assert [p for p in _tree(state) if p != ".lock"] == before
    with pytest.raises(ValueError, match="testbot1.json"):
        qa._write_staff_accounts(accounts, ["fresh", "testbot1"])
    assert not (accounts / "fresh.json").exists()

    assert qa.main(["start", "--name", "keep", "--world", str(source),
                    "--staff", "fresh"]) == 0
    assert read_record(state, "keep")["staff_files"] == [str(accounts / "fresh.json")]
    assert qa.main(["stop", "keep"]) == 0
    assert not (accounts / "fresh.json").exists()
    assert saved.read_bytes() == original


def test_bad_staff_names_are_refused(managed, tmp_path, capsys):
    state, _, _, _ = managed
    source = _world_source(tmp_path)
    assert qa.main(["start", "--name", "bad", "--world", str(source), "--staff", "../evil"]) == 2
    assert "staff account" in capsys.readouterr().err
    assert not (state / "bad.json").exists()


@pytest.mark.parametrize("phase", ["fixture", "launch", "wait"])
@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_failed_staff_start_removes_account_and_next_start_resets_options(
        managed, tmp_path, monkeypatch, phase, error):
    from game_tester.fixtures import FixtureFile

    state, _, _, _ = managed
    source = _world_source(tmp_path)
    account = state / "dev.world" / "accounts" / "qastaff.json"
    config = state / "dev.serveroptions.txt"

    def fail(*args):
        assert account.is_file()
        assert "staff = qastaff\n" in config.read_text()
        raise error("startup failed")

    with monkeypatch.context() as patch:
        if phase == "fixture":
            patch.setattr(FixtureFile, "install", fail)
        elif phase == "launch":
            patch.setattr(qa, "_launch", fail)
        else:
            patch.setattr(qa, "_log_tail", fail)
        with qa._locked(), pytest.raises(error, match="startup failed"):
            qa.start(world=source, staff=["qastaff"])
    assert not account.exists()
    assert not (state / "dev.json").exists()
    assert not config.exists()
    # Every start rewrites options, including any stale generated staff line.
    config.write_text("staff = qastaff\n")
    assert qa.main(["start", "--world", str(source)]) == 0
    assert _tree(account.parent) == []
    assert "staff =" not in config.read_text()
    assert qa.main(["stop", "dev"]) == 0


def test_prune_removes_only_created_staff_accounts(managed, tmp_path):
    state, _, children, _ = managed
    source = _world_source(tmp_path)
    accounts = state / "dev.world" / "accounts"
    accounts.mkdir(parents=True)
    saved = accounts / "saved.json"
    saved.write_bytes(b'{"x": 5}\n')
    assert qa.main(["start", "--world", str(source), "--staff", "qastaff"]) == 0
    children[-1].kill()
    children[-1].wait(timeout=5)
    assert qa.main(["prune"]) == 0
    assert not (accounts / "qastaff.json").exists()
    assert saved.read_bytes() == b'{"x": 5}\n'


def test_run_with_staff_restarts_a_live_server_that_lacks_it(managed, tmp_path):
    state, checkout, _, _ = managed
    (checkout / "levels").mkdir()
    assert qa.main(["start", "--name", "r", "--port", "14903"]) == 0
    first = read_record(state, "r")["pid"]
    record = qa.ensure("r", 14903, fresh=True, staff=["qastaff"])
    assert record["pid"] != first and record["staff"] == ["qastaff"]
    again = qa.ensure("r", 14903, fresh=True, staff=["qastaff"])
    assert again["pid"] == record["pid"]
    assert qa.main(["stop", "r"]) == 0
