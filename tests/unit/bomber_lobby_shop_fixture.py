"""Loader for tests/fixtures/bomber_lobby_shop — classic Bomber's shop
("Dryden's Wares") replayed OFFLINE.

The fixture is the two NPC scripts the shop is made of, extracted verbatim from
the third-party level file (Preagonal/graal-bomber-gs1/world/bomblobby.nw): the
counter the player touches (level position 45,35 — `setshape 1,96,16`) and the
item catalogue it reaches with `callnpc testnpc(56,26),GrabItemList,...` (level
position 56,26). Those two NPCs are the only content we have that exercises
`testnpc` and the `mousescreenx`/`mousex` screen<->world conversion together —
and the shop is on a live third-party server, so nothing here may touch the
network.

The NPC ids are synthetic (1, 2 in level order): unlike bomber_room0 this is
extracted from the level file, not captured off the wire, so there are no
server-allocated ids to preserve. Everything the scripts read is verbatim.
"""
from __future__ import annotations

import json
import os

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'fixtures', 'bomber_lobby_shop')


def _require_fixture() -> None:
    """Skip instead of failing when the captured data is absent.

    The scripts in this fixture are byte-identical third-party server content,
    so they are deliberately NOT committed (see .gitignore). Re-capture them
    from a live session to run the Dryden's Wares shop tests.
    """
    if not os.path.isdir(FIXTURE_DIR):
        import pytest
        pytest.skip("bomber_lobby_shop fixture data not present (uncommitted:"
                    " third-party server scripts)", allow_module_level=True)


_require_fixture()

#: fixture NPC id of the shop counter (the NPC with the touch handler)
COUNTER_ID = 1
#: fixture NPC id of the item catalogue (`testnpc(56,26)`'s target)
CATALOGUE_ID = 2


def load_capture() -> dict:
    """The manifest: level name, player position, per-NPC image + position."""
    with open(os.path.join(FIXTURE_DIR, 'capture.json'), encoding='utf-8') as f:
        return json.load(f)


def load_script(npc_id: int) -> str:
    """One NPC's script, exactly as the level file holds it."""
    with open(os.path.join(FIXTURE_DIR, 'npc_%d.gs1' % npc_id),
              encoding='utf-8') as f:
        return f.read()


def load_scripts() -> dict:
    """{npc id -> script} for both shop NPCs, in level order."""
    return {int(nid): load_script(int(nid))
            for nid in sorted(int(k) for k in load_capture()['npcs'])}
