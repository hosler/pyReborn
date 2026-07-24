"""Regression tests for NPC touch under scripted movement (disabledefmovement).

Bomber v6 moves the player from a weapon script (default_movement OFF), which
made input.py return before _move() — the only caller of
npc_handler.process_movement — so playertouchsme/onPlayerTouchsMe never fired
and the queue counter (NPC 10376, setshape2 14x1) could not be joined.

The fix: input.py's scripted-movement branch calls
ActionsMixin._scripted_movement_touch, which runs the same touch dispatch off
the HELD direction keys at the player's current script-driven position.

Covered here, no live server needed:
- the probe dispatches process_movement with the pressed direction (and does
  nothing with no direction held);
- the NPCHandler gate accepts a GS2-only NPC (no GS1 script text) that
  declares onPlayerTouchsMe, respects the setshape2 14x1 per-tile flags, fires
  once per overlap, and re-fires only after the player leaves the shape
  (handlePlayer TOGGLES queue membership — re-fire without walking away would
  bounce the player straight back out of the queue).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pygame.locals import K_UP, K_DOWN, K_LEFT, K_RIGHT

from pyreborn.game.actions import ActionsMixin
from pyreborn.npc_handler import NPCHandler, NPCShape


class FakeKeys:
    """pygame.key.get_pressed() stand-in: index with K_* constants."""

    def __init__(self, *held):
        self._held = set(held)

    def __getitem__(self, key):
        return key in self._held


class _SpyHandler:
    def __init__(self):
        self.calls = []
        self.refreshes = 0

    def update_npcs(self):
        self.refreshes += 1

    def process_movement(self, x, y, direction):
        self.calls.append((x, y, direction))


class _StubClient:
    def __init__(self, x=25.0, y=20.5):
        self.x = x
        self.y = y
        self.npcs = {}


class _Harness(ActionsMixin):
    """Minimal object carrying just what _scripted_movement_touch reads."""

    def __init__(self):
        self.client = _StubClient()
        self.npc_handler = _SpyHandler()


def test_probe_dispatches_pressed_direction():
    h = _Harness()
    h._scripted_movement_touch(FakeKeys(K_UP))
    assert h.npc_handler.calls == [(25.0, 20.5, 0)]
    # The probe must re-snapshot shapes first: GS2 NPCs record setshape2
    # after the level-entry update_npcs() snapshot (see method docstring).
    assert h.npc_handler.refreshes == 1

    h.npc_handler.calls.clear()
    h._scripted_movement_touch(FakeKeys(K_RIGHT))
    assert h.npc_handler.calls == [(25.0, 20.5, 3)]


def test_probe_noop_without_direction_or_handler():
    h = _Harness()
    h._scripted_movement_touch(FakeKeys())
    assert h.npc_handler.calls == []

    # A missing handler (early init) must not raise.
    h.npc_handler = None
    h._scripted_movement_touch(FakeKeys(K_DOWN, K_LEFT))


def _counter_handler(has_event=True):
    """NPCHandler with Bomber v6's queue-counter geometry: GS2-only NPC 10376
    at (25,18), setshape2 14,1,{22,22,0,0,0,0,22,22,0,0,0,0,22,22}."""
    client = _StubClient()
    handler = NPCHandler(client)
    client.npcs[10376] = {'id': 10376, 'x': 25.0, 'y': 18.0, 'script': ''}
    handler.npc_scripts[10376] = ''  # GS2 NPC: no GS1 script text at all
    handler.npc_shapes[10376] = NPCShape(
        x=25.0, y=18.0, width=14, height=1,
        solid_flags=[22, 22, 0, 0, 0, 0, 22, 22, 0, 0, 0, 0, 22, 22])

    class _GS2Stub:
        def npc_has_event(self, npc_id, event):
            return has_event and npc_id == 10376 and event == "onPlayerTouchsMe"

    handler.gs2 = _GS2Stub()
    fired = []
    handler.on_playertouchsme = lambda npc_id, npc_data: fired.append(npc_id)
    return handler, fired


def test_gs2_only_counter_touch_fires_and_dedupes():
    handler, fired = _counter_handler()

    # Pushing UP with the up-probe row (player y+1) inside the shape row and
    # the probe columns (x+1, x+2) on solid flag cells 0/1.
    handler.process_movement(24.5, 17.2, 0)
    assert fired == [10376]

    # Held key repeats the probe every frame — must NOT re-fire while the
    # overlap lasts (handlePlayer toggles queue membership).
    handler.process_movement(24.5, 17.2, 0)
    assert fired == [10376]

    # Walk away (probe leaves the shape), then push back in: re-fires.
    handler.process_movement(24.5, 20.5, 0)
    handler.process_movement(24.5, 17.2, 0)
    assert fired == [10376, 10376]


def test_flush_contact_touches():
    """Scripted movement (classic box top = y+1) rests the player pressed
    dead against the counter at y=18.0: the up probe lands at y+1 = 19.0 —
    exactly the shape's exclusive bottom edge. The 1px facing extension in
    check_touch must make flush contact register (real-client touchtestd
    extends beyond the box)."""
    handler, fired = _counter_handler()
    handler.process_movement(24.8, 18.0, 0)
    assert fired == [10376]

    # One half-step farther away must NOT fire.
    handler2, fired2 = _counter_handler()
    handler2.process_movement(24.8, 18.5, 0)
    assert fired2 == []


def test_setshape2_flag_gaps_are_not_touchable():
    handler, fired = _counter_handler()
    # Columns 2-5 of the counter are flag-0 (seat gaps): probes at x+1/x+2 =
    # columns 3.5/4.5 must not touch.
    handler.process_movement(27.5, 17.2, 0)
    assert fired == []


def test_gs2_npc_without_touch_event_does_not_fire():
    handler, fired = _counter_handler(has_event=False)
    handler.process_movement(24.5, 17.2, 0)
    assert fired == []


def test_reload_preserves_gs2_npc_shapes():
    """gs1.clear() during _reload_level_scripts must not permanently destroy
    shapes recorded by GS2 NPCs' onPlayerEnters (pump_level_events fires
    BEFORE the reload and never re-fires for the same level visit) — the
    live-lobby failure mode: no counter touch AND walking through it."""
    import types
    from pyreborn.gs1_client import ClientGS1
    from pyreborn.game.setup import SetupMixin

    flags = [22, 22, 0, 0, 0, 0, 22, 22, 0, 0, 0, 0, 22, 22]

    client = types.SimpleNamespace(
        npcs={10376: {'id': 10376, 'x': 25.0, 'y': 18.0, 'script': ''}},
        x=25.0, y=25.0, _current_level_name='bomblobby.nw',
        player=types.SimpleNamespace(direction=0, hearts=3, x=25.0, y=25.0),
        global_flags={})
    gs1 = ClientGS1(client)
    # GS2 NPC 10376's onPlayerEnters ran setshape2 (shared shape store +
    # onwall2 blocking cells); a GS1-only NPC 42 also has a shape but no VM.
    gs1.shapes[10376] = (14, 1, list(flags))
    gs1._update_shape_blocks(10376, client.npcs[10376], 14, 1, flags)
    gs1.shapes[42] = (2, 2, [22, 22, 22, 22])

    class _Host(SetupMixin):
        pass

    host = _Host()
    host.client = client
    host.gs1 = gs1
    host.gs2 = types.SimpleNamespace(vms={'npc': {10376: object()}})

    keep = host._snapshot_gs2_npc_shapes()
    assert keep == {10376: (14, 1, flags)}
    assert 42 not in keep  # GS1 NPC re-records via _trigger_playerenters

    gs1.clear()
    assert gs1.shapes == {} and not gs1._shape_blocks

    host._restore_gs2_npc_shapes(keep)
    assert gs1.shapes == {10376: (14, 1, flags)}
    # solid columns 0,1 / 6,7 / 12,13 anchored at (25,18) block onwall2 again
    assert (25, 18) in gs1._shape_blocks and (26, 18) in gs1._shape_blocks
    assert (27, 18) not in gs1._shape_blocks
