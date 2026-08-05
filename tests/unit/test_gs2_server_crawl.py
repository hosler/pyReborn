from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from game_tester.gs2_server_crawl import aggregate, run_crawl, select_entries
from game_tester.gs2_ui_explorer.capture import CaptureWriter
from pyreborn.listserver import ServerEntry


def _entry(name: str, prefix: str = "", port: int = 14900) -> ServerEntry:
    return ServerEntry(name, prefix, "English", "", "", "6.037", 0,
                       "127.0.0.1", port)


def test_server_filter_limit_and_non_game_marker():
    entries = [_entry("Alpha"), _entry("Beta", "P "),
               _entry("Chat", "C "), _entry("Gamma")]
    assert [item.name for item in select_entries(entries, "beta,ALPHA", 1)] == ["Alpha"]
    assert [item.name for item in select_entries(entries)] == ["Alpha", "Beta", "Gamma"]
    assert select_entries(entries, limit=0) == []


def test_failure_is_recorded_and_does_not_abort(tmp_path):
    entries = [_entry("Bad"), _entry("Good", port=14901)]
    calls = []

    def runner(entry, _prefs, _seconds, _out):
        calls.append(entry.name)
        if entry.name == "Bad":
            raise RuntimeError("broken protocol")
        return {"status": "ok", "missing_builtins": {},
                "warning_kinds": {}, "blocked_sends": [], "bytecodes": {}}

    report = run_crawl(out_dir=tmp_path, prefs=SimpleNamespace(),
                       entry_fetcher=lambda _prefs, _timeout: entries,
                       server_runner=runner, sleep=lambda _seconds: None)
    assert calls == ["Bad", "Good"]
    assert [row["status"] for row in report["servers"]] == ["error", "ok"]
    assert "broken protocol" in report["servers"][0]["reason"]


def test_aggregation_ranks_breadth_before_volume():
    records = [
        {"name": "A", "status": "ok", "missing_builtins": {"wide": 1, "loud": 50}},
        {"name": "B", "status": "ok", "missing_builtins": {"wide": 2}},
        {"name": "C", "status": "ok", "missing_builtins": {}},
    ]
    rows = aggregate(records)["missing_builtins"]
    assert [row["name"] for row in rows] == ["wide", "loud"]
    assert rows[0]["server_count"] == 2
    assert rows[0]["total_count"] == 3


def test_report_file_shapes(tmp_path):
    report = run_crawl(out_dir=tmp_path, prefs=SimpleNamespace(),
                       entry_fetcher=lambda _prefs, _timeout: [_entry("One")],
                       server_runner=lambda *_args: {
                           "status": "ok", "missing_builtins": {"foo": 2},
                           "warning_kinds": {"template": 1},
                           "blocked_sends": [{"packet_name": "PLI_CHAT"}],
                           "bytecodes": {"weapon": 1, "class": 2, "npc": 3},
                           "refused_assets": 4},
                       sleep=lambda _seconds: None)
    disk = json.loads((tmp_path / "crawl_report.json").read_text())
    markdown = (tmp_path / "crawl_report.md").read_text()
    assert disk.keys() == report.keys()
    assert set(disk["gaps"]) == {"missing_builtins", "warning_kinds", "blocked_packets"}
    assert disk["servers"][0]["bytecodes"] == {"weapon": 1, "class": 2, "npc": 3}
    assert "| One | ok | 1 | 2 | 3 | 4 | 1 |" in markdown
    assert "## Missing builtins" in markdown


def test_capture_writer_keeps_bounded_formatted_vm_samples(tmp_path):
    writer = CaptureWriter(tmp_path)
    handler = writer.warning_handler(limit=2)
    logger = logging.getLogger("pyreborn.gs2_client.runtime")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        logger.warning("GS2 %s.%s aborted: %s", "shop", "onAction", "first")
        logger.warning("GS2 %s.%s aborted: %s", "shop", "onAction", "second")
        logger.warning("GS2 %s.%s aborted: %s", "shop", "onAction", "third")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    samples = json.loads(writer.warning_samples_path.read_text())
    template = next(iter(samples))
    assert len(samples[template]) == 2
    assert samples[template][0] == {"vm": "shop.onAction", "message": "GS2 shop.onAction aborted: first"}
