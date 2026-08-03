"""Regression tests: level-link warps under scripted movement.

Bomber v6 runs disabledefmovement — the -Test/Movement GS2 weapon writes
player x/y from the VM every tick. That broke door links: _try_link_warp was
only called from _move() in the input path, which input.py skips entirely
while a script drives movement, so walking onto a level link no longer
warped. The -Test/Movement bytecode itself only does wall checks (onwall2/
hitwall) and gani updates, never link warps. The reference client warps
whenever the player's position enters a link rect regardless of what moved
them.

Fix under test: the frame loop calls ActionsMixin._check_scripted_link_warp()
after the script engines tick. On any position change while default_movement
is off it runs the same _try_link_warp path (rising-edge latch, arrival
suppression, _use_door_link invariants) as input-driven movement.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from types import SimpleNamespace

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin

DRY_LEVEL = [0] * 4096


class _NoopSound:
    def play(self, *a, **k):
        pass


class _NoopAnim:
    def set_animation(self, *a, **k):
        pass


class _NoopNpcHandler:
    def update_npcs(self):
        pass


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    # Interior door link in lobby.nw: rect (30,32)-(34,34), well away from
    # level edges so it is never classified as a GMAP edge link.
    c._current_level_name = "lobby.nw"
    c.player.level = "lobby.nw"
    c.levels["lobby.nw"] = list(DRY_LEVEL)
    c.levels["house1.nw"] = list(DRY_LEVEL)
    c.tiles = c.levels["lobby.nw"]
    c.links["lobby.nw"] = [{
        'x': 30, 'y': 32, 'width': 4, 'height': 2,
        'dest_level': 'house1.nw', 'dest_x': '30', 'dest_y': '30',
    }]
    c.player.direction = 2  # facing down: link probe at (x+1.5, y+3.5)
    return c


class _Harness(CollisionMixin, ActionsMixin):
    """Minimal GameClient stand-in for the scripted-movement link probe."""

    def __init__(self, client, default_movement=False):
        self.client = client
        self.gs1 = SimpleNamespace(default_movement=default_movement)
        self.is_swimming = False
        self.current_anim_name = "idle"
        self.is_moving = False
        self.noclip = False
        self.sound_mgr = _NoopSound()
        self.player_anim = _NoopAnim()
        self.npc_handler = _NoopNpcHandler()
        self.world_surface = None
        self.visual_x = self.visual_y = 0.0
        self._was_on_link = False
        self._link_arrival = None
        self._scripted_link_pos = None

    # _use_door_link also drives GS1/NPC bootstrap - not under test here.
    def _load_npc_scripts(self):
        pass

    def _trigger_playerenters(self):
        pass


class TestScriptedMovementLinkWarp:
    def test_vm_position_write_onto_link_warps(self):
        c = _fake_connected_client()
        h = _Harness(c)

        # Off the link: probe runs (position changed from None) but no warp.
        c.player.x, c.player.y = 30.0, 20.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"

        # Script tick writes the player onto the link rect: must warp through
        # the normal door path.
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is True
        assert c._current_level_name == "house1.nw"
        assert (c.x, c.y) == (30.0, 30.0)

    def test_no_refire_at_warp_arrival(self):
        c = _fake_connected_client()
        h = _Harness(c)
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is True
        assert c._current_level_name == "house1.nw"

        # Same frame-loop probe again at the arrival point: no bounce-back
        # (position stamp + rising-edge latch/arrival suppression).
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "house1.nw"

    def test_unchanged_position_short_circuits(self):
        c = _fake_connected_client()
        h = _Harness(c)
        c.player.x, c.player.y = 30.0, 20.0
        assert h._check_scripted_link_warp() is False

        calls = []
        original = c.check_link_collision
        c.check_link_collision = lambda: calls.append(1) or original()
        assert h._check_scripted_link_warp() is False  # position unchanged
        assert calls == []

    def test_default_movement_leaves_probe_inert(self):
        c = _fake_connected_client()
        h = _Harness(c, default_movement=True)
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"

    def test_transition_in_flight_defers_probe(self):
        c = _fake_connected_client()
        h = _Harness(c)
        c._local_level_transition = "scroll"
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"
