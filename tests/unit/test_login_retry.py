"""The interactive login window stays up until a login works.

Each failed listserver or direct login reopens it with the reason and the
typed fields; only cancelling quits. Command-line credentials still exit."""
from types import SimpleNamespace

import pytest

from pyreborn import example_pygame


class _Prefs(SimpleNamespace):
    def remember_login(self, *a, **k):
        pass

    def save(self):
        pass


def _prefs():
    return _Prefs(listserver_host="ls.test", listserver_port=14922,
                  host="localhost", port=14900, content_dirs=[],
                  window_w=800, window_h=600, last_server=None)


FIELDS = {"username": "u", "password": "bad", "use_listserver": True,
          "host": "localhost", "port": 14900, "listserver_host": "ls.test"}


@pytest.fixture
def harness(monkeypatch):
    shown = []      # (error, fields) per login window
    results = []    # what each window returns

    class FakeLogin:
        def __init__(self, prefs=None, error="", fields=None):
            shown.append((error, fields))

        def run(self):
            return results.pop(0)

    monkeypatch.setattr(example_pygame, "LoginScreen", FakeLogin)
    monkeypatch.setattr(example_pygame, "show_loading_screen", lambda *a, **k: None)
    monkeypatch.setattr(example_pygame.pygame, "quit", lambda: None)
    monkeypatch.setattr(example_pygame.Prefs, "load", staticmethod(_prefs))
    monkeypatch.setattr(example_pygame.sys, "argv", ["pyreborn"])
    return shown, results


def test_listserver_failure_reopens_login_with_error(harness, monkeypatch):
    shown, results = harness
    good = dict(FIELDS, password="good")
    results += [FIELDS, good, None]   # bad, good, then cancel at retry point
    logins = []

    class FakeLS:
        def __init__(self, host, port):
            pass

        def login(self, user, password):
            logins.append(password)
            if password == "bad":
                return SimpleNamespace(success=False, error="Account name or password is invalid")
            return SimpleNamespace(success=True, status="ok", servers=[])

    monkeypatch.setattr(example_pygame, "ListServerClient", FakeLS)
    with pytest.raises(SystemExit) as exc:
        example_pygame.main()
    assert exc.value.code == 0                     # cancelled, not a failure exit
    assert logins == ["bad", "good"]
    assert shown[0] == ("", None)
    assert shown[1][0] == "Account name or password is invalid"
    assert shown[1][1] is FIELDS                   # typed fields kept
    assert shown[2][0] == "No servers available!"  # empty list also reopens


def test_direct_login_failure_reopens_login(harness, monkeypatch):
    shown, results = harness
    direct = dict(FIELDS, use_listserver=False)
    results += [direct, None]

    class FakeClient:
        disconnect_reason = "Invalid password"

        def __init__(self, *a, **k):
            pass

        def connect(self):
            return True

        def login(self, *a, **k):
            return False

        def disconnect(self):
            pass

    monkeypatch.setattr(example_pygame, "Client", FakeClient)
    with pytest.raises(SystemExit) as exc:
        example_pygame.main()
    assert exc.value.code == 0
    assert shown[1][0] == "Invalid password"


def test_command_line_credentials_still_fail_fast(harness, monkeypatch):
    shown, _ = harness
    monkeypatch.setattr(example_pygame.sys, "argv", ["pyreborn", "u", "bad", "--listserver"])

    class FakeLS:
        def __init__(self, *a):
            pass

        def login(self, *a):
            return SimpleNamespace(success=False, error="nope")

    monkeypatch.setattr(example_pygame, "ListServerClient", FakeLS)
    with pytest.raises(SystemExit) as exc:
        example_pygame.main()
    assert exc.value.code == 1
    assert shown == []
