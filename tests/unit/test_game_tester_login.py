"""The transactional login helper and its cleanup guarantees.

The bug these pin down: every failure path used to return without closing the
socket, leaving the account logged in server-side for the next run to collide
with (game_tester/login.py's module docstring).
"""

import socket
import time

import pytest

from game_tester.game_bot import GameBot
from game_tester.login import LoginOutcome, login_client, login_session
from game_tester.multi_bot import MultiBotTest


class FakeClient:
    """Minimal stand-in for pyreborn.Client's login surface."""

    def __init__(self, host="h", port=1, version="6.037", *,
                 tcp_ok=True, login_ok=True, reason="", raises=None):
        self.host, self.port, self.version = host, port, version
        self._tcp_ok, self._login_ok = tcp_ok, login_ok
        self._raises = raises
        self.disconnect_reason = reason
        self.tiles = [1] * 4096
        self._current_level_name = "onlinestartlocal.nw"
        self.x = self.y = 30.0
        self.connect_calls = 0
        self.login_calls = 0
        self.disconnect_calls = 0
        self.connected = False

    def connect(self):
        self.connect_calls += 1
        self.connected = self._tcp_ok
        return self._tcp_ok

    def login(self, username, password, timeout=5.0):
        self.login_calls += 1
        if self._raises is not None:
            raise self._raises
        return self._login_ok

    def update(self, timeout=0.01):
        return []

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


def _bot(**kwargs):
    """A GameBot whose (unconnected) real client is swapped for a fake."""
    bot = GameBot("qa_fake_bot", "127.0.0.1", 1)
    bot.client = FakeClient(**kwargs)
    return bot


# --------------------------------------------------------------------------
# login_client / login_session
# --------------------------------------------------------------------------

def test_login_client_reports_connect_failure_without_attempting_login():
    client = FakeClient(tcp_ok=False)
    outcome = login_client(client, "acc", "pw")
    assert (outcome.connected, outcome.accepted, outcome.ok) == (False, False, False)
    assert client.login_calls == 0


def test_login_client_reports_the_servers_rejection_reason():
    client = FakeClient(login_ok=False, reason="server is version 2.22")
    outcome = login_client(client, "acc", "pw")
    assert outcome.connected and not outcome.accepted
    assert outcome.rejection == "server is version 2.22"


def test_login_client_settles_and_reports_the_version():
    outcome = login_client(FakeClient(version="2.22"), "acc", "pw")
    assert outcome.ok and outcome.settled
    assert (outcome.version, outcome.requested_version) == ("2.22", "2.22")


def test_login_client_skips_the_settle_poll_when_asked():
    client = FakeClient()
    client.tiles = []  # would never settle
    assert login_client(client, "acc", "pw", settle=False).settled is False


def test_login_client_never_disconnects_the_caller_s_client():
    client = FakeClient(login_ok=False)
    login_client(client, "acc", "pw")
    assert client.disconnect_calls == 0


def test_login_session_disconnects_after_a_successful_body():
    seen = {}
    with login_session("h", 1, "acc", "pw",
                       client_factory=FakeClient) as outcome:
        seen["client"] = outcome.client
        assert outcome.ok
        assert outcome.client.disconnect_calls == 0
    assert seen["client"].disconnect_calls == 1


def test_login_session_disconnects_when_the_body_raises():
    made = []

    def factory(host, port, version):
        client = FakeClient(host, port, version)
        made.append(client)
        return client

    with pytest.raises(RuntimeError):
        with login_session("h", 1, "acc", "pw", client_factory=factory):
            raise RuntimeError("boom")
    assert made[0].disconnect_calls == 1


def test_login_session_disconnects_a_rejected_login():
    made = []

    def factory(host, port, version):
        made.append(FakeClient(host, port, version, login_ok=False,
                               reason="staff only"))
        return made[-1]

    with login_session("h", 1, "acc", "pw", client_factory=factory) as outcome:
        assert outcome.rejection == "staff only"
    assert made[0].disconnect_calls == 1


def test_login_session_teardown_survives_a_broken_disconnect():
    class Broken(FakeClient):
        def disconnect(self):
            raise OSError("socket already dead")

    with login_session("h", 1, "acc", "pw",
                       client_factory=Broken) as outcome:
        assert outcome.ok


def test_login_outcome_ok_requires_both_steps():
    assert not LoginOutcome(client=None, connected=True).ok
    assert not LoginOutcome(client=None, accepted=True).ok
    assert LoginOutcome(client=None, connected=True, accepted=True).ok


# --------------------------------------------------------------------------
# GameBot.connect cleanup
# --------------------------------------------------------------------------

def test_bot_connect_closes_the_connection_when_login_is_refused():
    bot = _bot(login_ok=False)
    assert bot.connect(timeout=0.1) is False
    assert bot.client.disconnect_calls == 1
    assert bot.connected is False


def test_bot_connect_closes_the_connection_when_the_client_raises():
    bot = _bot(raises=OSError("connection reset"))
    assert bot.connect(timeout=0.1) is False
    assert bot.client.disconnect_calls == 1
    assert any("Connection error" in issue.description
               for issue in bot.get_issues())


def test_bot_connect_surfaces_the_rejection_reason_as_an_issue():
    bot = _bot(login_ok=False, reason="account is banned")
    bot.connect(timeout=0.1)
    assert [i.description for i in bot.get_issues()] == [
        "Login failed for qa_fake_bot: account is banned"]


def test_bot_connect_keeps_the_connection_on_success():
    bot = _bot()
    assert bot.connect(timeout=0.1) is True
    assert bot.client.disconnect_calls == 0
    assert bot._connected is True


def test_bot_connect_closes_the_real_socket_on_a_refused_login():
    """End-to-end socket proof: connect to a listener that never answers the
    login, then confirm the peer saw the client hang up rather than the
    connection being left open (the leak this fixes)."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        bot = GameBot("qa_socket_probe", *listener.getsockname())
        assert bot.connect(timeout=0.3) is False
        conn, _ = listener.accept()
        try:
            conn.settimeout(2.0)
            deadline = time.time() + 2.0
            saw_eof = False
            while time.time() < deadline:
                if conn.recv(4096) == b"":
                    saw_eof = True
                    break
            assert saw_eof, "client left the socket open after a failed login"
        finally:
            conn.close()
        assert bot.client.connected is False
        assert bot.client._protocol.socket is None
    finally:
        listener.close()


# --------------------------------------------------------------------------
# MultiBotTest.connect_all rollback
# --------------------------------------------------------------------------

def test_connect_all_rolls_back_the_bots_that_did_get_in():
    test = MultiBotTest(2, "127.0.0.1", 1)
    test.bots[0].client = FakeClient()
    test.bots[1].client = FakeClient(login_ok=False)

    assert test.connect_all(timeout=0.1) is False
    assert test.bots[0].client.disconnect_calls >= 1
    assert all(not bot.connected for bot in test.bots)


def test_connect_all_leaves_a_fully_connected_set_alone():
    test = MultiBotTest(2, "127.0.0.1", 1)
    for bot in test.bots:
        bot.client = FakeClient()

    assert test.connect_all(timeout=0.1) is True
    assert all(bot.client.disconnect_calls == 0 for bot in test.bots)
