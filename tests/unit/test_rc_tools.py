"""game/rc_ui.py (the F10 RC tools overlay) + rc_link.py's threading contract.

Both are testable headlessly: RCOverlay drives a fake link and a fake game
stub, and RCLink's queue/state/download paths need no socket.

The invariants worth pinning are the ones a mis-edit would make DANGEROUS
rather than merely broken:
  * a destructive action (kick/ban/delete/flag write) never fires until the
    confirm step is answered Y;
  * a single-flag edit sends back every OTHER flag too, because
    PLI_RC_SERVERFLAGSSET replaces the whole set server-side;
  * commands are refused while the link is not READY, so a queued kick cannot
    fire later against a session that was denied;
  * a download named "../../x" cannot escape the download directory.

SDL_VIDEODRIVER/SDL_AUDIODRIVER are forced to "dummy" (matches the rest of
tests/unit/) so this runs headless.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame
import pygame.locals as pgl
import pytest

from pyreborn import nc_link, rc_link
from pyreborn.game.rc_ui import TABS, RCOverlay
from pyreborn.packets import PacketID
from pyreborn.rc_client import RCClient
from pyreborn.rc_link import DENIED, READY, RCLink, RCSnapshot


class _Key:
    """Minimal stand-in for a pygame KEYDOWN event."""

    def __init__(self, key, unicode="", mod=0):
        self.key = key
        self.unicode = unicode
        self.mod = mod


def _fake_game():
    client = SimpleNamespace(host="localhost", port=14900, version="6.037",
                             level="onlinestartlocal.nw", x=30.0, y=31.0,
                             player=SimpleNamespace(account="hosler"))
    return SimpleNamespace(client=client, rc_password="pw",
                           screen_w=800, screen_h=600)


def _overlay(snapshot: RCSnapshot):
    """An open overlay whose link is a mock already in the given state."""
    overlay = RCOverlay(_fake_game())
    link = Mock(spec=RCLink)
    link.snapshot = snapshot
    link.available = snapshot.state == READY
    link.started = True
    overlay.link = link
    overlay.visible = True
    return overlay, link


def _ready(**fields) -> RCSnapshot:
    return RCSnapshot(state=READY, status="RC session active", **fields)


def _type(overlay, text, submit=True):
    for ch in text:
        overlay.handle_key(_Key(ord(ch), ch))
    if submit:
        overlay.handle_key(_Key(pgl.K_RETURN, "\r"))


# -- rows / tabs -------------------------------------------------------------

def test_tabs_cycle_and_rows_follow_the_open_tab():
    players = ({'id': 7, 'account': 'someone'},)
    overlay, _ = _overlay(_ready(messages=("hi",), players=players,
                                 accounts=("a", "b")))
    assert TABS[overlay.tab] == "Chat"
    assert overlay.rows() == ["hi"]

    overlay.handle_key(_Key(pgl.K_TAB))
    assert TABS[overlay.tab] == "Players"
    assert "someone" in overlay.rows()[0]

    overlay.handle_key(_Key(pgl.K_TAB, mod=pgl.KMOD_SHIFT))
    assert TABS[overlay.tab] == "Chat"


def test_directory_rows_navigate_and_file_rows_transfer():
    """Directories are listing entries whose name ends in "/" (the reference
    layout has no is-directory field), so the two must not be confused: Enter
    on a directory changes into it, and a transfer must never target one."""
    snap = _ready(folders=("rw *",),
                  files=({'name': 'bodies/', 'size': 0, 'rights': 'r'},
                         {'name': 'a.png', 'size': 12, 'rights': 'rw'}))
    overlay, link = _overlay(snap)
    overlay.tab = TABS.index("Files")

    assert overlay.rows() == ["[bodies]", "a.png  12 bytes  rw"]

    overlay.handle_key(_Key(pgl.K_RETURN, "\r"))
    link.files_cd.assert_called_once_with("bodies")

    overlay.handle_key(_Key(ord('d'), 'd'))
    link.files_download.assert_not_called()      # row 0 is a directory

    overlay.selected[overlay.tab] = 1
    overlay.handle_key(_Key(ord('d'), 'd'))
    link.files_download.assert_called_once_with("a.png")


def test_folder_rights_become_the_rows_until_a_directory_is_opened():
    """The reference server sends rights, not a listing, on browser start.

    It then accepts a CD only for a name matching one of those rights, with
    the trailing slash, so the rows have to be derived from them - otherwise
    the browser has nothing to click and cannot be entered at all.
    """
    from pyreborn.game.rc_ui import folder_targets

    overlay, link = _overlay(_ready(folders=("rw world/*", "rw levels/*")))
    overlay.tab = TABS.index("Files")
    assert overlay.rows() == ["[world/]", "[levels/]"]
    assert "rw world/*" in overlay._context_line()

    overlay.handle_key(_Key(pgl.K_RETURN, "\r"))
    link.files_cd.assert_called_once_with("world/")

    assert folder_targets(("rw world/*", "r main/sub/*", "rw flat")) == [
        "world/", "main/sub/", "flat"]


def test_a_whole_tree_right_opens_the_root_not_a_folder_named_star():
    """`rw *` grants everything, and no directory is called "*".

    pygserver hands out exactly that entry for an account with no folder
    list, so treating it as a name made its browser open onto an empty
    listing. The CD for the root is the empty string.
    """
    from pyreborn.game.rc_ui import folder_targets

    assert folder_targets(("rw *",)) == [""]

    overlay, link = _overlay(_ready(folders=("rw *",)))
    overlay.tab = TABS.index("Files")
    assert overlay.rows() == ["[/]"]

    overlay.handle_key(_Key(pgl.K_RETURN, "\r"))
    link.files_cd.assert_called_once_with("")


def test_a_real_listing_replaces_the_rights_rows():
    overlay, _ = _overlay(_ready(folders=("rw world/*",), folder="world/",
                                 files=({'name': 'a.nw', 'size': 3},)))
    overlay.tab = TABS.index("Files")
    assert overlay.rows() == ["a.nw  3 bytes  "]


# -- destructive actions are gated ------------------------------------------

def test_kick_requires_confirmation():
    overlay, link = _overlay(_ready(players=({'id': 7, 'account': 'someone'},)))
    overlay.tab = TABS.index("Players")

    overlay.handle_key(_Key(ord('k'), 'k'))
    link.kick.assert_not_called()
    assert overlay.confirm is not None

    overlay.handle_key(_Key(ord('n'), 'n'))          # declined
    link.kick.assert_not_called()
    assert overlay.confirm is None

    overlay.handle_key(_Key(ord('k'), 'k'))
    overlay.handle_key(_Key(ord('y'), 'y'))          # confirmed
    link.kick.assert_called_once_with(7)


def test_ban_asks_for_a_reason_then_confirms():
    overlay, link = _overlay(_ready(players=({'id': 7, 'account': 'someone'},)))
    overlay.tab = TABS.index("Players")

    overlay.handle_key(_Key(ord('b'), 'b'))
    _type(overlay, "spamming")
    link.ban.assert_not_called()                     # reason alone is not enough

    overlay.handle_key(_Key(ord('y'), 'y'))
    link.ban.assert_called_once_with("someone", True, "spamming")


def test_escape_cancels_a_prompt_without_acting():
    overlay, link = _overlay(_ready(players=({'id': 7, 'account': 'someone'},)))
    overlay.tab = TABS.index("Players")
    overlay.handle_key(_Key(ord('c'), 'c'))
    _type(overlay, "note", submit=False)
    overlay.handle_key(_Key(pgl.K_ESCAPE))
    link.set_comments.assert_not_called()
    assert overlay.prompt is None
    assert overlay.visible, "Esc closing the prompt must not also close the panel"


def test_setting_one_server_flag_sends_the_whole_set_back():
    """PLI_RC_SERVERFLAGSSET replaces every flag, so an edit must merge."""
    overlay, link = _overlay(_ready(server_flags=("motd=hello", "pvp=1")))
    overlay.tab = TABS.index("Server")

    overlay.handle_key(_Key(ord('f'), 'f'))
    _type(overlay, "pvp=0")
    overlay.handle_key(_Key(ord('y'), 'y'))

    link.set_flags.assert_called_once_with({"motd": "hello", "pvp": "0"})


# -- input containment -------------------------------------------------------

def test_typed_letters_go_to_the_prompt_not_to_tab_actions():
    overlay, link = _overlay(_ready(players=({'id': 7, 'account': 'someone'},)))
    overlay.tab = TABS.index("Players")
    overlay.handle_key(_Key(ord('c'), 'c'))          # opens the comment prompt
    _type(overlay, "kick", submit=False)             # contains 'k'
    link.kick.assert_not_called()
    assert overlay.prompt.text == "kick"


def test_actions_are_ignored_without_a_live_session():
    overlay, link = _overlay(RCSnapshot(state="denied", status="no RC access"))
    overlay.tab = TABS.index("Players")
    overlay.handle_key(_Key(ord('k'), 'k'))
    link.kick.assert_not_called()
    assert overlay.confirm is None


def test_f10_closes_the_panel():
    overlay, _ = _overlay(_ready())
    overlay.handle_key(_Key(pgl.K_F10))
    assert not overlay.visible


def test_reopening_retries_a_dropped_session_but_not_a_refused_one():
    overlay, link = _overlay(RCSnapshot(state="closed", status="dropped"))
    overlay.link.state = "closed"
    overlay.close()
    overlay.toggle()
    link.start.assert_called_once()

    link.start.reset_mock()
    overlay.link.state = "denied"
    overlay.close()
    overlay.toggle()
    link.start.assert_not_called()


# -- rendering ---------------------------------------------------------------

def test_panel_draws_in_every_tab():
    pygame.init()
    pygame.display.set_mode((320, 240))
    surface = pygame.Surface((800, 600))
    overlay, _ = _overlay(_ready(messages=("hi",), players=({'id': 1, 'account': 'a'},),
                                 accounts=("a",), server_flags=("pvp=1",),
                                 files=({'name': 'x.png', 'size': 1},)))
    overlay.game.font = pygame.font.Font(None, 18)
    overlay.game.font_small = pygame.font.Font(None, 14)
    from pyreborn.game.assets import FontManager
    overlay.game.fonts = FontManager()
    for index in range(len(TABS)):
        overlay.tab = index
        overlay.draw(surface)          # must not raise on any tab
    overlay.prompt = None
    pygame.quit()


def test_panel_rect_stays_drawable_on_a_tiny_window():
    overlay, _ = _overlay(_ready())
    overlay.game.screen_w = 10
    overlay.game.screen_h = 10
    assert overlay._panel_rect().size == (320, 240)


# -- RCLink ------------------------------------------------------------------

def test_commands_are_refused_until_the_session_is_ready():
    link = RCLink("localhost", 14900, "hosler", "pw")
    assert link.say("hello") is False
    assert link._commands.empty(), "a refused command must not queue for later"


def test_start_without_a_password_is_denied_not_attempted():
    link = RCLink("localhost", 14900, "hosler", "")
    link.start()
    assert link.state == "denied"
    assert link.started is False


def test_start_does_not_retry_a_denied_session():
    link = RCLink("localhost", 14900, "hosler", "pw")
    link._set_state(DENIED, "no RC access")
    with patch("pyreborn.rc_link.threading.Thread") as thread:
        link.start()
    thread.assert_not_called()


def test_download_names_cannot_escape_the_download_directory(tmp_path):
    link = RCLink("localhost", 14900, "hosler", "pw", download_dir=tmp_path)
    link._on_file("../../escaped.txt", b"data")

    assert (tmp_path / "escaped.txt").read_bytes() == b"data"
    assert not (tmp_path.parent.parent / "escaped.txt").exists()
    assert any("escaped.txt" in note for note in link.snapshot.notices)


def test_snapshot_is_a_copy_not_a_live_view(tmp_path):
    link = RCLink("localhost", 14900, "hosler", "pw", download_dir=tmp_path)
    before = link.snapshot
    link._note("something happened")
    assert before.notices == ()
    assert link.snapshot.notices == ("something happened",)


def test_rc_download_dir_is_not_the_asset_cache(monkeypatch):
    monkeypatch.delenv("PYREBORN_RC_DOWNLOAD_DIR", raising=False)
    path = rc_link.rc_download_dir("example.com", 14900)
    assert path.name == "example.com_14900"
    assert "rc_downloads" in str(path)


def test_rc_file_transfer_never_persists_in_the_asset_cache(tmp_path,
                                                            monkeypatch):
    monkeypatch.setenv("PYREBORN_CACHE_DIR", str(tmp_path))
    client = RCClient("example.com", 14900, "6.037")
    client._store_cached_file("pics1.png", b"old backup", 123)
    assert list(tmp_path.rglob("*")) == []


def test_admin_message_is_not_rc_access_proof():
    client = rc_link._LinkedRCClient("localhost", 14900, "6.037")
    with patch.object(RCClient, "_handle_packet"):
        client._handle_packet(PacketID.PLO_RC_ADMINMESSAGE, b"")
    assert client.saw_rc_packet is False


def test_restart_discards_commands_from_the_dead_session():
    link = RCLink("localhost", 14900, "hosler", "pw")
    link._set_state(READY, "active")
    assert link.kick(7) is True
    link._set_state("closed", "dropped")
    with patch("pyreborn.rc_link.threading.Thread") as thread:
        link.start()
    assert link._commands.empty()
    thread.return_value.start.assert_called_once()


def test_close_keeps_a_blocked_worker_stopped_and_tracked():
    link = RCLink("localhost", 14900, "hosler", "pw")
    worker = Mock()
    worker.is_alive.return_value = True
    link._thread = worker
    old_stop = link._stop
    link.close(timeout=0)
    assert old_stop.is_set()
    assert link._thread is worker
    link.start()
    assert link._stop is old_stop


def test_stop_during_access_proof_closes_without_a_denial():
    link = RCLink("localhost", 14900, "hosler", "pw")
    link._set_state("connecting", "proving access")
    stop_event = rc_link.threading.Event()
    client = Mock()
    client.connect.return_value = True
    client.login.return_value = True

    def stop_proof(_client, _stop_event):
        stop_event.set()
        return False

    with patch("pyreborn.rc_link._LinkedRCClient", return_value=client), \
            patch.object(link, "_await_rc_proof", side_effect=stop_proof):
        link._run(stop_event)
    assert link.state == "closed"


def test_rc_disconnect_during_access_proof_is_retryable():
    link = RCLink("localhost", 14900, "hosler", "pw")
    client = Mock()
    client.connect.return_value = True
    client.login.return_value = True
    with patch("pyreborn.rc_link._LinkedRCClient", return_value=client), \
            patch.object(link, "_await_rc_proof", return_value=None):
        link._run(rc_link.threading.Event())
    assert link.state == "closed"
    assert link.snapshot.status == "RC connection dropped"


def test_nc_disconnect_during_access_proof_is_retryable():
    link = nc_link.NCLink("localhost", 14900, "hosler", "pw")
    client = Mock()
    client.connect.return_value = True
    client.login.return_value = True
    with patch("pyreborn.nc_link._LinkedNCClient", return_value=client), \
            patch.object(link, "_await_nc_proof", return_value=None):
        link._run(nc_link.threading.Event())
    assert link.state == "closed"
    assert link.snapshot.status == "NC connection dropped"


# -- the panel must not leave the player walking ------------------------------

def test_an_open_panel_stops_held_key_movement():
    """The panels are modal for EVENTS, and movement does not run off events.

    `_handle_input` polls `key.get_pressed()` every frame, so the arrow keys
    that scroll a row are physically held and the player walked off underneath
    the open panel.
    """
    from pyreborn.game.input import InputMixin

    class _Harness(InputMixin):
        def __init__(self):
            self.rc_ui = SimpleNamespace(visible=False)
            self.dev_ui = SimpleNamespace(visible=False)

    harness = _Harness()
    assert harness._admin_overlay_captures_keys() is False

    harness.rc_ui.visible = True
    assert harness._admin_overlay_captures_keys() is True

    harness.rc_ui.visible = False
    harness.dev_ui.visible = True
    assert harness._admin_overlay_captures_keys() is True


def test_edit_mode_is_left_walkable_on_purpose():
    """F11 is non-modal by design: a builder walks while painting."""
    from pyreborn.game.input import InputMixin

    class _Harness(InputMixin):
        def __init__(self):
            self.rc_ui = SimpleNamespace(visible=False)
            self.dev_ui = SimpleNamespace(visible=False)
            self.level_editor = SimpleNamespace(state=SimpleNamespace(
                enabled=True))

    assert _Harness()._admin_overlay_captures_keys() is False
