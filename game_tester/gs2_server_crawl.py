"""Sequential passive GS2 UI exploration across public-list servers."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from game_tester.behaviour_fingerprint import (
    REMOTE_SPACING, _LogCapture, delta_counters, snapshot_host_counters,
    snapshot_logs,
)
from game_tester.server_probe import fetch_entries, parse_server_name
from pyreborn.prefs import Prefs


GAME_TYPE_PREFIXES = {"", "H ", "P ", "3 ", "U "}


def default_crawl_dir() -> Path:
    root = os.environ.get("PYREBORN_RC_DOWNLOAD_DIR") or os.environ.get("PYREBORN_DATA")
    base = Path(root) if root else Path.home() / ".local" / "share" / "pyreborn"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / "gs2_crawls" / stamp


def select_entries(entries: Iterable[Any], names: str | None = None,
                   limit: int | None = None) -> list[Any]:
    if limit is not None and limit <= 0:
        return []
    wanted = ({part.strip().casefold() for part in names.split(",") if part.strip()}
              if names else None)
    selected = []
    for entry in entries:
        if getattr(entry, "type_prefix", "") not in GAME_TYPE_PREFIXES:
            continue
        clean, _category = parse_server_name(entry.display_name)
        if wanted is not None and clean.casefold() not in wanted:
            continue
        selected.append(entry)
        if limit is not None and len(selected) >= max(0, limit):
            break
    return selected


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return value or "server"


def _run_server(entry: Any, prefs: Prefs, seconds: float, out_dir: Path) -> dict[str, Any]:
    from game_tester.gs2_ui_explorer.capture import CaptureWriter
    from game_tester.gs2_ui_explorer.explorer import ExplorerBot, ExplorerBudget
    from game_tester.gs2_ui_explorer.pump import GamePump
    from game_tester.gs2_ui_explorer.send_policy import PassiveSendPolicy
    from game_tester.login import login_session
    from pyreborn.pygame_game import GameClient

    writer = CaptureWriter(out_dir, {"host": entry.ip, "port": entry.port,
                                    "mode": "passive", "duration": seconds,
                                    "limits": vars(ExplorerBudget())})
    policy = PassiveSendPolicy(writer.blocked_path, allow_sends=False)
    logs = _LogCapture()
    samples = writer.warning_handler()
    host_before = snapshot_host_counters()
    root_logger = logging.getLogger()
    with login_session(entry.ip, entry.port, prefs.username, prefs.password) as outcome:
        if not outcome.ok:
            status = "rejected" if outcome.connected else "unreachable"
            return {"status": status,
                    "reason": outcome.rejection or "connection or login failed"}
        outcome.client._protocol.outbound_policy = policy
        root_logger.addHandler(logs)
        root_logger.addHandler(samples)
        try:
            game = GameClient(outcome.client)
            game._explorer_log_capture = logs
            game._load_npc_scripts()
            game._trigger_playerenters()
            result = ExplorerBot(game, pump=GamePump(game), writer=writer,
                                 policy=policy).explore(seconds)
        finally:
            root_logger.removeHandler(samples)
            root_logger.removeHandler(logs)
    bytecodes = {kind: len(blobs) for kind, blobs in
                 (getattr(outcome.client, "gs2_bytecode", {}) or {}).items()}
    log_data = snapshot_logs(logs)
    return {
        "status": "ok", "reason": "", "capture_dir": str(out_dir),
        "states": result.states, "actions": result.actions,
        "bytecodes": {kind: bytecodes.get(kind, 0) for kind in ("weapon", "class", "npc")},
        "missing_builtins": delta_counters(host_before.get("missing", {}),
                                            snapshot_host_counters().get("missing", {})),
        "warning_kinds": log_data["kinds"],
        "warning_samples": dict(writer._warning_samples),
        "refused_assets": sum(log_data["refused"].values()),
        "blocked_sends": list(policy.blocked),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    def ranked(mapping: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
        rows = [{"name": name, "servers": sorted(counts),
                 "server_count": len(counts), "total_count": sum(counts.values()),
                 "counts": dict(sorted(counts.items()))}
                for name, counts in mapping.items()]
        return sorted(rows, key=lambda row: (-row["server_count"],
                                             -row["total_count"], row["name"]))

    builtins: dict[str, dict[str, int]] = defaultdict(dict)
    warnings: dict[str, dict[str, int]] = defaultdict(dict)
    blocked: dict[str, dict[str, int]] = defaultdict(dict)
    for record in records:
        if record.get("status") != "ok":
            continue
        name = record["name"]
        for gap, count in record.get("missing_builtins", {}).items():
            builtins[gap][name] = int(count)
        for kind, count in record.get("warning_kinds", {}).items():
            warnings[kind][name] = int(count)
        counts = Counter(item.get("packet_name", "unknown")
                         for item in record.get("blocked_sends", []))
        for packet, count in counts.items():
            blocked[packet][name] = count
    return {"missing_builtins": ranked(builtins),
            "warning_kinds": ranked(warnings),
            "blocked_packets": ranked(blocked)}


def write_reports(out_dir: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = aggregate(records)
    report = {"schema_version": 1,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "servers": records, "gaps": gaps}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "crawl_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# GS2 server crawl", "", "## Servers", "",
             "| Server | Status | Weapon | Class | NPC | Refused | Blocked | Reason |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in records:
        bc = row.get("bytecodes", {})
        reason = str(row.get("reason", "")).replace("|", "\\|")
        lines.append(f"| {row['name']} | {row['status']} | {bc.get('weapon', 0)} | "
                     f"{bc.get('class', 0)} | {bc.get('npc', 0)} | "
                     f"{row.get('refused_assets', 0)} | {len(row.get('blocked_sends', []))} | {reason} |")
    labels = (("Missing builtins", "missing_builtins"),
              ("Warning kinds", "warning_kinds"),
              ("Blocked send packets", "blocked_packets"))
    for title, key in labels:
        lines += ["", f"## {title}", "", "| Gap | Servers | Total | Server names |",
                  "|---|---:|---:|---|"]
        for gap in gaps[key]:
            lines.append(f"| {gap['name'].replace('|', '\\|')} | {gap['server_count']} | "
                         f"{gap['total_count']} | {', '.join(gap['servers'])} |")
    (out_dir / "crawl_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def run_crawl(*, seconds: float = 75.0, out_dir: str | Path | None = None,
              servers: str | None = None, limit: int | None = None,
              prefs: Prefs | None = None,
              entry_fetcher: Callable[[Prefs, float], list[Any]] = fetch_entries,
              server_runner: Callable[[Any, Prefs, float, Path], dict[str, Any]] = _run_server,
              sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    prefs = prefs or Prefs.load()
    destination = Path(out_dir) if out_dir else default_crawl_dir()
    entries = select_entries(entry_fetcher(prefs, 20.0), servers, limit)
    records = []
    for index, entry in enumerate(entries):
        if index:
            sleep(REMOTE_SPACING)
        name, _category = parse_server_name(entry.display_name)
        server_out = destination / f"{index + 1:03d}-{_slug(name)}"
        base = {"name": name, "host": entry.ip, "port": entry.port}
        try:
            result = server_runner(entry, prefs, seconds, server_out)
        except (TimeoutError, socket.timeout) as exc:
            result = {"status": "unreachable", "reason": str(exc) or "timeout"}
        except Exception as exc:
            result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
        records.append({**base, **result})
    report = write_reports(destination, records)
    print("Server                         Status       Builtins Warnings Blocked")
    for row in records:
        print(f"{row['name'][:29]:29} {row['status']:12} "
              f"{sum(row.get('missing_builtins', {}).values()):8} "
              f"{sum(row.get('warning_kinds', {}).values()):8} "
              f"{len(row.get('blocked_sends', [])):7}")
    print(f"Report: {destination / 'crawl_report.md'}")
    return report
