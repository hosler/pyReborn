"""Regression tests for the sticky-swimming bug: GameClient.is_swimming (the
state backing the GS1 `playerswimming` flag and the pygame HUD swim badge)
must recompute on warp/level-change, not just after a manual move().

Live evidence: a bot stranded in water on chicken5.nw still reported
swimming:true after warping into a dry indoor level (chicken_house1.nw).
Root cause: _update_swimming_state() (pyreborn/game/actions.py) was only
called from _move() and from the run() loop's per-frame catch-all - warp
entry points (_use_door_link, _process_pending_warp) never called it
directly, so any caller that does not drive the full run() loop (or checks
state immediately after a warp within the same frame, before the catch-all
runs) sees the previous level's stale value. Fixed by recomputing swimming
state immediately at both warp sites.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.setup import SetupMixin
from pyreborn.tiletypes import TileType, get_tile_type

# Derived from the loaded type table. These used to be tile ids 1 and 2,
# forced to these types by a per-client override layer that no longer exists.
DEEP = next(t for t in range(4096) if get_tile_type(t) == TileType.WATER)
SHALLOW = next(t for t in range(4096)
               if get_tile_type(t) == TileType.NEAR_WATER)

WATER_LEVEL = [DEEP] * 4096
SHALLOW_LEVEL = [SHALLOW] * 4096
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
    return c


def _seed_levels(c):
    c._current_level_name = "chicken5.nw"
    c.levels["chicken5.nw"] = list(WATER_LEVEL)
    c.tiles = c.levels["chicken5.nw"]
    c.player.x, c.player.y = 30.0, 30.0
    c.levels["chicken_house1.nw"] = list(DRY_LEVEL)


class _SwimHarness(CollisionMixin, ActionsMixin):
    """Minimal GameClient stand-in exercising just the swimming-state slice
    of the mixins, without pygame display/asset/sound setup."""

    def __init__(self, client):
        self.client = client
        self.is_swimming = False
        self.current_anim_name = "idle"
        self.is_moving = False
        self.noclip = False
        self.sound_mgr = _NoopSound()
        self.player_anim = _NoopAnim()
        self.npc_handler = _NoopNpcHandler()
        self.world_surface = None
        self.visual_x = self.visual_y = 0.0

    # _use_door_link also drives GS1/NPC bootstrap - not under test here.
    def _load_npc_scripts(self):
        pass

    def _trigger_playerenters(self):
        pass


class _SwimHarnessWithSetup(SetupMixin, CollisionMixin, ActionsMixin):
    """Same as _SwimHarness but mixes in SetupMixin for _process_pending_warp."""

    def __init__(self, client):
        self.client = client
        self.is_swimming = False
        self.current_anim_name = "idle"
        self.is_moving = False
        self.noclip = False
        self.sound_mgr = _NoopSound()
        self.player_anim = _NoopAnim()


class TestSwimmingStateRecompute:
    def test_shallow_water_does_not_trigger_swimming(self):
        c = _fake_connected_client()
        _seed_levels(c)
        c.levels["chicken5.nw"] = list(SHALLOW_LEVEL)
        c.tiles = c.levels["chicken5.nw"]
        h = _SwimHarness(c)

        h._update_swimming_state()

        assert h.is_swimming is False

    def test_baseline_recompute_detects_water(self):
        c = _fake_connected_client()
        _seed_levels(c)
        h = _SwimHarness(c)
        h._update_swimming_state()
        assert h.is_swimming is True

    def test_standing_point_transitions_at_deep_shallow_boundary(self):
        c = _fake_connected_client()
        _seed_levels(c)
        tiles = list(SHALLOW_LEVEL)
        for y in range(64):
            for x in range(32, 64):
                tiles[y * 64 + x] = DEEP
        c.levels["chicken5.nw"] = tiles
        c.tiles = tiles
        h = _SwimHarness(c)

        # The standing point is player x + 1.5, so these positions straddle
        # the boundary between shallow column 31 and deep column 32.
        c.player.x = 30.49
        h._update_swimming_state()
        assert h.is_swimming is False

        c.player.x = 30.5
        h._update_swimming_state()
        assert h.is_swimming is True

        c.player.x = 30.49
        h._update_swimming_state()
        assert h.is_swimming is False

    def test_door_link_warp_clears_swimming_into_dry_level(self):
        c = _fake_connected_client()
        _seed_levels(c)
        h = _SwimHarness(c)
        h._update_swimming_state()
        assert h.is_swimming is True

        h._use_door_link({
            'dest_level': 'chicken_house1.nw', 'dest_x': '24', 'dest_y': '26',
        })
        assert c._current_level_name == "chicken_house1.nw"
        # Recomputed immediately by _use_door_link, not left stale from
        # chicken5.nw until the next run()-loop frame.
        assert h.is_swimming is False

    def test_gs1_pending_warp_clears_swimming_into_dry_level(self):
        c = _fake_connected_client()
        _seed_levels(c)
        h = _SwimHarnessWithSetup(c)
        h._update_swimming_state()
        assert h.is_swimming is True

        h._pending_gs1_warp = ("chicken_house1.nw", 24.0, 26.0)
        h._process_pending_warp()
        assert c._current_level_name == "chicken_house1.nw"
        assert h.is_swimming is False

    def test_warp_into_water_sets_swimming_true(self):
        # Symmetric case: a dry-level door_link warp landing in water.
        c = _fake_connected_client()
        c._current_level_name = "chicken_house1.nw"
        c.levels["chicken_house1.nw"] = list(DRY_LEVEL)
        c.tiles = c.levels["chicken_house1.nw"]
        c.player.x, c.player.y = 24.0, 26.0
        c.levels["chicken5.nw"] = list(WATER_LEVEL)

        h = _SwimHarness(c)
        h._update_swimming_state()
        assert h.is_swimming is False

        h._use_door_link({'dest_level': 'chicken5.nw', 'dest_x': '30', 'dest_y': '30'})
        assert c._current_level_name == "chicken5.nw"
        assert h.is_swimming is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
