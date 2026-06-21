"""
exercise_nc - A battery of NC (NPC Control) actions for coverage.

Drives an NCClient through the full NC PLI surface so every builder is sent over
the wire (and validated against the server's received view) and every NC reply
the server can produce without a running npc-server is parsed:

  - weapon list / weapon get / weapon add+delete (a throwaway weapon)
  - level list / local-npcs dump
  - the npc + class management commands (best-effort: with no npc-server these
    are server-side no-ops, but the PLI still round-trips for builder coverage)

Every step is best-effort: failures become notes rather than aborting. Mutating
ops are confined to a clearly-named throwaway weapon/class that this module
creates and deletes itself.
"""

from __future__ import annotations

import time
from typing import List

from pyreborn.nc_client import NCClient

THROWAWAY_WEAPON = "qa_nc_throwaway"
THROWAWAY_CLASS = "qa_nc_class"
# A database-npc id far above anything real so getNPC() resolves to null and the
# npc-management handlers are safe no-ops on a server with no npc-server.
FAKE_NPC_ID = 1900000
# A throwaway database npc this battery creates and deletes itself (>= 10000 is
# the database id floor; well clear of the seeded Control-NPC at 10000).
THROWAWAY_NPC_ID = 55000
# Seeded fixtures present when the server runs with serverside=true (see the
# npcs/ + scripts/ folders): a CONTROL npc and a script class.
SEEDED_NPC_ID = 10000
SEEDED_CLASS = "qaclass"
QA_LEVEL = "onlinestartlocal.nw"


def _step(notes: List[str], name: str, fn, verbose: bool):
    try:
        if verbose:
            print(f"  [nc] {name}")
        fn()
    except Exception as e:  # noqa: BLE001 - best-effort battery
        notes.append(f"{name}: {type(e).__name__}: {e}")


def _pump(nc: NCClient, seconds: float = 0.4):
    deadline = time.time() + seconds
    while time.time() < deadline:
        nc.update(timeout=0.1)
        time.sleep(0.02)


def run_nc_battery(nc: NCClient, verbose: bool = True) -> List[str]:
    """Drive `nc` through the NC surface. Returns failure notes."""
    notes: List[str] = []

    # --- read-only queries (work without an npc-server) -------------------
    _step(notes, "weapon_list", lambda: (nc.get_weapon_list(), _pump(nc)), verbose)
    _step(notes, "level_list", lambda: (nc.get_level_list(), _pump(nc)), verbose)
    _step(notes, "local_npcs",
          lambda: (nc.get_local_npcs(QA_LEVEL), _pump(nc)), verbose)
    _step(notes, "npc_ping", lambda: (nc.ping_npcs(), _pump(nc)), verbose)

    # --- weapon lifecycle: add -> get -> list -> delete -------------------
    _step(notes, "weapon_lifecycle",
          lambda: _weapon_lifecycle(nc, notes, verbose), verbose)

    # --- npc reads against the seeded database NPC (-> 157/160/161) --------
    # These elicit replies only with a running npc-server; against a no-npc
    # server they round-trip as PLI for builder coverage and reply with nothing.
    _step(notes, "npc_get",
          lambda: (nc.get_npc(SEEDED_NPC_ID), _pump(nc, 0.6)), verbose)
    _step(notes, "npc_script_get",
          lambda: (nc.get_npc_script(SEEDED_NPC_ID), _pump(nc, 0.6)), verbose)
    _step(notes, "npc_flags_get",
          lambda: (nc.get_npc_flags(SEEDED_NPC_ID), _pump(nc, 0.6)), verbose)

    # --- npc set/warp/reset on the seeded NPC (state-only, no destructive) -
    _step(notes, "npc_flags_set",
          lambda: (nc.set_npc_flags(SEEDED_NPC_ID, "qa=1"), _pump(nc)), verbose)
    _step(notes, "npc_warp",
          lambda: (nc.warp_npc(SEEDED_NPC_ID, 30, 30, QA_LEVEL), _pump(nc)), verbose)
    _step(notes, "npc_reset",
          lambda: (nc.reset_npc(SEEDED_NPC_ID), _pump(nc)), verbose)
    # Fake-id read too, so the no-npc-server path (null getNPC) is also covered.
    _step(notes, "npc_get_fake",
          lambda: (nc.get_npc(FAKE_NPC_ID), _pump(nc)), verbose)

    # --- throwaway npc lifecycle: add -> get -> delete (-> 158/159) --------
    _step(notes, "npc_lifecycle",
          lambda: _npc_lifecycle(nc, notes, verbose), verbose)

    # --- class management: edit seeded (-> 162) + throwaway add/del (163/188)
    _step(notes, "class_get",
          lambda: (nc.edit_class(SEEDED_CLASS), _pump(nc, 0.6)), verbose)
    _step(notes, "class_lifecycle",
          lambda: _class_lifecycle(nc, notes, verbose), verbose)

    return notes


def _npc_lifecycle(nc: NCClient, notes: List[str], verbose: bool):
    """Create a throwaway database NPC, set its script, then delete it.

    Requires an npc-server (NPCADD is guarded by hasNPCServer). Without one this
    is a no-op; the PLI still round-trips for builder coverage.
    """
    try:
        nc.add_npc("qa_npc", THROWAWAY_NPC_ID, "", "qa", QA_LEVEL, 30, 30)
        _pump(nc, 0.8)
        nc.set_npc_script(THROWAWAY_NPC_ID, "//qa throwaway\n")
        _pump(nc, 0.6)
        nc.get_npc_script(THROWAWAY_NPC_ID)
        _pump(nc, 0.6)
    finally:
        nc.delete_npc(THROWAWAY_NPC_ID)
        _pump(nc, 0.8)


def _weapon_lifecycle(nc: NCClient, notes: List[str], verbose: bool):
    """Add a throwaway weapon, fetch it, then delete it. Cleans up on failure."""
    try:
        nc.add_weapon(THROWAWAY_WEAPON, "qa.png",
                      "//qa weapon\nfunction onCreated(){}"); _pump(nc, 0.6)
        nc.get_weapon(THROWAWAY_WEAPON); _pump(nc, 0.6)
        if not nc.last_weapon or nc.last_weapon.get("name") != THROWAWAY_WEAPON:
            notes.append("nc weapon_lifecycle: weapon_get did not return the "
                         "throwaway weapon")
    finally:
        nc.delete_weapon(THROWAWAY_WEAPON)
        _pump(nc, 0.6)


def _class_lifecycle(nc: NCClient, notes: List[str], verbose: bool):
    """Exercise classedit/add/delete. No-ops without an npc-server."""
    nc.edit_class(THROWAWAY_CLASS); _pump(nc)
    nc.add_class(THROWAWAY_CLASS, "//qa class"); _pump(nc, 0.6)
    nc.delete_class(THROWAWAY_CLASS); _pump(nc, 0.6)
