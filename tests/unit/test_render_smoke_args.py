"""render_smoke must never reach a socket on --help, a bad flag, or a missing
port: it paints over the wire, and used to run against the shared server."""
import socket

import pytest

from game_tester import render_smoke


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("render_smoke opened a socket")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.delenv("PYREBORN_TEST_PORT", raising=False)


def test_help_prints_usage_and_exits(capsys):
    with pytest.raises(SystemExit) as exit_info:
        render_smoke.main(["--help"])
    assert exit_info.value.code == 0
    assert "--port" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--bogus"], ["--port", "x"], ["stray"], []])
def test_bad_or_missing_arguments_exit_nonzero(argv):
    with pytest.raises(SystemExit) as exit_info:
        render_smoke.main(argv)
    assert exit_info.value.code == 2


def test_the_shared_port_needs_shared_flag(monkeypatch):
    with pytest.raises(SystemExit):
        render_smoke.main(["--port", "14900"])
    monkeypatch.setenv("PYREBORN_TEST_PORT", "14900")
    with pytest.raises(SystemExit):
        render_smoke.main([])
    assert render_smoke.parse_args(["--shared"]).port == 14900
    with pytest.raises(SystemExit):
        render_smoke.parse_args(["--shared", "--port", "14931"])


def test_explicit_port_or_qa_server_env_is_accepted(monkeypatch):
    assert render_smoke.parse_args(["--port", "14932"]).port == 14932
    monkeypatch.setenv("PYREBORN_TEST_PORT", "14933")
    assert render_smoke.parse_args([]).port == 14933
