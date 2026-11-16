"""
live_checks_rcnc - live assertions for what an RC or NC connection is told.

The coverage batteries (exercise_rc, exercise_nc) only count packet ids. These
checks assert WHO is sent WHAT, against a running pygserver that gives the
staff account RC and NC access (``qa_server run --staff qastaff``):

NC delete notice (GServer-v2 Server.cpp:1625-1641, Server::deleteNPC)
    A destroyed NPC is announced to every NC connection with one
    PLO_NC_NPCDELETE, and to no RC connection. Two paths: the NC deleting a
    database NPC (NC_NPCDELETE) and the server destroying one by itself (the
    NPC's own script).

RC roster entry (PlayerClient.cpp:1155-1162, 1341-1347)
    A game player's PLO_ADDPLAYER reaches every RC at login (twice: before
    the first level entry with the start level, then at the entry) and again
    on each level entry. A same-level warp and a gmap hop are no entry.

Each check returns a (name, status, detail) row; status is "pass", "fail",
"precondition_failed" or "skip". Failed preconditions fail the suite; only
the undriven gmap hop is skipped.
"""

from __future__ import annotations

import time
from typing import Callable, List, Tuple

from reborn_protocol.constants import PLO

from pyreborn.nc_client import NCClient
from pyreborn.packets import parse_rc_add_player
from pyreborn.rc_client import RCClient

from .game_bot import GameBot

Row = Tuple[str, str, str]

PROBE_ACCOUNT = "testbot3"
LEVEL_A = "onlinestartlocal.nw"
LEVEL_B = "qa_testlevel.nw"
SELF_DESTROY_ID = 56001
NC_DELETE_ID = 56000


def _pump(clients, seconds: float):
    deadline = time.time() + seconds
    while time.time() < deadline:
        for client in clients:
            client.update(timeout=0.05)
        time.sleep(0.02)


def _received(client, packet_id) -> int:
    return int(client.packet_stats.get(int(packet_id), {}).get("received", 0))


def _record_packets(client, packet_id) -> List[bytes]:
    """Keep the payload of every `packet_id` the client is sent. RCClient
    consumes its own packet ids before the generic listener hook, so the
    recorder sits in front of its dispatcher."""
    seen: List[bytes] = []
    original = client._handle_packet

    def recording(pid, data):
        if pid == int(packet_id):
            seen.append(bytes(data))
        return original(pid, data)

    client._handle_packet = recording
    return seen


def _login(client, account: str, password: str) -> bool:
    if not client.connect() or not client.login(account, password, timeout=10.0):
        return False
    _pump([client], 1.0)
    return True


def _entries(raw: List[bytes], account: str) -> List[dict]:
    parsed = [parse_rc_add_player(data) for data in raw]
    return [entry for entry in parsed if entry.get("account") == account]


def _describe(entries: List[dict]) -> str:
    return "[" + "; ".join(
        f"level={e.get('level')!r} status={e.get('status')!r} "
        f"nick={e.get('nickname')!r} community={e.get('community')!r}"
        for e in entries) + "]"


def check_nc_delete_notice(host: str, port: int, account: str,
                           password: str) -> List[Row]:
    rows: List[Row] = []
    nc = NCClient(host, port, version="6.037")
    rc = RCClient(host, port, version="6.037")
    if not _login(nc, account, password):
        return [("nc_delete_notice", "precondition_failed", "NC login failed")]
    if not _login(rc, account, password):
        nc.disconnect()
        return [("nc_delete_notice", "precondition_failed", "RC login failed")]
    watcher = GameBot("testbot2", host, port)
    try:
        watcher_up = watcher.connect()
        _pump([nc, rc], 0.5)

        def destroy_count(start_nc, start_rc):
            return (_received(nc, PLO.NC_NPCDELETE) - start_nc,
                    _received(rc, PLO.NC_NPCDELETE) - start_rc)

        # NC-initiated: add a database NPC, then delete it from the NC.
        nc.add_npc("qa_live_del", NC_DELETE_ID, "", "qa", LEVEL_A, 30, 30)
        _pump([nc, rc], 0.8)
        if NC_DELETE_ID not in nc.npcs:
            rows.append(("nc_delete_notice_nc_initiated", "precondition_failed",
                         "the NC never saw the database NPC it added"))
        else:
            start = (_received(nc, PLO.NC_NPCDELETE), _received(rc, PLO.NC_NPCDELETE))
            nc.delete_npc(NC_DELETE_ID)
            _pump([nc, rc], 1.0)
            got_nc, got_rc = destroy_count(*start)
            ok = got_nc == 1 and got_rc == 0 and NC_DELETE_ID not in nc.npcs
            rows.append(("nc_delete_notice_nc_initiated", "pass" if ok else "fail",
                         f"NC received {got_nc} PLO_NC_NPCDELETE (want 1), "
                         f"RC received {got_rc} (want 0), "
                         f"NPC still listed={NC_DELETE_ID in nc.npcs}"))

        # Server-initiated: the NPC's own script destroys it.
        nc.add_npc("qa_live_self", SELF_DESTROY_ID, "", "qa", LEVEL_A, 31, 30)
        _pump([nc, rc], 0.8)
        start = (_received(nc, PLO.NC_NPCDELETE), _received(rc, PLO.NC_NPCDELETE))
        if not watcher_up or SELF_DESTROY_ID not in nc.npcs:
            detail = ("game watcher failed to connect" if not watcher_up
                      else "the NC never saw the database NPC it added")
            rows.append(("nc_delete_notice_server_initiated", "precondition_failed", detail))
        else:
            nc.set_npc_script(SELF_DESTROY_ID, "if (created) {\n  destroy;\n}\n")
            _pump([nc, rc], 1.5)
            got_nc, got_rc = destroy_count(*start)
            ok = got_nc == 1 and got_rc == 0
            rows.append(("nc_delete_notice_server_initiated", "pass" if ok else "fail",
                         f"NC received {got_nc} PLO_NC_NPCDELETE (want 1), "
                         f"RC received {got_rc} (want 0)"))
    finally:
        # Idempotent cleanup of the second NPC (a no-op when it destroyed itself).
        nc.delete_npc(SELF_DESTROY_ID)
        _pump([nc], 0.5)
        watcher.disconnect()
        nc.disconnect()
        rc.disconnect()
    return rows


def check_rc_roster_entries(host: str, port: int, account: str,
                            password: str) -> List[Row]:
    rows: List[Row] = []
    rc = RCClient(host, port, version="6.037")
    if not _login(rc, account, password):
        return [("rc_addplayer_login", "precondition_failed", "RC login failed")]
    raw = _record_packets(rc, PLO.ADDPLAYER)
    bot = GameBot(PROBE_ACCOUNT, host, port)
    try:
        if not bot.connect():
            return [("rc_addplayer_login", "precondition_failed",
                     f"game bot {PROBE_ACCOUNT} failed to connect")]
        for _ in range(15):
            _pump([rc, bot.client], 0.2)
        entries = _entries(raw, PROBE_ACCOUNT)
        start_level = bot.level
        complete = all(e.get("level") and "status" in e and e.get("nickname") is not None
                       and e.get("community") == PROBE_ACCOUNT for e in entries)
        ok = (len(entries) == 2 and complete
              and entries[0]["id"] == entries[1]["id"]
              and entries[1]["level"] == start_level)
        rows.append(("rc_addplayer_login", "pass" if ok else "fail",
                     f"{len(entries)} entries (want 2, start level then entered "
                     f"level {start_level!r}): {_describe(entries)}"))

        target = LEVEL_B if start_level != LEVEL_B else LEVEL_A
        before = len(raw)
        bot.warp_to(target, 30, 30)
        for _ in range(10):
            _pump([rc, bot.client], 0.2)
        entries = _entries(raw[before:], PROBE_ACCOUNT)
        ok = len(entries) == 1 and entries[0].get("level") == target
        rows.append(("rc_addplayer_warp", "pass" if ok else "fail",
                     f"{len(entries)} entries after a warp to {target!r} (want 1): "
                     f"{_describe(entries)}"))

        before = len(raw)
        bot.warp_to(target, 20, 20)
        for _ in range(10):
            _pump([rc, bot.client], 0.2)
        entries = _entries(raw[before:], PROBE_ACCOUNT)
        rows.append(("rc_addplayer_same_level_warp", "pass" if not entries else "fail",
                     f"{len(entries)} entries after a warp inside {target!r} "
                     f"(want 0): {_describe(entries)}"))

        if bot.client.gmap_width > 0:
            rows.append(("rc_addplayer_gmap_hop", "skip",
                         "a gmap is loaded but the hop path is not driven by this suite yet"))
        else:
            rows.append(("rc_addplayer_gmap_hop", "skip",
                         "the world has no gmap (serve ../funtimes-pygserver for one)"))
    finally:
        bot.disconnect()
        rc.disconnect()
    return rows


def run_live_checks(kind: str, host: str, port: int, account: str,
                    password: str) -> List[Row]:
    """`kind` is "rc" or "nc". Never raises: an exception is a failed row."""
    check: Callable[..., List[Row]] = (
        check_rc_roster_entries if kind == "rc" else check_nc_delete_notice)
    try:
        return check(host, port, account, password)
    except Exception as exc:  # noqa: BLE001 - a crash is a failed check, not a crash of the run
        return [(f"{kind}_live_checks", "fail", f"{type(exc).__name__}: {exc}")]
