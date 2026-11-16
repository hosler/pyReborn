"""The row logic of the RC/NC live checks, without a server."""
import struct
import sys
from types import SimpleNamespace

import pytest

from game_tester import live_checks_rcnc as live
from game_tester.packet_coverage import CoverageReport


def _entry(player_id, account, level, status, nick, community):
    def gstring(text):
        return bytes([32 + len(text)]) + text.encode()
    return (struct.pack("BB", 32 + (player_id >> 7), 32 + (player_id & 127))
            + gstring(account)
            + bytes([32 + 20]) + gstring(level) + bytes([32 + 53, 32 + status])
            + bytes([32 + 0]) + gstring(nick) + bytes([32 + 82]) + gstring(community))


def test_entries_keep_only_the_probe_account_and_decode_every_field():
    raw = [_entry(3, "other", "a.nw", 0, "o", "other"),
           _entry(4, "testbot3", "start.nw", 0, "nick", "testbot3")]
    entries = live._entries(raw, "testbot3")
    assert len(entries) == 1
    assert entries[0]["level"] == "start.nw"
    assert entries[0]["status"] == 0
    assert entries[0]["nickname"] == "nick"
    assert entries[0]["community"] == "testbot3"


def test_run_live_checks_turns_a_crash_into_a_failed_row(monkeypatch):
    def boom(*args):
        raise OSError("refused")
    monkeypatch.setattr(live, "check_nc_delete_notice", boom)
    rows = live.run_live_checks("nc", "127.0.0.1", 1, "a", "b")
    assert rows == [("nc_live_checks", "fail", "OSError: refused")]


def test_describe_lists_level_status_nick_and_community():
    text = live._describe([{"level": "a.nw", "status": 0, "nickname": "n", "community": "c"}])
    assert "level='a.nw'" in text and "status=0" in text and "nick='n'" in text and "community='c'" in text


@pytest.fixture
def sessions(monkeypatch):
    settings = SimpleNamespace(
        nc_login=True, rc_login=True, bot_connect=True, add_npc=True,
        nc_notices=1, server_notices=1, rc_notices=0,
        login_entries=2, warp_entries=1, same_level_entries=0, gmap_width=0)

    class Session:
        def __init__(self, kind):
            self.kind = kind
            self.packet_stats = {}
            self.npcs = {}

        def connect(self):
            return True

        def login(self, *args, **kwargs):
            return getattr(settings, self.kind + "_login")

        def disconnect(self):
            pass

        def _handle_packet(self, pid, data):
            stats = self.packet_stats.setdefault(int(pid), {"received": 0})
            stats["received"] += 1

        def add_npc(self, name, npc_id, *args):
            if settings.add_npc:
                self.npcs[npc_id] = name

        def delete_npc(self, npc_id):
            self.npcs.pop(npc_id, None)
            self.notice(settings.nc_notices)

        def set_npc_script(self, npc_id, script):
            self.npcs.pop(npc_id, None)
            self.notice(settings.server_notices)

        def notice(self, count):
            for _ in range(count):
                self._handle_packet(live.PLO.NC_NPCDELETE, b"")
            for _ in range(settings.rc_notices):
                rc._handle_packet(live.PLO.NC_NPCDELETE, b"")

    nc, rc = Session("nc"), Session("rc")

    class Bot:
        def __init__(self, account, *args):
            self.account = account
            self.level = live.LEVEL_A
            self.client = SimpleNamespace(gmap_width=settings.gmap_width)

        def emit(self, count, level):
            for _ in range(count):
                rc._handle_packet(live.PLO.ADDPLAYER,
                                  _entry(4, self.account, level, 0, "nick", self.account))

        def connect(self):
            if not settings.bot_connect:
                return False
            self.emit(settings.login_entries, self.level)
            return True

        def warp_to(self, level, *args):
            count = (settings.same_level_entries if level == self.level
                     else settings.warp_entries)
            self.level = level
            self.emit(count, level)

        def disconnect(self):
            pass

    monkeypatch.setattr(live, "NCClient", lambda *a, **kw: nc)
    monkeypatch.setattr(live, "RCClient", lambda *a, **kw: rc)
    monkeypatch.setattr(live, "GameBot", Bot)
    monkeypatch.setattr(live, "_pump", lambda *a: None)
    return settings


def _run(kind):
    return live.run_live_checks(kind, "127.0.0.1", 1, "qastaff", "password")


@pytest.mark.parametrize("count,status", [(1, "pass"), (0, "fail"), (2, "fail")])
def test_nc_delete_checks_expected_missing_and_extra_packets(sessions, count, status):
    sessions.nc_notices = sessions.server_notices = count
    rows = _run("nc")
    assert [(name, st) for name, st, _ in rows] == [
        ("nc_delete_notice_nc_initiated", status),
        ("nc_delete_notice_server_initiated", status)]


def test_nc_delete_checks_reject_a_notice_sent_to_rc(sessions):
    sessions.rc_notices = 1
    assert [status for _, status, _ in _run("nc")] == ["fail", "fail"]


@pytest.mark.parametrize("count", [0, 1, 2])
def test_missing_watcher_is_a_failed_precondition_even_if_notices_arrive(sessions, count):
    sessions.bot_connect = False
    sessions.server_notices = count
    rows = _run("nc")
    assert rows[0][1] == "pass"
    assert rows[1][1] == "precondition_failed"
    assert "watcher failed to connect" in rows[1][2]
    report = CoverageReport(account="qastaff", checks=rows)
    assert report.failed_checks() == [rows[1]]


@pytest.mark.parametrize("kind,setting", [
    ("nc", "nc_login"), ("nc", "rc_login"), ("nc", "add_npc"),
    ("rc", "rc_login"), ("rc", "bot_connect")])
def test_session_setup_failures_have_a_distinct_failing_status(sessions, kind, setting):
    setattr(sessions, setting, False)
    rows = _run(kind)
    assert all(status == "precondition_failed" for _, status, _ in rows)
    assert CoverageReport(account="qastaff", checks=rows).failed_checks() == rows


@pytest.mark.parametrize("counts,statuses", [
    ((2, 1, 0), ["pass", "pass", "pass"]),
    ((0, 0, 0), ["fail", "fail", "pass"]),
    ((3, 2, 1), ["fail", "fail", "fail"]),
])
def test_rc_roster_checks_expected_missing_and_extra_packets(sessions, counts, statuses):
    sessions.login_entries, sessions.warp_entries, sessions.same_level_entries = counts
    rows = _run("rc")
    assert [name for name, _, _ in rows] == [
        "rc_addplayer_login", "rc_addplayer_warp",
        "rc_addplayer_same_level_warp", "rc_addplayer_gmap_hop"]
    # A same-level warp expects silence, so zero packets must pass that check.
    assert [status for _, status, _ in rows] == statuses + ["skip"]


@pytest.mark.parametrize("width", [0, 8])
def test_only_the_undriven_gmap_hop_is_skipped(sessions, width):
    sessions.gmap_width = width
    rows = _run("rc")
    assert [name for name, status, _ in rows if status == "skip"] == ["rc_addplayer_gmap_hop"]
    assert not CoverageReport(account="qastaff", checks=rows).failed_checks()


@pytest.mark.parametrize("status,exit_code", [
    ("pass", 0), ("fail", 1), ("precondition_failed", 1), ("skip", 0)])
def test_fake_session_statuses_preserve_cli_exit_contract(sessions, monkeypatch, status, exit_code):
    from game_tester import __main__ as cli
    from game_tester import packet_coverage

    if status == "fail":
        sessions.warp_entries = 0
    elif status == "precondition_failed":
        sessions.bot_connect = False
    rows = [row for row in _run("rc") if row[1] == status]
    assert rows
    report = CoverageReport(account="qastaff", checks=rows)
    monkeypatch.setattr(packet_coverage, "run_coverage_rc", lambda **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["game_tester", "--coverage-rc"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == exit_code
