"""PlayerList / F2Log / serverlist-chat host surface (2026-07-28 wave).

Covers the engine surface that makes the official Login window weapons
functional, per the two audited specs (scratchpad/gs2-native-windows-spec.md,
scratchpad/gs2-login-irc-spec.md):

- prop-81 PLAYERLISTCATEGORY / prop-82 COMMUNITYNAME / prop-51 DISCONNECT /
  prop-53 PLAYERLISTSTATUS decode in the other-player stream.
- the session-global `all_players` roster + universe events
  (onPlayerLogin/onPlayerLogout/onPlayerChanges/onPM).
- the persistent per-id player wrapper surface (flag booleans, staff-guild
  isadmin, pmswaiting/ismasspm/isguildpm, showprofile,
  openexternalpm/openexternalhistory falsy stubs, sticky writable members).
- the `scriptedplayerlist`/`allplayers` script globals.
- GuiTextListCtrl's engine sort model (sortgroup band -> sortvalue/lexical,
  both enum vocabularies) and active/flickering row semantics.
- universe onControlKeyDown/onKeyPressed from the GUI key path (F2/F7 arms
  live, Esc arms dead because window is always "").
- onLogMessage feed (echo -> log line. Reentrancy guard).
- the GuiPMCtrl/GuiPMEditCtrl/GuiPMHistoryCtrl native panes.
- the real -Playerlist/-F2LogWindow bytecode as runnable fixtures
  (skipped when the third-party corpus checkout is absent).
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn.gs2_client import ClientGS2, _is_admin_guild
from pyreborn.handlers.entities import (
    handle_del_player,
    handle_other_player_props,
)
from pyreborn.packets import parse_other_player
from reborn_protocol.gs2 import GS2_NULL, GS2Object

pygame.init()
pygame.font.init()

#: third-party corpus (reference-only checkout; never edited) -- the two
#: official Login weapons, recovered as raw bytecode
_CORPUS = Path(__file__).resolve().parents[3] / \
    "Preagonal" / "gbf" / "bytecode" / "login"
_needs_corpus = pytest.mark.skipif(
    not (_CORPUS / "_Playerlist.gs2bc").is_file(),
    reason="Preagonal login bytecode corpus not checked out")


class _FakeVM:
    def __init__(self, fns=()):
        self.fns = {name.lower() for name in fns}
        self.calls = []
        self.name = "weapon:fake"

    def has_function(self, name):
        return name.lower() in self.fns

    def iter_call(self, name, *args):
        self.calls.append((name, args))
        return iter(())


def _client(**over):
    base = dict(
        player=SimpleNamespace(id=1, x=0, y=0, account="me", nickname="Me"),
        # staff_guilds None = PLO_STAFFGUILDS never sent (client_state's
        # default) -> the built-in staff-guild defaults apply
        players={}, all_players={}, staff_guilds=None, server_name="login",
        connected=False, weapons={}, _colors_len=5,
        prop_parse_diagnostics=None, _current_level_name="",
        gmap_width=0, gmap_grid={}, on_player_left=None, on_chat=None,
        on_del_player=None, player_list={},
    )
    base.update(over)
    return SimpleNamespace(**base)


def _gshort(v):
    return bytes([((v >> 7) & 0x7F) + 32, (v & 0x7F) + 32])


def _sstr(prop_id, text):
    raw = text.encode("latin-1")
    return bytes([prop_id + 32, len(raw) + 32]) + raw


# =============================================================================
# 1. Wire decode
# =============================================================================

class TestPropDecode:
    def test_prop81_flags_and_prop82_communityname(self):
        data = (_gshort(16000)
                + _sstr(0, "#reborn (1,0)")
                + _sstr(34, "irc:#reborn")
                + bytes([81 + 32, 3 + 32])
                + _sstr(82, "Reborn"))
        props = parse_other_player(data)
        assert props["id"] == 16000
        assert props["playerlist_flags"] == 3
        assert props["communityname"] == "Reborn"
        assert props["account"] == "irc:#reborn"

    def test_pseudo_player_nonascending_prop_order_parses_fully(self):
        # GServer-v2 and the live Login servers hand-build the external/
        # pseudo-player packet as ACCOUNTNAME(34), NICKNAME(0),
        # PLAYERLISTCATEGORY(81) -- non-ascending (PlayerRequestText.cpp:170,
        # PlayerExternalPlayers.cpp:182-184; live capture 2026-07-28). The
        # strict ascending stop used to drop the nick AND the flags, so the
        # channel row listed as a plain player.
        data = (_gshort(16000)
                + _sstr(34, "irc:#reborn")
                + _sstr(0, "#reborn (1,0)")
                + bytes([81 + 32, 3 + 32]))
        props = parse_other_player(data)
        assert props["account"] == "irc:#reborn"
        assert props["nickname"] == "#reborn (1,0)"
        assert props["playerlist_flags"] == 3

    def test_prop53_status_is_numeric_gbyte(self):
        # GServer-v2/pygserver emit prop 53 as a GBYTE1 status index
        # (PlayerProps.cpp:904); the v6 mobile client's string read of the
        # same id has no emitting server in any oracle, so the validated
        # width is pinned here.
        data = _gshort(5) + bytes([53 + 32, 2 + 32])
        props = parse_other_player(data)
        assert props["playerlist_status"] == 2

    def test_prop51_disconnect_marker_reaches_handler(self):
        # Wire.VOID decodes to None: without the handle_empty exemption the
        # logout notification silently vanished.
        data = _gshort(5) + bytes([51 + 32])
        props = parse_other_player(data)
        assert props.get("disconnect") is True


# =============================================================================
# 2. Global roster + universe events (packet-handler level)
# =============================================================================

class _HostRecorder:
    def __init__(self):
        self.events = []

    def roster_player_added(self, pid):
        self.events.append(("login", pid))

    def roster_player_changed(self, pid):
        self.events.append(("changes", pid))

    def roster_player_removed(self, pid, record):
        self.events.append(("logout", pid, dict(record or {})))

    def pm_received(self, pid, mtype, message):
        self.events.append(("pm", pid, mtype, message))


class TestRosterEvents:
    def test_login_update_logout_cycle(self):
        client = _client()
        client.gs2_host = host = _HostRecorder()
        # first sighting -> onPlayerLogin
        handle_other_player_props(client, _gshort(7) + _sstr(0, "Bob"))
        assert ("login", 7) in host.events
        assert 7 in client.all_players and 7 in client.players
        # roster-relevant prop update -> onPlayerChanges (nickname is one of
        # the reference's playerListChanged props)
        handle_other_player_props(client, _gshort(7) + _sstr(0, "Bobby"))
        assert ("changes", 7) in host.events
        assert client.all_players[7]["nickname"] == "Bobby"
        # level leave: gone from the LEVEL roster, still in allplayers
        handle_other_player_props(client, _gshort(7) + bytes([50 + 32, 32]))
        assert 7 not in client.players and 7 in client.all_players
        assert not any(e[0] == "logout" for e in host.events)
        # DISCONNECT -> onPlayerLogout, removed everywhere
        handle_other_player_props(client, _gshort(7) + bytes([51 + 32]))
        assert 7 not in client.all_players
        assert any(e[0] == "logout" and e[1] == 7 for e in host.events)

    def test_external_pseudo_players_stay_out_of_level_roster(self):
        client = _client()
        client.gs2_host = _HostRecorder()
        data = (_gshort(16000) + _sstr(0, "#reborn (1,0)")
                + _sstr(34, "irc:#reborn") + bytes([81 + 32, 3 + 32]))
        handle_other_player_props(client, data)
        assert 16000 in client.all_players
        assert 16000 not in client.players

    def test_delplayer_fires_logout_for_known_roster_id(self):
        client = _client()
        client.gs2_host = host = _HostRecorder()
        handle_other_player_props(client, _gshort(9) + _sstr(0, "Eve"))
        handle_del_player(client, _gshort(9))
        assert any(e[0] == "logout" and e[1] == 9 for e in host.events)
        assert 9 not in client.all_players

    def test_non_roster_prop_update_fires_no_changes_event(self):
        client = _client()
        client.gs2_host = host = _HostRecorder()
        handle_other_player_props(client, _gshort(7) + _sstr(0, "Bob"))
        host.events.clear()
        # a plain position update is not a playerListChanged prop
        handle_other_player_props(
            client, _gshort(7) + bytes([15 + 32, 20 + 32, 16 + 32, 20 + 32]))
        assert host.events == []


# =============================================================================
# 3. Wrapper surface
# =============================================================================

class TestWrapperSurface:
    def test_flag_booleans_and_channel_identity(self):
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[16000] = {"account": "irc:#reborn",
                                     "nickname": "#reborn (1,0)",
                                     "playerlist_flags": 11}
        item = rt2.roster_wrapper(16000)
        assert item.get("isexternal") == 1.0
        assert item.get("ischannel") == 1.0
        assert item.get("ischanneluser") == 0.0
        assert item.get("ischannelopen") == 1.0
        # identity is stable across reads
        assert rt2.roster_wrapper(16000) is item
        assert rt2.player_by_id(16000) is item
        assert rt2.all_player_objects() == [item]

    def test_isadmin_staff_guild_rule_and_external_override(self):
        assert _is_admin_guild("RC", None)
        assert _is_admin_guild("Coder", None)
        assert not _is_admin_guild("CoderX", None)   # "Coder)" pins exact
        assert _is_admin_guild("RCA", None)          # bare "RC" is a prefix
        assert not _is_admin_guild("Players", None)
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Bob (RC)"}
        assert rt2.roster_wrapper(5).get("isadmin") == 1.0
        # external forces isadmin false even with a staff guild
        client.all_players[5]["playerlist_flags"] = 1
        assert rt2.roster_wrapper(5).get("isadmin") == 0.0

    def test_isadmin_server_sent_empty_list_disables_defaults(self):
        # A server-SENT staff-guild list is authoritative even when EMPTY:
        # isadminguild answers false for every guild then (TPlayerList.cpp:
        # 11-12); only a NEVER-SENT list (None) uses the baked defaults.
        assert not _is_admin_guild("RC", [])
        assert not _is_admin_guild("Coder", [])
        # a sent list replaces the defaults entirely
        assert _is_admin_guild("MyStaff", ["MyStaff)"])
        assert not _is_admin_guild("RC", ["MyStaff)"])
        # blank entries never prefix-match everything
        assert not _is_admin_guild("Anyone", [""])

    def test_pm_methods_and_falsy_stubs(self):
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Bob"}
        item = rt2.roster_wrapper(5)
        assert item.get("pmswaiting")() is False
        assert item.get("openexternalpm")() is False
        assert item.get("openexternalhistory")() is False
        item.set("message", "Mass message:\nhi all")
        assert item.get("pmswaiting")() is True
        assert item.get("ismasspm")() is True
        assert item.get("isguildpm")() is False

    def test_sticky_members_survive_refresh(self):
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Bob"}
        item = rt2.roster_wrapper(5)
        item.set("isbuddy", 1.0)
        item.set("message", "Private message:\nhello")
        # a refresh from a NEW record dict must not clobber script/PM state
        client.all_players[5] = {"nickname": "Bobby"}
        again = rt2.roster_wrapper(5)
        assert again is item
        assert again.get("nick") == "Bobby"
        assert again.get("isbuddy") == 1.0
        assert again.get("message") == "Private message:\nhello"

    def test_id_reuse_by_different_account_resets_sticky_state(self):
        # Both servers hand a freed id to the next login immediately; the
        # wrapper cache outlives a logout on purpose (waiting-PM survival),
        # so a new ACCOUNT on a cached id must not inherit the prior
        # occupant's PM badge/history/buddy flag.
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Alice", "account": "alice"}
        item = rt2.roster_wrapper(5)
        item.set("isbuddy", 1.0)
        rt2.pm_received(5, "Private message:", "for alice")
        assert item.get("pmswaiting")() is True
        assert rt2.pm_history[5] == [("in", "for alice")]
        record = client.all_players.pop(5)
        rt2.roster_player_removed(5, record)          # Alice logs out
        client.all_players[5] = {"nickname": "Bob", "account": "bob"}
        again = rt2.roster_wrapper(5)                 # Bob takes the id
        assert again is item                          # same per-id wrapper
        assert again.get("message") == ""
        assert again.get("pmswaiting")() is False
        assert again.get("isbuddy") == 0.0
        assert 5 not in rt2.pm_history
        assert again.get("nick") == "Bob"
        assert again.get("isloggedin") == 1.0

    def test_id_reuse_same_account_reconnect_preserves_state(self):
        # Same id + same account relogging is a reconnect-in-place: the
        # deletedplayers-analog state (waiting PM, buddy flag, history)
        # must survive.
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Alice", "account": "alice"}
        item = rt2.roster_wrapper(5)
        item.set("isbuddy", 1.0)
        rt2.pm_received(5, "Private message:", "wb")
        record = client.all_players.pop(5)
        rt2.roster_player_removed(5, record)
        client.all_players[5] = {"nickname": "Alice2", "account": "alice"}
        again = rt2.roster_wrapper(5)
        assert again is item
        assert again.get("message") == "Private message:\nwb"
        assert again.get("isbuddy") == 1.0
        assert rt2.pm_history[5] == [("in", "wb")]

    def test_pm_placeholder_wrapper_keeps_message_when_account_arrives(self):
        # A PM can arrive before the sender's props: the placeholder wrapper
        # has no account yet and is NOT logged out, so learning the account
        # is an attribution, not a reuse -- the waiting PM must survive.
        client = _client()
        rt2 = ClientGS2(client)
        rt2.pm_received(9, "Private message:", "early")
        client.all_players[9] = {"nickname": "Carol", "account": "carol"}
        item = rt2.roster_wrapper(9)
        assert item.get("message") == "Private message:\nearly"
        assert rt2.pm_history[9] == [("in", "early")]

    def test_showprofile_fires_open_profile_window(self):
        client = _client()
        rt2 = ClientGS2(client)
        vm = _FakeVM(["onOpenProfileWindow"])
        rt2.vms["weapon"]["-playerlist_profile"] = vm
        client.all_players[5] = {"nickname": "Bob"}
        item = rt2.roster_wrapper(5)
        item.get("showprofile")()
        assert vm.calls and vm.calls[0][0] == "onOpenProfileWindow"
        assert vm.calls[0][1][0] is item

    def test_pm_received_sets_message_before_onpm(self):
        client = _client()
        rt2 = ClientGS2(client)
        seen = []
        vm = _FakeVM(["onPM"])
        vm.iter_call = lambda name, *args: (
            seen.append((name, args[0].get("message"))), iter(()))[1]
        rt2.vms["weapon"]["-playerlist"] = vm
        client.all_players[5] = {"nickname": "Bob"}
        rt2.pm_received(5, "Private message:", "hello")
        assert seen == [("onPM", "Private message:\nhello")]
        assert rt2.pm_history[5] == [("in", "hello")]

    def test_players_array_serves_persistent_wrappers(self):
        client = _client()
        rt2 = ClientGS2(client)
        client.players[5] = {"nickname": "Bob", "account": "bob"}
        client.all_players[5] = client.players[5]
        arr = rt2.player_list_objects()
        assert arr[0] is rt2.player_object
        assert arr[1] is rt2.roster_wrapper(5)


# =============================================================================
# 4. Script globals
# =============================================================================

class TestGlobals:
    def test_scriptedplayerlist_is_truthy(self):
        rt2 = ClientGS2(_client())
        assert rt2.host.get_object("scriptedplayerlist") == 1.0

    def test_allplayers_binding_excludes_local_player(self):
        client = _client()
        rt2 = ClientGS2(client)
        client.all_players[5] = {"nickname": "Bob"}
        aps = rt2.host.get_object("allplayers")
        assert len(aps) == 1
        assert aps[0] is rt2.roster_wrapper(5)


# =============================================================================
# 5. Sort model / row semantics
# =============================================================================

class TestListSortModel:
    def _list(self, rt2):
        return rt2.host.create_object("GuiTextListCtrl", "L")

    def test_desktop_vocabulary_accepted_and_band_sort(self):
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        lst.set("sortorder", "descending")     # desktop spelling
        lst.set("sortmode", "value")
        lst.set("groupsortorder", "ascending")
        assert lst.get("sortorder") == "sortdescending"
        assert lst.get("sortmode") == "sortbyvalue"
        header = lst.get("addrow")(-1, "--- Staff ---")
        header.set("sortgroup", 0.0)
        header.set("sortvalue", 0.0)
        a = lst.get("addrow")(7, "alice")
        a.set("sortgroup", 2.0)
        a.set("sortvalue", 100.0)
        b = lst.get("addrow")(8, "bob")
        b.set("sortgroup", 2.0)
        b.set("sortvalue", 200.0)     # more recent -> first within band
        lst.get("sort")()
        assert [r.get("id") for r in lst.list_rows] == [-1, 8, 7]

    def test_lexical_mode_case_insensitive(self):
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        lst.set("sortorder", "sortascending")  # mobile spelling still works
        for rid, text in ((1, "delta"), (2, "Alpha"), (3, "charlie")):
            lst.get("addrow")(rid, text)
        lst.get("sort")()
        assert [str(r.get("text")) for r in lst.list_rows] == \
            ["Alpha", "charlie", "delta"]

    def test_inactive_row_is_unselectable(self):
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        row = lst.get("addrow")(1, "offline guy")
        row.set("active", 0.0)
        assert lst.select_index(0) is False
        assert lst.selected_index == -1

    def test_unset_active_read_does_not_disable_row(self):
        # A mere READ of row.active (script style, e.g. in a with-block)
        # vivifies an _InertDrawable placeholder per GuiListRow.get()'s
        # with-scope contract; that placeholder is still UNSET -- the row
        # must stay selectable (unset means active), not to_num() to 0.0.
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        row = lst.get("addrow")(1, "guy")
        row.get("active")               # materializes the inert placeholder
        assert lst.select_index(0) is True
        assert lst.selected_index == 0
        # an explicit write afterwards still disables
        row.set("active", 0.0)
        assert lst.select_index(0) is False

    def test_row_icon_records_and_isclear(self):
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        row = lst.get("addrow")(1, "x")
        icon = row.get("icon")
        assert icon.get("isclear") == 1.0
        icon.get("drawimagerectangle")(0, 0, "state.png", 142, 0, 16, 16)
        assert row.icon_image == "state.png"
        assert icon.get("isclear") == 0.0
        icon.get("clearall")()
        assert icon.get("isclear") == 1.0

    def test_rows_member_indexes_row_model(self):
        rt2 = ClientGS2(_client())
        lst = self._list(rt2)
        row = lst.get("addrow")(1, "x")
        assert lst.get("rows")[0] is row


# =============================================================================
# 6. Universe key dispatch
# =============================================================================

class TestUniverseKeys:
    def _rt2_with_catcher(self):
        rt2 = ClientGS2(_client())
        vm = _FakeVM(["onControlKeyDown", "onKeyPressed"])
        rt2.vms["weapon"]["-f2logwindow"] = vm
        return rt2, vm

    def test_unconsumed_key_fires_with_empty_window_arg(self):
        rt2, vm = self._rt2_with_catcher()
        event = pygame.event.Event(
            pygame.KEYDOWN, {"key": pygame.K_F2, "unicode": "", "mod": 0,
                             "scancode": 0})
        rt2.gui.handle_event(event)
        ck = [c for c in vm.calls if c[0] == "onControlKeyDown"]
        assert ck and ck[0][1][0] == 113.0      # VK_F2
        assert ck[0][1][3] == ""                # window: always the main one
        kp = [c for c in vm.calls if c[0] == "onKeyPressed"]
        assert kp and kp[0][1][0] == 113.0

    def test_consumed_key_does_not_fire(self):
        rt2, vm = self._rt2_with_catcher()
        gui = rt2.gui
        edit = rt2.host.create_object("GuiTextEditCtrl", "E")
        edit.x, edit.y, edit.width, edit.height = 0, 0, 100, 20
        rt2.host.call_builtin(None, "addcontrol", [edit])
        gui.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, {"pos": (5, 5), "button": 1}))
        assert gui.keyboard_captured
        gui.handle_event(pygame.event.Event(
            pygame.KEYDOWN, {"key": pygame.K_F2, "unicode": "", "mod": 0,
                             "scancode": 0}))
        assert not any(c[0] == "onControlKeyDown" for c in vm.calls)


# =============================================================================
# 7. onLogMessage feed
# =============================================================================

class TestLogMessageFeed:
    def test_echo_feeds_onlogmessage(self):
        rt2 = ClientGS2(_client())
        vm = _FakeVM(["onLogMessage"])
        rt2.vms["weapon"]["-f2logwindow"] = vm
        rt2.host.call_builtin(None, "echo", ["hi log"])
        assert ("onLogMessage", ("hi log", 0.0, 1.0, 0.0, "echo")) in vm.calls

    def test_reentrancy_guard(self):
        rt2 = ClientGS2(_client())
        vm = _FakeVM(["onLogMessage"])
        depth = []

        def _iter(name, *args):
            depth.append(name)
            # a handler that logs again must not recurse
            rt2.fire_log_message("nested", 1, 1, 1, "game")
            return iter(())
        vm.iter_call = _iter
        rt2.vms["weapon"]["-f2logwindow"] = vm
        rt2.fire_log_message("outer", 1, 1, 1, "game")
        assert depth == ["onLogMessage"]


# =============================================================================
# 8. PM panes
# =============================================================================

class TestPMControls:
    def _rt2(self):
        sent = []
        client = _client()
        client.send_pm = lambda pid, text: sent.append(("pm", pid, text)) or True
        client.send_pm_multi = lambda ids, text: \
            sent.append(("mass", tuple(ids), text)) or True
        rt2 = ClientGS2(client)
        return rt2, client, sent

    def test_showpm_renders_and_consumes(self):
        rt2, client, _ = self._rt2()
        client.all_players[5] = {"nickname": "Bob"}
        person = rt2.roster_wrapper(5)
        person.set("message", "Private message:\nhello")
        pane = rt2.host.create_object("GuiPMCtrl", "P")
        pane.get("showpm")(person)
        assert "hello" in pane.text
        assert person.get("message") == ""
        assert person.get("pmswaiting")() is False

    def test_sendpm_and_history(self):
        rt2, client, sent = self._rt2()
        client.all_players[5] = {"nickname": "Bob"}
        person = rt2.roster_wrapper(5)
        edit = rt2.host.create_object("GuiPMEditCtrl", "E")
        edit.text = "yo"
        edit.get("sendpm")(person)
        assert sent == [("pm", 5, "yo")]
        assert rt2.pm_history[5] == [("out", "yo")]
        assert edit.text == ""
        hist = rt2.host.create_object("GuiPMHistoryCtrl", "H")
        hist.get("showhistory")(person)
        assert "yo" in hist.text

    def test_sendmasspm_null_is_inert(self):
        rt2, client, sent = self._rt2()
        edit = rt2.host.create_object("GuiPMEditCtrl", "E")
        edit.text = "yo"
        edit.get("sendmasspm")(GS2_NULL)
        assert sent == []


# =============================================================================
# 9. Window claim surface
# =============================================================================

class TestWindowClaims:
    def test_desktop_window_props_land_and_externalwindow_is_null(self):
        rt2 = ClientGS2(_client())
        win = rt2.host.create_object("GuiWindowCtrl", "W")
        for name in ("dockable", "istoolwindow", "stayontop", "isexternal",
                     "buttonoffset", "edgesnap", "cancollapse"):
            assert win.has(name), name
            win.set(name, 1.0)
            assert win.get(name) == 1.0, name
        assert win.has("externalwindow")
        assert win.get("externalwindow") is GS2_NULL


# =============================================================================
# 10. The real Login weapons as runnable fixtures
# =============================================================================

@_needs_corpus
class TestOfficialWeapons:
    def _rt2(self):
        client = _client()
        rt2 = ClientGS2(client)
        return rt2, client

    def test_playerlist_builds_and_tracks_roster(self):
        rt2, client = self._rt2()
        # Exercise the weapon's fallback constructor independently of the
        # client-owned F3 window that is normally present before it loads.
        rt2.gui.destroy(rt2.host.get_object("PlayerList_Window"))
        rt2.load_bytecode("weapon", "-Playerlist",
                          (_CORPUS / "_Playerlist.gs2bc").read_bytes())
        gui = rt2.gui
        win = gui._named.get("playerlist_window")
        assert win is not None and win.CTRL_CLASS == "GuiWindowCtrl"
        lst = gui._named.get("playerlist_list")
        headers = [str(r.get("text")) for r in lst.list_rows]
        assert "--- Staff ---" in headers and "--- Players ---" in headers
        # roster events drive rows
        client.all_players[7] = {"account": "bob", "nickname": "Bob",
                                 "playerlist_flags": 0}
        rt2.roster_player_added(7)
        assert any(r.get("id") == 7 for r in lst.list_rows)
        # waiting PM promotes + flickers the row
        rt2.pm_received(7, "Private message:", "hi")
        row = next(r for r in lst.list_rows if r.get("id") == 7)
        assert row._members.get("flickering")
        # logout removes the row
        record = client.all_players.pop(7)
        rt2.roster_player_removed(7, record)
        assert not any(r.get("id") == 7 for r in lst.list_rows)

    def test_playerlist_f7_toggles_and_esc_stays_dead(self):
        rt2, _client_ = self._rt2()
        rt2.load_bytecode("weapon", "-Playerlist",
                          (_CORPUS / "_Playerlist.gs2bc").read_bytes())
        win = rt2.gui._named.get("playerlist_window")
        assert win.visible is False
        rt2.trigger_event("onControlKeyDown", 118.0, "", 0.0, "")
        assert win.visible is True
        # Esc arm requires window == "PlayerList_Window", never true here
        rt2.trigger_event("onControlKeyDown", 27.0, "", 0.0, "")
        assert win.visible is True
        rt2.trigger_event("onControlKeyDown", 118.0, "", 0.0, "")
        assert win.visible is False

    def test_f2logwindow_builds_feeds_and_toggles(self):
        rt2, _client_ = self._rt2()
        rt2.load_bytecode("weapon", "-F2LogWindow",
                          (_CORPUS / "_F2LogWindow.gs2bc").read_bytes())
        gui = rt2.gui
        win = gui._named.get("f2logwindow_window")
        tab = gui._named.get("f2logwindow_tab")
        assert win is not None and win.visible is False
        assert [str(r.get("text")) for r in tab.list_rows] == \
            ["Game", "Files", "Scripts", "Net", "Graphics", "Sounds"]
        rt2.fire_log_message("hello engine log", 0.2, 0.2, 1.0, "game")
        pane = gui._named.get("f2logwindow_text0")
        assert "hello engine log" in pane.text
        rt2.trigger_event("onControlKeyDown", 113.0, "", 0.0, "")
        assert win.visible is True
        rt2.trigger_event("onControlKeyDown", 27.0, "", 0.0, "")
        assert win.visible is True     # Esc arm dead (window always "")
        rt2.trigger_event("onControlKeyDown", 113.0, "", 0.0, "")
        assert win.visible is False

    def test_scripterror_category_folds_into_scripts_tab(self):
        rt2, _client_ = self._rt2()
        rt2.load_bytecode("weapon", "-F2LogWindow",
                          (_CORPUS / "_F2LogWindow.gs2bc").read_bytes())
        rt2.fire_log_message("boom", 1.0, 0.0, 0.0, "scripterrors")
        pane = rt2.gui._named.get("f2logwindow_text2")   # "scripts" tab
        assert "boom" in pane.text
