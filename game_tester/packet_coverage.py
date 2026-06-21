"""
packet_coverage - Protocol coverage harness for pyReborn.

The real GServer-v2 logs every packet it sends/receives per account to
``packettrace.txt`` (enabled with ``GS_PKTLOG=1``). That file is ground truth:
it tells us exactly which PLO (server->client) packets the server emitted to a
given bot and the exact bytes of each PLI (client->server) packet the server
received.

This module cross-references that trace against pyReborn's own instrumentation
(``Client.packet_stats``) to answer two questions for full coverage:

  1. Did pyReborn *receive and handle* every PLO the server sent it?
     (pyReborn silently drops packet ids it has no branch for.)
  2. Does every PLI builder produce the *exact bytes* the server received?

Usage:
    from game_tester.packet_coverage import run_coverage
    report = run_coverage(host="localhost", port=14900)
    report.print_summary()
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

try:
    from reborn_protocol.constants import PLO, PLI
except ImportError:  # pragma: no cover - PYTHONPATH fallback
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                    "reborn-protocol"))
    from reborn_protocol.constants import PLO, PLI


# Default location of the GServer-v2 packet trace, relative to the repo root.
_DEFAULT_TRACE = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "GServer-v2", "bin", "servers", "default", "logs", "packettrace.txt"))

# id -> name maps for human-readable reports.
PLO_NAMES: Dict[int, str] = {int(m): m.name for m in PLO}
PLI_NAMES: Dict[int, str] = {int(m): m.name for m in PLI}

# PLO ids the server reliably emits but which carry no client-side state worth
# asserting on (pure server bookkeeping / display). Tracked but not counted as
# coverage gaps. Keep this list short and justified.
IGNORED_PLO: Set[int] = set()

_LINE_RE = re.compile(
    r"dir=(?P<dir>OUT|IN)\s+who=(?P<who>\S+)\s+id=(?P<id>\d+)\s+"
    r"name=(?P<name>\S+)\s+len=(?P<len>\d+)\s+hex=(?P<hex>\S*)")


@dataclass
class TraceRecord:
    direction: str   # "OUT" (server->client) or "IN" (client->server)
    who: str         # account name
    pid: int         # packet id
    name: str        # PLO_/PLI_ name as the server sees it
    length: int
    hex: str         # payload bytes (after the id byte), hex string


class PacketTrace:
    """Offset-based reader for the server's packettrace.txt.

    ``packettrace.txt`` accumulates across server runs, so we snapshot the file
    size with :meth:`mark` at the start of a session and only parse bytes
    appended afterwards via :meth:`read_new`.
    """

    def __init__(self, path: str = _DEFAULT_TRACE):
        self.path = path
        self._offset = 0

    def available(self) -> bool:
        return os.path.isfile(self.path)

    def mark(self) -> None:
        """Record the current end-of-file so read_new() only sees new lines."""
        self._offset = os.path.getsize(self.path) if self.available() else 0

    def read_new(self, who: Optional[str] = None) -> List[TraceRecord]:
        """Parse trace lines appended since the last mark().

        Args:
            who: if given, only return records for this account.
        """
        if not self.available():
            return []
        records: List[TraceRecord] = []
        with open(self.path, "r", errors="replace") as f:
            f.seek(self._offset)
            for line in f:
                m = _LINE_RE.search(line)
                if not m:
                    continue
                if who is not None and m.group("who") != who:
                    continue
                records.append(TraceRecord(
                    direction=m.group("dir"),
                    who=m.group("who"),
                    pid=int(m.group("id")),
                    name=m.group("name"),
                    length=int(m.group("len")),
                    hex=m.group("hex"),
                ))
        return records


@dataclass
class CoverageReport:
    account: str
    # server_out: PLO id -> count the server sent this bot
    server_out: Dict[int, int] = field(default_factory=dict)
    # server_in: PLI id -> list of hex payloads the server received from this bot
    server_in: Dict[int, List[str]] = field(default_factory=dict)
    # client_sent: PLI id -> list of hex payloads pyReborn actually sent
    client_sent: Dict[int, List[str]] = field(default_factory=dict)
    # client_stats: copy of Client.packet_stats (id -> received/handled/errors)
    client_stats: Dict[int, Dict[str, object]] = field(default_factory=dict)
    trace_available: bool = True
    notes: List[str] = field(default_factory=list)

    # ---- derived views -------------------------------------------------

    def plo_status(self) -> List[Tuple[int, str, int, int, int, int, str]]:
        """One row per PLO id the server sent.

        Returns tuples: (id, name, sent, received, handled, errors, verdict).
        """
        rows = []
        for pid in sorted(self.server_out):
            sent = self.server_out[pid]
            st = self.client_stats.get(pid, {})
            recv = int(st.get("received", 0))
            handled = int(st.get("handled", 0))
            errors = int(st.get("errors", 0))
            name = PLO_NAMES.get(pid, f"PLO_{pid}")
            if pid in IGNORED_PLO:
                verdict = "IGNORED"
            elif errors:
                verdict = "ERROR"
            elif recv == 0:
                verdict = "DROPPED"      # server sent it, client never saw it
            elif handled == 0:
                verdict = "UNHANDLED"    # received but no handler branch
            else:
                verdict = "OK"
            rows.append((pid, name, sent, recv, handled, errors, verdict))
        return rows

    def gaps(self) -> List[Tuple[int, str, str]]:
        """PLO ids the server sent that aren't cleanly handled."""
        return [(pid, name, verdict)
                for pid, name, _s, _r, _h, _e, verdict in self.plo_status()
                if verdict not in ("OK", "IGNORED")]

    def pli_status(self) -> List[Tuple[int, str, int, int, int, str]]:
        """One row per PLI id pyReborn sent during the session.

        Cross-checks the bytes the client *sent* against what the server
        *received* (a true wire round-trip: builder + framing + encryption).
        Returns tuples: (id, name, client_sent, matched, total_server, verdict).
        """
        from collections import Counter
        rows = []
        for pid in sorted(self.client_sent):
            sent = self.client_sent[pid]
            srv = Counter(self.server_in.get(pid, []))
            matched = 0
            for payload in sent:
                if srv.get(payload, 0) > 0:
                    srv[payload] -= 1
                    matched += 1
            name = PLI_NAMES.get(pid, f"PLI_{pid}")
            if not self.trace_available:
                verdict = "NOTRACE"
            elif matched == len(sent):
                verdict = "OK"
            elif matched == 0:
                verdict = "MISMATCH"
            else:
                verdict = "PARTIAL"
            rows.append((pid, name, len(sent), matched,
                         len(self.server_in.get(pid, [])), verdict))
        return rows

    def pli_gaps(self) -> List[Tuple[int, str, str]]:
        return [(pid, name, v) for pid, name, _s, _m, _t, v in self.pli_status()
                if v not in ("OK", "NOTRACE")]

    def coverage_pct(self) -> float:
        rows = [r for r in self.plo_status() if r[6] != "IGNORED"]
        if not rows:
            return 100.0
        ok = sum(1 for r in rows if r[6] == "OK")
        return 100.0 * ok / len(rows)

    def unseen_plo(self) -> List[Tuple[int, str]]:
        """Known PLO types the server never sent this session (need a driver)."""
        return [(pid, name) for pid, name in sorted(PLO_NAMES.items())
                if pid not in self.server_out]

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "trace_available": self.trace_available,
            "coverage_pct": round(self.coverage_pct(), 1),
            "plo_status": [
                {"id": pid, "name": name, "sent": s, "received": r,
                 "handled": h, "errors": e, "verdict": v}
                for pid, name, s, r, h, e, v in self.plo_status()
            ],
            "gaps": [{"id": pid, "name": name, "verdict": v}
                     for pid, name, v in self.gaps()],
            "pli_status": [
                {"id": pid, "name": name, "sent": s, "matched": m,
                 "server_total": t, "verdict": v}
                for pid, name, s, m, t, v in self.pli_status()
            ],
            "pli_gaps": [{"id": pid, "name": name, "verdict": v}
                         for pid, name, v in self.pli_gaps()],
            "notes": self.notes,
        }

    # ---- rendering -----------------------------------------------------

    def print_summary(self) -> None:
        print("=" * 64)
        print(f"  PACKET COVERAGE - account={self.account}")
        print("=" * 64)
        if not self.trace_available:
            print("  [!] No packet trace found - is GS_PKTLOG=1 set on the server?")
            print(f"      expected: {_DEFAULT_TRACE}")
        rows = self.plo_status()
        print(f"  server sent {len(rows)} distinct PLO types this session")
        print(f"  PLI types exercised: {len(self.server_in)}")
        print(f"  PLO coverage: {self.coverage_pct():.0f}%")
        print("-" * 64)
        print(f"  {'id':>3} {'name':<24} {'sent':>4} {'rcv':>4} "
              f"{'hdl':>4} {'err':>4}  verdict")
        for pid, name, s, r, h, e, v in rows:
            flag = " " if v in ("OK", "IGNORED") else "*"
            print(f" {flag}{pid:>3} {name:<24} {s:>4} {r:>4} {h:>4} {e:>4}  {v}")
        gaps = self.gaps()
        if gaps:
            print("-" * 64)
            print(f"  {len(gaps)} PLO GAP(S): " +
                  ", ".join(f"{n}({v})" for _p, n, v in gaps))
        # PLI builder round-trip validation.
        pli_rows = self.pli_status()
        if pli_rows:
            print("-" * 64)
            print("  PLI builders (client-sent bytes vs server-received bytes)")
            print(f"  {'id':>3} {'name':<24} {'sent':>4} {'ok':>4} "
                  f"{'srv':>4}  verdict")
            for pid, name, s, m, t, v in pli_rows:
                flag = " " if v in ("OK", "NOTRACE") else "*"
                print(f" {flag}{pid:>3} {name:<24} {s:>4} {m:>4} {t:>4}  {v}")
            pgaps = self.pli_gaps()
            if pgaps:
                print(f"  {len(pgaps)} PLI GAP(S): " +
                      ", ".join(f"{n}({v})" for _p, n, v in pgaps))
        print("=" * 64)


def build_report(account: str, trace: PacketTrace,
                 client_stats: Dict[int, Dict[str, object]],
                 sent_payloads: Optional[Dict[int, List[bytes]]] = None
                 ) -> CoverageReport:
    """Combine the server trace and the client's packet_stats into a report."""
    report = CoverageReport(account=account, trace_available=trace.available())
    for rec in trace.read_new(who=account):
        if rec.direction == "OUT":
            report.server_out[rec.pid] = report.server_out.get(rec.pid, 0) + 1
        else:  # IN
            report.server_in.setdefault(rec.pid, []).append(rec.hex.lower())
    # Deep-ish copy of stats so the report is a stable snapshot.
    report.client_stats = {pid: dict(st) for pid, st in client_stats.items()}
    if sent_payloads:
        report.client_sent = {pid: [p.hex() for p in payloads]
                              for pid, payloads in sent_payloads.items()}
    return report


def run_coverage(host: str = "localhost", port: int = 14900,
                 account: str = "testbot1", password: str = "testpass",
                 trace_path: str = _DEFAULT_TRACE,
                 verbose: bool = True) -> CoverageReport:
    """Connect a bot, exercise a broad battery of behaviors, and report coverage.

    The battery is intentionally wide so the server emits as many PLO types as
    possible. Each action is best-effort: failures are recorded as notes rather
    than aborting, so one missing fixture doesn't zero out the whole report.
    """
    # Imported here to avoid a hard dependency when only the parser is used.
    from .exercise import run_exercise_battery
    from .game_bot import GameBot

    trace = PacketTrace(trace_path)
    trace.mark()

    bot = GameBot(account, host, port, password=password)
    notes: List[str] = []
    if not bot.connect():
        notes.append("bot failed to connect/login")
        report = build_report(account, trace, {})
        report.notes = notes
        return report

    # Record outgoing payloads from here on (login is already done) so we can
    # diff them against the server's received view.
    bot.client._protocol.sent_payloads = {}

    try:
        notes.extend(run_exercise_battery(bot, verbose=verbose))
        # Drain any trailing packets the server queued in response.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            bot.client.update(timeout=0.1)
    finally:
        report = build_report(account, trace, bot.client.packet_stats,
                              bot.client._protocol.sent_payloads)
        report.notes = notes
        bot.disconnect()

    return report


def run_coverage_nc(host: str = "localhost", port: int = 14900,
                    account: str = "testbot1", password: str = "testpass",
                    trace_path: str = _DEFAULT_TRACE,
                    verbose: bool = True) -> CoverageReport:
    """Connect as an NC (npc-control) client, exercise the NC surface, report.

    Like the RC harness this logs in under `account`, so run it when no game/RC
    bot for that account is connected (the trace filters by account). NC uses
    ENCRYPT_GEN_2 framing - see NCClient / Protocol.use_gen2().

    Note: NPC/class *reply* packets (PLO_NC_NPCADD/NPCSCRIPT/CLASSGET/...) only
    appear when the server runs an npc-server (V8/GS2). Without one, the npc/
    class commands round-trip as PLI (builder coverage) but elicit no PLO.
    """
    from .exercise_nc import run_nc_battery
    from pyreborn.nc_client import NCClient

    trace = PacketTrace(trace_path)
    trace.mark()

    nc = NCClient(host, port, version="6.037")
    notes: List[str] = []
    if not nc.connect():
        notes.append("NC failed to connect")
        report = build_report(account, trace, {})
        report.notes = notes
        return report
    if not nc.login(account, password, timeout=10.0):
        notes.append("NC login failed (staff rights / localhost mode?)")
        report = build_report(account, trace, nc.packet_stats)
        report.notes = notes
        nc.disconnect()
        return report

    # Drain the login burst (SIGNATURE/NEWWORLDTIME), then record outgoing
    # payloads for the PLI round-trip diff.
    deadline = time.time() + 1.5
    while time.time() < deadline:
        nc.update(timeout=0.1)
    nc._protocol.sent_payloads = {}

    try:
        notes.extend(run_nc_battery(nc, verbose=verbose))
        deadline = time.time() + 2.0
        while time.time() < deadline:
            nc.update(timeout=0.1)
    finally:
        report = build_report(account, trace, nc.packet_stats,
                              nc._protocol.sent_payloads)
        report.notes = notes
        nc.disconnect()

    return report


def run_coverage_rc(host: str = "localhost", port: int = 14900,
                    account: str = "testbot1", password: str = "testpass",
                    trace_path: str = _DEFAULT_TRACE,
                    verbose: bool = True) -> CoverageReport:
    """Connect as an RC admin, exercise the RC surface, and report coverage.

    The RC connection logs in under the same account as the base bot, so run
    this when no game bot for that account is connected (the trace filters by
    account and would otherwise mix the two).
    """
    from .exercise_rc import run_rc_battery
    from pyreborn.rc_client import RCClient

    trace = PacketTrace(trace_path)
    trace.mark()

    rc = RCClient(host, port, version="6.037")
    notes: List[str] = []
    if not rc.connect():
        notes.append("RC failed to connect")
        report = build_report(account, trace, {})
        report.notes = notes
        return report
    if not rc.login(account, password, timeout=10.0):
        notes.append("RC login failed (staff rights / localhost mode?)")
        report = build_report(account, trace, rc.packet_stats)
        report.notes = notes
        rc.disconnect()
        return report

    # Drain the login burst, then record outgoing payloads for the PLI diff.
    deadline = time.time() + 1.5
    while time.time() < deadline:
        rc.update(timeout=0.1)
    rc._protocol.sent_payloads = {}

    try:
        notes.extend(run_rc_battery(rc, host, port, verbose=verbose))
        deadline = time.time() + 2.0
        while time.time() < deadline:
            rc.update(timeout=0.1)
    finally:
        report = build_report(account, trace, rc.packet_stats,
                              rc._protocol.sent_payloads)
        report.notes = notes
        rc.disconnect()

    return report
