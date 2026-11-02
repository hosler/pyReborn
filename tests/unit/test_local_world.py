"""Filesystem/lifecycle tests, plus an opt-in-by-capability real socket login."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from game_tester.local_world import LocalWorld


@pytest.fixture
def server_source(tmp_path):
    source = tmp_path / "server"
    for name in ("world", "weapons", "npcs", "config"):
        (source / name).mkdir(parents=True)
    for name in ("aaa.nw", "lobby.nw", "start.nw"):
        (source / "world" / name).write_text("GLEVNW01\n")
    (source / "weapons" / "weaponDemo.txt").write_text(
        "GRAWP001\nREALNAME Demo\nIMAGE demo.png\nSCRIPT\n"
        "//#CLIENTSIDE\nif (created) { setimg demo.png; }\nSCRIPTEND\n")
    (source / "npcs" / "demo.py").write_text("class Demo:\n    pass\n")
    (source / "config" / "serveroptions.txt").write_bytes(
        b"# startlevel = ignored.nw\r\n// gmaps = ignored.gmap\r\n"
        b"unrelated option\r\nUNSTICKMELEVEL = lobby.nw\r\n"
        b"gmaps = first.gmap, second.gmap, \r\nserverport = 9999\r\n"
        b"serverside = false # classic script mode\r\n")
    return source


@pytest.mark.parametrize("mode", ["detected", "source_only", "explicit_world"])
def test_server_directory_defaults_and_layout(server_source, mode):
    from pygserver.config import ServerConfig
    if mode == "detected":
        local = LocalWorld(server_source)
    elif mode == "source_only":
        local = LocalWorld(server_dir_source=server_source)
    else:
        local = LocalWorld(server_source / "world", server_dir_source=server_source)
    try:
        local.prepare()
        assert local.server_dir_source == server_source
        assert local.world_dir == server_source / "world"
        assert local.weapons_dir == server_source / "weapons"
        assert local.npcs_dir == server_source / "npcs"
        for name in ("world", "npcs"):
            assert (local.server_dir / name).is_symlink()
            assert (local.server_dir / name).resolve() == server_source / name
        assert not (local.server_dir / "weapons").is_symlink()
        assert ((local.server_dir / "weapons" / "weaponDemo.txt").read_bytes() ==
                (server_source / "weapons" / "weaponDemo.txt").read_bytes())
        config = ServerConfig.from_server_dir(str(local.server_dir))
        assert config.start_level == local.start_level == "lobby.nw"
        assert config.gmaps == local.gmaps == ["first.gmap", "second.gmap"]
        assert config.port == 0  # Source network settings are not inherited.
        assert config.serverside is False
        account = json.loads((local.server_dir / "accounts" / "testbot1.json").read_text())
        assert account["level_name"] == "lobby.nw"
        assert local.start_xy == (30.0, 30.5)
    finally:
        local.close()
    assert (server_source / "world" / "lobby.nw").is_file()
    assert (server_source / "npcs" / "demo.py").is_file()


@pytest.mark.parametrize("start_option, expected", [
    ("startlevel = start.nw\n", "start.nw"),
    ("startlevel = \n", "lobby.nw"),
])
def test_server_startlevel_precedes_unstick_default(server_source, start_option, expected):
    options = server_source / "config" / "serveroptions.txt"
    options.write_text(options.read_text() + start_option)
    local = LocalWorld(server_source)
    try:
        assert local.start_level == expected
    finally:
        local.close()


@pytest.mark.parametrize("gmaps, expected", [("override.gmap", ["override.gmap"]), ([], [])])
def test_server_explicit_arguments_override_defaults(server_source, tmp_path, gmaps, expected):
    weapons, npcs = tmp_path / "custom_weapons", tmp_path / "custom_npcs"
    weapons.mkdir()
    npcs.mkdir()
    (weapons / "custom.txt").write_text("custom weapon")
    local = LocalWorld(server_dir_source=server_source, weapons_dir=weapons,
                       npcs_dir=npcs, start_level="explicit.nw", start_xy=(4, 5),
                       gmaps=gmaps)
    try:
        local.prepare()
        assert local.start_level == "explicit.nw"
        assert local.start_xy == (4, 5)
        assert local.gmaps == expected
        assert (local.server_dir / "npcs").resolve() == npcs
        assert (local.server_dir / "weapons" / "custom.txt").read_text() == "custom weapon"
        assert not (local.server_dir / "weapons" / "weaponDemo.txt").exists()
    finally:
        local.close()


def test_server_optional_npcs_and_missing_defaults(server_source):
    (server_source / "npcs" / "demo.py").unlink()
    (server_source / "npcs").rmdir()
    (server_source / "config" / "serveroptions.txt").write_text("# no defaults\n")
    local = LocalWorld(server_source)
    try:
        local.prepare()
        assert local.npcs_dir is None
        assert list((local.server_dir / "npcs").iterdir()) == []
        assert not (local.server_dir / "npcs").is_symlink()
        assert local.start_level == "aaa.nw" and local.gmaps == []
    finally:
        local.close()


@pytest.mark.parametrize("child", ["world", "config"])
def test_server_detection_requires_world_and_config(tmp_path, child):
    (tmp_path / child).mkdir()
    (tmp_path / "spawn.nw").write_text("GLEVNW01\n")
    local = LocalWorld(tmp_path)
    try:
        assert local.server_dir_source is None
        assert local.world_dir == tmp_path
        assert local.start_level == "spawn.nw"
    finally:
        local.close()


def test_weapon_compilation_caches_stay_in_temp_directory(server_source, tmp_path, monkeypatch):
    from pygserver import gs2
    from pygserver.config import ServerConfig
    # Also cover symlinked source files and pre-existing cache symlinks.
    source_weapon = server_source / "weapons" / "weaponDemo.txt"
    shared_weapon = tmp_path / "shared.txt"
    shared_weapon.write_bytes(source_weapon.read_bytes())
    source_weapon.unlink()
    source_weapon.symlink_to(shared_weapon)
    shared_cache = tmp_path / "shared.gs2bc"
    shared_cache.write_bytes(b"old")
    (source_weapon.with_suffix(".gs2bc")).symlink_to(shared_cache)
    compiler = SimpleNamespace(available=True, compile=Mock(return_value=b"compiled"))
    monkeypatch.setattr(gs2, "GS2Compiler", lambda: compiler)
    local = LocalWorld(server_source)
    try:
        local.prepare()
        weapon = local.server_dir / "weapons" / "weaponDemo.txt"
        cache = weapon.with_suffix(".gs2bc")
        assert not weapon.is_symlink() and not cache.is_symlink()
        # Force the copied cache to be stale, without touching the source.
        import os
        os.utime(cache, (1, 1))
        manager = gs2.GS2ScriptManager(SimpleNamespace(
            config=ServerConfig.from_server_dir(str(local.server_dir))), str(local.server_dir))
        manager.load()
        assert manager.get_weapon("Demo").bytecode == b"compiled"
        assert cache.read_bytes() == b"compiled"
        assert shared_cache.read_bytes() == b"old"
        assert source_weapon.is_symlink()
        assert source_weapon.read_bytes() == shared_weapon.read_bytes()
        cache.unlink()
        local.prepare()  # Repeated prepares preserve edits to private weapons.
        assert not cache.exists()
    finally:
        local.close()


def test_launcher_npc_import_keeps_symlinked_source_read_only(server_source, monkeypatch):
    import subprocess
    import game_tester.local_world as module
    monkeypatch.setattr(module, "_BOOTSTRAP", """
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]) / 'npcs' / 'demo.py'
spec = importlib.util.spec_from_file_location('demo', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.Demo.__name__ == 'Demo'
""")
    local = LocalWorld(server_source)
    try:
        local.prepare()
        subprocess.run(local._command(), check=True, capture_output=True)
        assert list((server_source / "npcs").iterdir()) == [server_source / "npcs" / "demo.py"]
    finally:
        local.close()


@pytest.mark.parametrize("gmap_suite", [False, True])
def test_world_arguments_detect_server_and_allow_source_overrides(server_source, tmp_path, gmap_suite):
    import argparse
    from game_tester.local_world import add_world_arguments, world_from_arguments
    parser = argparse.ArgumentParser()
    add_world_arguments(parser, gmap_suite=gmap_suite)
    weapons, npcs = tmp_path / "weapons", tmp_path / "npcs"
    weapons.mkdir()
    npcs.mkdir()
    for overrides in ([], ["--weapons", str(weapons), "--npcs", str(npcs),
                          "--gmap", "custom.gmap", "--start", "start.nw", "2", "3"]):
        args = parser.parse_args(["--world", str(server_source), *overrides])
        local = world_from_arguments(args)
        try:
            local.prepare()
            assert local.server_dir_source == server_source
            assert local.weapons_dir == (weapons if overrides else server_source / "weapons")
            assert local.npcs_dir == (npcs if overrides else server_source / "npcs")
            assert local.start_level == ("start.nw" if overrides else "lobby.nw")
            assert local.gmaps == (["custom.gmap"] if overrides else ["first.gmap", "second.gmap"])
        finally:
            local.close()


def test_sibling_server_directory_detection():
    source = Path("/home/hosler/Projects/opengraal2/Preagonal/graal-bomber-gs1")
    if not source.is_dir():
        pytest.skip("sibling third-party server not available")
    local = LocalWorld(source)
    try:
        local.prepare()
        assert local.server_dir_source == source
        assert local.start_level == "bomblobby.nw"
        assert (local.server_dir / "world").is_symlink()
        assert (local.server_dir / "world").resolve() == source / "world"
        assert (local.server_dir / "world" / "bomblobby.nw").is_file()
        weapons = list((local.server_dir / "weapons").glob("*.txt"))
        assert len(weapons) == 13
        assert all(path.read_bytes().startswith(b"GRAWP001") for path in weapons)
        assert not (local.server_dir / "weapons").is_symlink()
    finally:
        local.close()


@pytest.fixture
def world(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "spawn.nw").write_text("GLEVNW01\n")
    local = LocalWorld(source, gmaps=["test.gmap"], start_level="spawn.nw",
                       start_xy=(12, 18.5), port=15432,
                       extra_options={"putnpcenabled": True})
    try:
        yield local.prepare()
    finally:
        local.close()


def test_config_and_account_seeding(world):
    from pygserver.account import Account
    from pygserver.config import ServerConfig
    options = (world.server_dir / "config" / "serveroptions.txt").read_text()
    assert "serverport = 15432\n" in options
    assert "noverifylogin = true\n" in options
    assert "staff = testbot1,testbot2\n" in options
    assert "gmaps = test.gmap\n" in options
    assert "startlevel = spawn.nw\n" in options
    assert "startx = 12\n" in options
    assert "starty = 18.5\n" in options
    assert "putnpcenabled = true\n" in options
    config = ServerConfig.from_server_dir(str(world.server_dir))
    assert Path(config.levels_dir).resolve() == world.world_dir
    assert config.gmaps == ["test.gmap"]
    assert not config.verify_login
    assert config.staff == ["testbot1", "testbot2"]
    for name in world.accounts:
        data = json.loads((world.server_dir / "accounts" / f"{name}.json").read_text())
        expected = Account(account_name=name, level_name="spawn.nw", x=12,
                           y=18.5, is_staff=True)
        expected.set_password("testpass")
        assert data == expected.to_dict()
        assert data["hearts"] == data["max_hearts"] == 3
        assert (data["bombs"], data["arrows"], data["weapons"]) == (10, 5, [])
    # prepare is idempotent; it must never reset played account state.
    account = world.server_dir / "accounts" / "testbot1.json"
    account.write_text('{"played": true}')
    world.prepare()
    assert json.loads(account.read_text()) == {"played": True}
    assert list(world.world_dir.iterdir()) == [world.world_dir / "spawn.nw"]


def test_fresh_instances_start_identically(world):
    other = LocalWorld(world.world_dir, gmaps="test.gmap", start_level="spawn.nw",
                       start_xy=(12, 18.5))
    try:
        other.prepare()  # No free-port socket needed.
        assert other.port is None
        for name in world.accounts:
            assert ((world.server_dir / "accounts" / f"{name}.json").read_bytes() ==
                    (other.server_dir / "accounts" / f"{name}.json").read_bytes())
    finally:
        other.close()


def test_snapshot_restore_exact_roundtrip(world):
    accounts = world.server_dir / "accounts"
    before = {p.name: p.read_bytes() for p in accounts.glob("*.json")}
    snapshot = world.snapshot("initial")
    assert snapshot == world.server_dir / "snapshots" / "initial"
    (accounts / "testbot1.json").write_text('{"hearts": 1, "flags": {"win": "1"}}')
    (accounts / "testbot2.json").unlink()
    (accounts / "newcomer.json").write_text("{}")
    world.restore("initial")
    assert {p.name: p.read_bytes() for p in accounts.glob("*.json")} == before
    with pytest.raises(FileExistsError):
        world.snapshot("initial")
    with pytest.raises(FileNotFoundError):
        world.restore("missing")


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".", "../accounts"])
def test_reject_path_traversal(world, name):
    with pytest.raises(ValueError):
        world.snapshot(name)
    with pytest.raises(ValueError):
        world.restore(name)


def test_restore_refuses_registered_connected_bot(world):
    class Bot:
        name = "newbot"
        connected = True
    bot = Bot()
    world.register_bot(bot)
    assert json.loads((world.server_dir / "accounts" / "newbot.json").read_text())["level_name"] == "spawn.nw"
    bot.connected = False
    world.snapshot("before")
    bot.connected = True
    with pytest.raises(RuntimeError, match="newbot"):
        world.restore("before")
    with pytest.raises(RuntimeError, match="newbot"):
        world.snapshot("online")
    bot.connected = False
    world.restore("before")


def test_gamebot_registers_automatically(world):
    from game_tester.game_bot import GameBot
    world._process = SimpleNamespace(poll=lambda: None)
    try:
        bot = GameBot("dynamic", world.host, world.port)
        assert bot in world._bots
        assert (world.server_dir / "accounts" / "dynamic.json").exists()
    finally:
        world._process = None


def test_crashed_server_fails_quickly_with_log_tail(world, monkeypatch):
    world.startup_timeout = 120
    monkeypatch.setattr(world, "_command", lambda: [
        sys.executable, "-u", "-c", "print('deliberate startup failure'); raise SystemExit(7)"])
    start = time.monotonic()
    with pytest.raises(RuntimeError, match=r"(?s)exited early \(code=7\).*deliberate startup failure") as error:
        world.start()
    assert "deliberate startup failure" in str(error.value)
    assert time.monotonic() - start < 3
    assert not world.running


def test_successful_readiness_and_shutdown_without_sockets(world, monkeypatch):
    monkeypatch.setattr(world, "_command", lambda: [
        sys.executable, "-u", "-c",
        "import time; print('Server listening on 127.0.0.1:15432'); time.sleep(60)"])
    assert world.start() is world
    assert world.running
    assert world.start() is world
    process = world._process
    world.stop()
    assert process.poll() is not None
    world.stop()


def test_restore_restarts_to_drop_account_cache(world, monkeypatch):
    world.snapshot("initial")
    world._process = SimpleNamespace(poll=lambda: None)
    calls = []
    def stop():
        calls.append("stop")
        (world.server_dir / "accounts" / "testbot1.json").write_text('{"cached": true}')
    def start():
        data = json.loads((world.server_dir / "accounts" / "testbot1.json").read_text())
        assert "cached" not in data
        calls.append("start")
    monkeypatch.setattr(world, "stop", stop)
    monkeypatch.setattr(world, "start", start)
    world.restore("initial")
    assert calls == ["stop", "start"]
    world._process = None
    monkeypatch.undo()


def test_timeout_stops_process(world, monkeypatch):
    monkeypatch.setattr(world, "startup_timeout", 0.15)
    monkeypatch.setattr(world, "_command", lambda: [
        sys.executable, "-u", "-c", "import time; print('not listening'); time.sleep(60)"])
    with pytest.raises(TimeoutError, match="not listening"):
        world.start()
    assert not world.running


@pytest.fixture
def mocked_launcher(monkeypatch):
    import game_tester.local_world as module
    observed = []
    original_start = LocalWorld.start
    original_wait = LocalWorld._wait_for_ready

    def launch(*args, **kwargs):
        kwargs["stdout"].write(b"Server listening on 127.0.0.1:15432\n")
        kwargs["stdout"].flush()
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = lambda: setattr(process.poll, "return_value", 0)
        return process

    def start(local):
        local.port = 15432  # Bypass free-port sockets in both entry points.
        return original_start(local)

    def wait(local):
        observed.append(local.startup_timeout)
        return original_wait(local)

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(LocalWorld, "start", start)
    monkeypatch.setattr(LocalWorld, "_wait_for_ready", wait)
    return observed


@pytest.mark.parametrize("timeout, expected", [(None, 20.0), (75.5, 75.5)])
def test_startup_timeout_kwarg_reaches_readiness(world, mocked_launcher, timeout, expected):
    local = LocalWorld(world.world_dir, startup_timeout=timeout)
    try:
        local.start()
        assert mocked_launcher == [expected]
    finally:
        local.close()


@pytest.mark.parametrize("entry", ["cli", "daemon"])
@pytest.mark.parametrize("flags, expected", [([], 120.0), (["--startup-timeout", "75.5"], 75.5)])
def test_cli_startup_timeout_reaches_readiness(world, mocked_launcher, monkeypatch, entry, flags, expected):
    from game_tester import __main__ as cli, playtest_daemon as daemon
    argv = ["--world", str(world.world_dir), *flags]
    if entry == "cli":
        monkeypatch.setattr(cli, "run_single_bot_tests", Mock(return_value=True))
        monkeypatch.setattr(cli, "run_multi_bot_tests", Mock(return_value=True))
        monkeypatch.setattr(sys, "argv", ["game_tester", *argv])
        with pytest.raises(SystemExit) as result:
            cli.main()
        assert result.value.code == 0
    else:
        for name in ("GAME_HOST", "GAME_PORT", "PORT", "running"):
            monkeypatch.setattr(daemon, name, getattr(daemon, name))
        monkeypatch.setattr(daemon, "ThreadingHTTPServer", MagicMock())
        monkeypatch.setattr(daemon.threading, "Thread", Mock())
        daemon.main(["15090", *argv])
    assert mocked_launcher == [expected]


@pytest.mark.integration
@pytest.mark.live
def test_local_world_live_gamebot_login_and_restore():
    """Starts a real server; restricted sandboxes skip on socket PermissionError."""
    from game_tester.game_bot import GameBot
    source = Path(__file__).resolve().parents[3] / "pygserver" / "levels"
    if not source.is_dir():
        pytest.skip("sibling pygserver fixture levels not available")
    world = LocalWorld(source, start_level="onlinestartlocal.nw", start_xy=(30, 30.5))
    try:
        try:
            world.start()
        except PermissionError as exc:
            pytest.skip(f"loopback sockets unavailable: {exc}")
        bot = GameBot("testbot1", world.host, world.port)
        try:
            assert bot.connect(), bot.get_issues()
            assert bot.level == "onlinestartlocal.nw"
            assert (bot.client.x, bot.client.y) == (30, 30.5)
            assert bot.hearts == 3
            with pytest.raises(RuntimeError, match="log out"):
                world.restore("initial")
        finally:
            bot.disconnect()
        world.snapshot("initial")
        world.restore("initial")
        try:
            assert bot.connect(), bot.get_issues()
            assert (bot.client.x, bot.client.y) == (30, 30.5)
        finally:
            bot.disconnect()
    finally:
        world.close()


def test_headless_frame_preserves_order_and_sets_dt():
    from game_tester.headless_client import FakeKeys, pump_frame
    calls = []
    def method(name):
        def run(*args, **kwargs):
            assert game._frame_dt == 0.05
            calls.append(name)
        return run
    names = ("_handle_events", "_handle_input", "_load_new_npcs", "_process_pending_warp",
             "_process_self_shoots", "_check_scripted_link_warp", "_check_level_change",
             "_update_swimming_state", "_update_visual_position", "_update_animations", "_render")
    game = SimpleNamespace(**{name: method(name) for name in names})
    game.client = SimpleNamespace(update=method("update"))
    game.gs1 = SimpleNamespace(process_coroutines=method("gs1.coroutines"),
                               process_timeouts=method("gs1.timeouts"),
                               advance_input_frame=method("advance"))
    game.gs2 = SimpleNamespace(process_coroutines=method("gs2.coroutines"),
                               process_timeouts=method("gs2.timeouts"))
    pump_frame(game, 0.05, 123)
    assert calls == ["_handle_events", "_handle_input", "update", "_load_new_npcs",
                     "_process_pending_warp", "_process_self_shoots", "gs1.coroutines",
                     "gs1.timeouts", "gs2.coroutines", "gs2.timeouts", "_check_scripted_link_warp",
                     "advance", "_check_level_change", "_update_swimming_state",
                     "_update_visual_position", "_update_animations", "_render"]
    assert game._last_dt == 0.05
    keys = FakeKeys()
    keys.set(1073741906, 97)
    assert len(keys) == 512 and keys[1073741906] and keys[97] and not keys[98]


def test_cli_world_and_legacy_gmap_modes(world, monkeypatch):
    from game_tester import __main__ as cli
    import game_tester.local_world as local
    import game_tester.gmap_tests as gmap
    factory = Mock(return_value=world)
    monkeypatch.setattr(local, "world_from_arguments", factory)
    monkeypatch.setattr(world, "start", lambda: world)
    monkeypatch.setattr(world, "close", lambda: None)
    single = Mock(return_value=True)
    multi = Mock(return_value=True)
    monkeypatch.setattr(cli, "run_single_bot_tests", single)
    monkeypatch.setattr(cli, "run_multi_bot_tests", multi)
    monkeypatch.setattr(sys, "argv", ["game_tester", "--world", str(world.world_dir),
                                      "--weapons", str(world.world_dir), "--npcs", str(world.world_dir),
                                      "--gmap", "test.gmap", "--start", "spawn.nw", "12", "18.5"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    assert single.call_args.args[:2] == (world.host, world.port)
    assert multi.call_args.args[:3] == (world.host, world.port, 2)
    args = factory.call_args.args[0]
    assert args.world == world.world_dir and args.start == ["spawn.nw", "12", "18.5"]
    assert args.weapons == args.npcs == world.world_dir
    # Naming a map configures the world and keeps the normal suite selected.
    monkeypatch.setattr(gmap, "run_gmap_tests", Mock(return_value=[]))
    monkeypatch.setattr(sys, "argv", ["game_tester", "--gmap", "--host", "example", "--port", "1234"])
    with pytest.raises(SystemExit):
        cli.main()
    assert gmap.run_gmap_tests.call_args.kwargs == {"host": "example", "port": 1234}


def test_daemon_world_flags_keep_positional_http_port(world, monkeypatch):
    from game_tester import playtest_daemon as daemon
    import game_tester.local_world as local
    factory = Mock(return_value=world)
    monkeypatch.setattr(local, "world_from_arguments", factory)
    monkeypatch.setattr(world, "start", lambda: world)
    monkeypatch.setattr(world, "close", lambda: None)
    server = Mock()
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    server_factory = Mock(return_value=server)
    monkeypatch.setattr(daemon, "ThreadingHTTPServer", server_factory)
    worker = Mock()
    monkeypatch.setattr(daemon.threading, "Thread", Mock(return_value=worker))
    for name in ("GAME_HOST", "GAME_PORT", "PORT", "running"):
        monkeypatch.setattr(daemon, name, getattr(daemon, name))
    daemon.main(["15090", "--world", str(world.world_dir), "--gmap", "test.gmap",
                 "--weapons", str(world.world_dir), "--npcs", str(world.world_dir),
                 "--start", "spawn.nw", "12", "18.5"])
    assert daemon.GAME_HOST == world.host and daemon.GAME_PORT == world.port
    assert server_factory.call_args.args[0] == ("127.0.0.1", 15090)
    assert factory.call_args.args[0].gmap == "test.gmap"
    assert factory.call_args.args[0].weapons == factory.call_args.args[0].npcs == world.world_dir
    server.serve_forever.assert_called_once()
    worker.join.assert_called_once()


@pytest.mark.parametrize("entry", ["cli", "daemon"])
@pytest.mark.parametrize("flag", ["--weapons", "--npcs"])
def test_cli_and_daemon_sources_require_world(entry, flag, tmp_path, monkeypatch, capsys):
    from game_tester import __main__ as cli, playtest_daemon as daemon
    with pytest.raises(SystemExit) as result:
        if entry == "cli":
            monkeypatch.setattr(sys, "argv", ["game_tester", flag, str(tmp_path)])
            cli.main()
        else:
            daemon.main([flag, str(tmp_path)])
    assert result.value.code == 2
    assert "require --world" in capsys.readouterr().err


def test_headless_records_exceptions_and_restores_keyboard(monkeypatch):
    import game_tester.headless_client as module
    wrapper = object.__new__(module.HeadlessGameClient)
    original = lambda: "original"
    wrapper.pygame = SimpleNamespace(key=SimpleNamespace(get_pressed=original))
    wrapper.keys = module.FakeKeys()
    wrapper._closed = False
    wrapper.frame_exceptions = []
    wrapper.game = SimpleNamespace()
    wrapper.client = SimpleNamespace(connected=True, weapons={"one": {}},
                                      _current_level_name="spawn.nw", x=12, y=18.5)
    wrapper.game.gs1 = SimpleNamespace(_progs={"w": {"is_weapon": True}, "npc": {}})
    wrapper.game.gs2 = SimpleNamespace(vms={"weapon": {"two": {}, "three": {}}})
    wrapper._warnings = SimpleNamespace(lines=["a script warning"])
    def broken(*args):
        assert wrapper.pygame.key.get_pressed() is wrapper.keys
        raise ValueError("frame failure")
    monkeypatch.setattr(module, "pump_frame", broken)
    wrapper.frame()
    assert wrapper.pygame.key.get_pressed is original
    report = wrapper.report()
    assert report["level"] == "spawn.nw" and report["pos"] == [12, 18.5]
    assert report["weapon_counts"] == {"client": 1, "gs1": 1, "gs2": 2}
    assert "frame failure" in report["frame_exceptions"][0]
    assert report["warning_log_lines"] == ["a script warning"]


def test_headless_hold_releases_keys_after_failure():
    from game_tester.headless_client import HeadlessGameClient
    wrapper = object.__new__(HeadlessGameClient)
    wrapper._key_codes = lambda keys: keys
    wrapper._set_keys = Mock()
    wrapper.pump = Mock(side_effect=RuntimeError("pump failed"))
    with pytest.raises(RuntimeError, match="pump failed"):
        wrapper.hold([97], 1)
    assert [call.args[0] for call in wrapper._set_keys.call_args_list] == [[97], []]


def test_socket_permission_in_child_is_reported_as_permission_error(world, monkeypatch):
    monkeypatch.setattr(world, "_command", lambda: [sys.executable, "-u", "-c",
                        "raise PermissionError('socket bind denied')"])
    with pytest.raises(PermissionError, match="socket permission denied"):
        world.start()


def test_launcher_scopes_parent_account_helpers(world, monkeypatch):
    import os
    monkeypatch.setenv("PYGSERVER_ACCOUNTS_DIR", "/tmp/previous-store")
    monkeypatch.delenv("GSERVER_ACCOUNTS_DIR", raising=False)
    monkeypatch.setattr(world, "_command", lambda: [sys.executable, "-u", "-c",
                        "import time; print('Server listening on'); time.sleep(60)"])
    world.start()
    assert os.environ["PYGSERVER_ACCOUNTS_DIR"] == str(world.server_dir / "accounts")
    assert os.environ["GSERVER_ACCOUNTS_DIR"] == str(world.server_dir / "accounts")
    world.close()
    assert os.environ["PYGSERVER_ACCOUNTS_DIR"] == "/tmp/previous-store"
    assert "GSERVER_ACCOUNTS_DIR" not in os.environ
