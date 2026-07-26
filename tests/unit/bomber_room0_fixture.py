"""Loader for tests/fixtures/bomber_room0 — a live capture of classic Bomber's
`room0.nw` (the player-base room), replayed OFFLINE.

The fixture is the 15 NPC scripts the server shipped, plus the flag set the
client held at that moment. It exists because room0's furniture NPCs are the
only content we have that exercises the whole GS1 client surface at once
(catalog build, `npcs[i]`/`npcscount` iteration, `callnpc`, bare `save[i]`) —
and because that room is a real, persistent, third-party player base whose
furniture the scripts can DELETE. Nothing here may touch the network: the
fixture is the substitute for connecting.

Scrubbed vs the raw capture: account handles were replaced with equal-length
placeholders and the capturing machine's IP plus the server's third-party
leaderboards were dropped (the room strings are parsed by byte offset, so
lengths had to be preserved). The NPC scripts are byte-identical server
content — they are the oracle.
"""
from __future__ import annotations

import json
import os

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'fixtures', 'bomber_room0')


def _require_fixture() -> None:
    """Skip instead of failing when the captured data is absent.

    The scripts in this fixture are byte-identical third-party server content,
    so they are deliberately NOT committed (see .gitignore). Re-capture them
    from a live session to run the room0 furniture/arcade tests.
    """
    if not os.path.isdir(FIXTURE_DIR):
        import pytest
        pytest.skip("bomber_room0 fixture data not present (uncommitted:"
                    " third-party server scripts)", allow_module_level=True)


_require_fixture()


def load_capture() -> dict:
    """The capture manifest: level name, player position, per-NPC position."""
    with open(os.path.join(FIXTURE_DIR, 'capture.json'), encoding='utf-8') as f:
        return json.load(f)


def load_flags() -> dict:
    """The client's flag set at capture time, wire-named (`server.`/`client.`
    prefixes intact) so it can be fed through ClientGS1.recv_flag."""
    with open(os.path.join(FIXTURE_DIR, 'flags.json'), encoding='utf-8') as f:
        return json.load(f)


def load_script(npc_id: int) -> str:
    """One NPC's script, exactly as the server sent it (0xa7 line separators
    intact — the GS1 lexer translates them)."""
    with open(os.path.join(FIXTURE_DIR, 'npc_%d.gs1' % npc_id),
              encoding='utf-8') as f:
        return f.read()


def load_scripts() -> dict:
    """{npc id -> script} for every captured NPC, in level order."""
    return {int(nid): load_script(int(nid)) for nid in sorted(
        (int(k) for k in load_capture()['npcs']))}
