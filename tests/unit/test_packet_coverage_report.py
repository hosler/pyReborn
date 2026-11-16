import pytest
from types import SimpleNamespace

from game_tester.packet_coverage import CoverageReport, PacketTrace, build_report


def test_empty_server_rows_with_client_packets_report_zero_and_warning(capsys):
    report = CoverageReport(account="tester", client_sent={1: ["00"]})

    assert report.coverage_pct() == 0.0
    report.print_summary()

    assert "NO PACKETS: the session exercised nothing" in capsys.readouterr().out


def test_nonempty_server_rows_keep_existing_coverage_calculation():
    report = CoverageReport(
        account="tester",
        server_out={1: 1, 2: 1},
        client_stats={
            1: {"received": 1, "handled": 1, "errors": 0},
            2: {"received": 1, "handled": 0, "errors": 0},
        },
    )

    assert report.coverage_pct() == 50.0


def test_untraced_session_reports_what_the_client_received(capsys):
    report = CoverageReport(
        account="tester", trace_available=False,
        client_stats={
            55: {"received": 2, "handled": 2, "errors": 0},
            9: {"received": 1, "handled": 0, "errors": 0},
            8: {"received": 1, "handled": 1, "errors": 1},
            50: {"received": 0, "handled": 0, "errors": 0},
        },
        client_sent={50: ["00"]})

    verdicts = {pid: verdict for pid, _n, _s, _r, _h, _e, verdict in report.plo_status()}
    assert verdicts == {8: "ERROR", 9: "UNHANDLED", 55: "OK"}
    assert [row[5] for row in report.pli_status()] == ["NOTRACE"]
    assert report.coverage_pct() == 100.0 / 3
    report.print_summary()
    out = capsys.readouterr().out
    assert "client received 3 distinct PLO types (no server trace: bytes not compared)" in out
    assert "client sent 1 distinct PLI types (no server trace: bytes not compared)" in out
    assert "PLI builders (client sent; no server trace: bytes not compared)" in out
    assert "server sent" not in out
    assert "client-sent bytes vs server-received bytes" not in out


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_trace_counts_as_untraced(tmp_path, exists):
    path = tmp_path / "packettrace.txt"
    if exists:
        path.write_text("")
    trace = PacketTrace(str(path))
    trace.mark()
    report = build_report("qastaff", trace, {55: {"received": 1, "handled": 1, "errors": 0}})
    assert report.trace_available is False
    assert [row[6] for row in report.plo_status()] == ["OK"]
    assert not report.failed_checks()


def test_nonempty_trace_without_requested_account_stays_strict(tmp_path, capsys):
    path = tmp_path / "packettrace.txt"
    path.write_text("dir=IN who=other id=50 name=PLI_TEST len=1 hex=00\n"
                    "dir=OUT who=another id=55 name=PLO_TEST len=1 hex=01\n")
    trace = PacketTrace(str(path))
    report = build_report("qastaff", trace,
                          {55: {"received": 1, "handled": 1, "errors": 0}},
                          {50: [b"\x00"]})
    assert report.trace_available is True
    assert [row[5] for row in report.pli_status()] == ["MISMATCH"]
    assert report.gaps() or report.failed_checks()  # CLI failure contract
    report.print_summary()
    out = capsys.readouterr().out
    assert "No trace records for account 'qastaff'" in out
    assert "accounts present: another, other" in out
    assert "MISMATCH" in out
    assert "no server trace" not in out


def test_nonempty_trace_without_session_records_uses_client_view(tmp_path, capsys):
    path = tmp_path / "packettrace.txt"
    path.write_text("dir=IN who=other id=50 name=PLI_TEST len=1 hex=00\n"
                    "dir=OUT who=another id=55 name=PLO_TEST len=1 hex=01\n")
    trace = PacketTrace(str(path))
    trace.mark()
    report = build_report("qastaff", trace,
                          {55: {"received": 1, "handled": 1, "errors": 0}},
                          {50: [b"\x00"]})
    assert report.trace_available is False
    assert not report.failed_checks()
    assert [row[6] for row in report.plo_status()] == ["OK"]
    assert [row[5] for row in report.pli_status()] == ["NOTRACE"]
    assert not report.gaps() and not report.pli_gaps()
    assert report.notes == [
        f"Trace file at {path} gained no records during this session "
        "and is ignored; the run is reported from the client's view. "
        "A traced server that has not flushed looks the same."]
    report.print_summary()
    out = capsys.readouterr().out
    assert f"[!] {report.notes[0]}" in out
    assert "No trace records for account" not in out
    assert "accounts present" not in out
    assert "MISMATCH" not in out


def test_appended_trace_without_requested_account_stays_strict(tmp_path, capsys):
    path = tmp_path / "packettrace.txt"
    path.write_text("dir=IN who=stale id=50 name=PLI_TEST len=1 hex=00\n")
    trace = PacketTrace(str(path))
    trace.mark()
    with path.open("a") as stream:
        stream.write("dir=IN who=other id=50 name=PLI_TEST len=1 hex=00\n"
                     "dir=OUT who=another id=55 name=PLO_TEST len=1 hex=01\n")
    report = build_report("qastaff", trace,
                          {55: {"received": 1, "handled": 1, "errors": 0}},
                          {50: [b"\x00"]})
    assert report.trace_available is True
    assert [row[5] for row in report.pli_status()] == ["MISMATCH"]
    assert report.failed_checks()[0][0] == "trace_account"
    assert "accounts present: another, other." in report.failed_checks()[0][2]
    assert "stale" not in report.failed_checks()[0][2]
    assert report.gaps() or report.failed_checks()  # CLI failure contract
    report.print_summary()
    out = capsys.readouterr().out
    assert "No trace records for account 'qastaff'" in out
    assert "accounts present: another, other." in out
    assert "MISMATCH" in out
    assert "no server trace" not in out


def test_trace_for_requested_account_keeps_round_trip_comparison(tmp_path):
    path = tmp_path / "packettrace.txt"
    path.write_text("dir=IN who=qastaff id=50 name=PLI_TEST len=1 hex=00\n"
                    "dir=OUT who=qastaff id=55 name=PLO_TEST len=1 hex=01\n")
    report = build_report("qastaff", PacketTrace(str(path)),
                          {55: {"received": 1, "handled": 1, "errors": 0}},
                          {50: [b"\x00"]})
    assert report.trace_available is True
    assert [row[6] for row in report.plo_status()] == ["OK"]
    assert [row[5] for row in report.pli_status()] == ["OK"]
    assert not report.failed_checks()


@pytest.mark.parametrize("kind", ["rc", "nc"])
def test_coverage_runner_preserves_trace_failure_and_diagnostic(tmp_path, monkeypatch, kind):
    from itertools import count
    from game_tester import exercise_nc, exercise_rc, live_checks_rcnc, packet_coverage
    from pyreborn import nc_client, rc_client

    path = tmp_path / "packettrace.txt"
    path.write_text("")

    class Client:
        packet_stats = {}
        _protocol = SimpleNamespace(sent_payloads={})

        def connect(self):
            return True

        def login(self, *args, **kwargs):
            return True

        def disconnect(self):
            pass

    client = Client()

    def battery(*args, **kwargs):
        path.write_text("dir=IN who=other id=50 name=PLI_TEST len=1 hex=00\n")
        client._protocol.sent_payloads = {50: [b"\x00"]}
        return ["battery note"]

    monkeypatch.setattr(rc_client, "RCClient", lambda *a, **kw: client)
    monkeypatch.setattr(nc_client, "NCClient", lambda *a, **kw: client)
    monkeypatch.setattr(exercise_rc, "run_rc_battery", battery)
    monkeypatch.setattr(exercise_nc, "run_nc_battery", battery)
    ticks = count(0, 10)
    monkeypatch.setattr(packet_coverage.time, "time", lambda: next(ticks))
    monkeypatch.setattr(live_checks_rcnc, "run_live_checks",
                        lambda *a: [("live_check", "pass", "fine")])
    runner = getattr(packet_coverage, "run_coverage_" + kind)
    report = runner(trace_path=str(path), verbose=False)
    assert report.trace_available is True
    assert report.failed_checks()[0][0] == "trace_account"
    assert report.checks[-1] == ("live_check", "pass", "fine")
    assert "No trace records for account 'qastaff'" in report.notes[0]
    assert report.notes[-1] == "battery note"
    assert report.pli_status()[0][5] == "MISMATCH"


def test_failed_live_checks_are_listed_and_printed(capsys):
    report = CoverageReport(account="tester")
    report.checks = [("a", "pass", "fine"), ("b", "skip", "no gmap"), ("c", "fail", "bad")]
    assert report.failed_checks() == [("c", "fail", "bad")]
    report.print_summary()
    out = capsys.readouterr().out
    assert "[FAIL] c: bad" in out and "[SKIP] b: no gmap" in out
    assert report.to_dict()["checks"][2] == {"name": "c", "status": "fail", "detail": "bad"}
