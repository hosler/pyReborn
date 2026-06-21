"""
exercise_rc - A battery of RC (Remote Control) admin actions for coverage.

Drives the RCClient through the read-mostly admin surface (flags, options,
accounts, rights, comments, bans, file browser) plus a few safe mutating ops
on a clearly-named throwaway account that it creates and deletes itself.

Like the base battery, every step is best-effort: failures are recorded as
notes rather than aborting. Destructive operations are confined to the
throwaway account and a peer bot this module owns - it never bans/kicks the
suite accounts.
"""

from __future__ import annotations

import time
from typing import List

from .game_bot import GameBot
from pyreborn.rc_client import RCClient

THROWAWAY = "qa_throwaway"


def _step(notes: List[str], name: str, fn, verbose: bool):
    try:
        if verbose:
            print(f"  [rc] {name}")
        fn()
    except Exception as e:  # noqa: BLE001 - best-effort battery
        notes.append(f"{name}: {type(e).__name__}: {e}")


def _pump(rc: RCClient, seconds: float = 0.4):
    deadline = time.time() + seconds
    while time.time() < deadline:
        rc.update(timeout=0.1)
        time.sleep(0.02)


def run_rc_battery(rc: RCClient, host: str, port: int,
                   verbose: bool = True) -> List[str]:
    """Drive `rc` through the RC admin surface. Returns failure notes."""
    notes: List[str] = []

    # --- chat / broadcast -------------------------------------------------
    _step(notes, "rc_say", lambda: (rc.rc_say("coverage RC run"), _pump(rc)), verbose)
    _step(notes, "admin_message",
          lambda: (rc.admin_message("coverage admin msg"), _pump(rc)), verbose)

    # --- server-wide reads ------------------------------------------------
    _step(notes, "server_flags", lambda: (rc.get_server_flags(), _pump(rc)), verbose)
    _step(notes, "server_options", lambda: (rc.get_server_options(), _pump(rc)), verbose)
    _step(notes, "folder_config", lambda: (rc.get_folder_config(), _pump(rc)), verbose)
    _step(notes, "account_list", lambda: (rc.get_account_list(), _pump(rc)), verbose)
    _step(notes, "update_levels", lambda: (rc.update_levels(), _pump(rc)), verbose)

    # --- account / player reads (target an existing suite account) --------
    _step(notes, "account_get", lambda: (rc.get_account("testbot2"), _pump(rc)), verbose)
    _step(notes, "player_rights",
          lambda: (rc.get_player_rights("testbot1"), _pump(rc)), verbose)
    _step(notes, "player_comments",
          lambda: (rc.get_player_comments("testbot1"), _pump(rc)), verbose)
    _step(notes, "ban_status",
          lambda: (rc.get_ban_status("testbot2"), _pump(rc)), verbose)

    # --- file browser -----------------------------------------------------
    def _filebrowser():
        rc.filebrowser_start(); _pump(rc)
        rc.filebrowser_cd("world"); _pump(rc)
        rc.filebrowser_end(); _pump(rc)
    _step(notes, "filebrowser", _filebrowser, verbose)

    # --- online-player ops: spawn a peer so props/warp have a target ------
    _step(notes, "online_player_ops",
          lambda: _online_player_ops(rc, host, port, notes, verbose), verbose)

    # --- throwaway account lifecycle (create -> ban -> unban -> delete) ---
    _step(notes, "account_lifecycle",
          lambda: _account_lifecycle(rc, notes, verbose), verbose)

    return notes


def _online_player_ops(rc: RCClient, host: str, port: int,
                       notes: List[str], verbose: bool):
    """RC queries/warps an online peer (PLAYERPROPSGET / WARPPLAYER)."""
    peer = GameBot("testbot2", host, port)
    if not peer.connect():
        notes.append("rc online_player_ops: peer failed to connect")
        return
    try:
        _pump(rc, 0.5)
        # Props by account name (resolves an online player server-side).
        rc.get_player_props_by_name("testbot2"); _pump(rc)
        # Warp the peer somewhere harmless (best-effort; id may be unknown).
        pid = rc.get_player_id_by_account("testbot2")
        if pid:
            rc.warp_player(pid, 30, 30, "onlinestartlocal.nw"); _pump(rc)
        else:
            notes.append("rc online_player_ops: peer id unresolved (warp skipped)")
    finally:
        peer.disconnect()


def _account_lifecycle(rc: RCClient, notes: List[str], verbose: bool):
    """Create, ban/unban, then delete a throwaway account.

    Confined to THROWAWAY so the suite accounts are never touched. Cleans up
    even if a middle step fails.
    """
    try:
        rc.create_account(THROWAWAY, "qa_pass_123", "qa@example.invalid")
        _pump(rc, 0.6)
        rc.get_account(THROWAWAY); _pump(rc)
        rc.ban_player(THROWAWAY, True, "qa coverage ban"); _pump(rc)
        rc.get_ban_status(THROWAWAY); _pump(rc)
        rc.ban_player(THROWAWAY, False); _pump(rc)
        rc.set_player_comments(THROWAWAY, "qa coverage comment"); _pump(rc)
        rc.get_player_comments(THROWAWAY); _pump(rc)
    finally:
        rc.delete_account(THROWAWAY)
        _pump(rc, 0.6)
