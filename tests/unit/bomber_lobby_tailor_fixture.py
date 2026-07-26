"""Loader for tests/fixtures/bomber_lobby_tailor — classic Bomber's tailor
(the NPC "Jonah" plus the `-tailor` weapon he calls) replayed OFFLINE.

Both scripts are verbatim third-party content: the NPC is
Preagonal/graal-bomber-gs1/world/bomblobby.nw:489-512 (the NPC declared at
`NPC - 16 12`, i.e. level position 16,12) and the weapon is the SCRIPT section
of Preagonal/graal-bomber-gs1/weapons/weapon%045tailor.txt. Together they are
the only content we have that exercises `callweapon` at all, and the tailor
also needs the client-version builtin, the character-NPC touch box and the
weapon-side appearance message codes — the bomber is on a live third-party
server, so nothing here may touch the network.

Manifest notes:

* the NPC's image is "#c#", which is what the wire carries once the server has
  run its `showcharacter` (GServer-v2 GS1Commands.cpp:3049 sets the IMAGE prop;
  scripting-gs1-commands.md lists showcharacter as gs2emu-serverside). The
  level file itself declares no image ("-");
* `weapons` is an ORDERING, not a capture: the live session had `-tailor` at
  index 3 of `weaponscount`, which is the index the NPC's `#w(i)` scan finds
  and hands to `callweapon`. Which weapons occupy 0-2 does not matter to
  anything here;
* the NPC id is synthetic (1): this is extracted from the level file, not
  captured off the wire, so there is no server-allocated id to preserve.
"""
from __future__ import annotations

import json
import os

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'fixtures', 'bomber_lobby_tailor')


def _require_fixture() -> None:
    """Skip instead of failing when the captured data is absent.

    The scripts in this fixture are byte-identical third-party server content,
    so they are deliberately NOT committed (see .gitignore). Re-capture them
    from a live session to run the Jonah tailor GUI tests.
    """
    if not os.path.isdir(FIXTURE_DIR):
        import pytest
        pytest.skip("bomber_lobby_tailor fixture data not present (uncommitted:"
                    " third-party server scripts)", allow_module_level=True)


_require_fixture()

#: fixture NPC id of the tailor NPC (Jonah — the one with the touch handler)
JONAH_ID = 1


def load_capture() -> dict:
    """The manifest: level, NPC image/position, weapon list, player look."""
    with open(os.path.join(FIXTURE_DIR, 'capture.json'), encoding='utf-8') as f:
        return json.load(f)


def load_npc_script(npc_id: int = JONAH_ID) -> str:
    """The NPC's script, exactly as the level file holds it."""
    with open(os.path.join(FIXTURE_DIR, 'npc_%d.gs1' % npc_id),
              encoding='utf-8') as f:
        return f.read()


def load_weapon_script() -> str:
    """The `-tailor` weapon's script, exactly as the weapon file holds it."""
    with open(os.path.join(FIXTURE_DIR, 'weapon_tailor.gs1'),
              encoding='utf-8') as f:
        return f.read()
