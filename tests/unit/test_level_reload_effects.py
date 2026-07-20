"""Level reloads deterministically clear the unified bomb registry."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.game.setup import SetupMixin


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True

    class _Stub:
        connected = True

        def send_packet(self, *a, **k):
            return True

    c._protocol = _Stub()
    c._current_level_name = "level1.nw"
    return c


class _ReloadHarness(SetupMixin):
    """Minimal GameClient stand-in exercising just _reload_level_scripts'
    cache-clearing slice, stubbing out the NPC/tileset machinery it also
    touches (mirrors test_render_cache_invalidation.py's _RenderHarness)."""

    def __init__(self, client):
        self.client = client
        self.gs1 = SimpleNamespace(clear=lambda: None)
        self.tileset_mgr = SimpleNamespace(clear_tiledefs=lambda: None)
        self.npc_handler = SimpleNamespace(update_npcs=lambda: None)
        self.npc_anims = {1: object()}
        self.npc_effects = {1: object()}
        self.npc_chat_texts = {1: object()}
        self.npc_visual = {1: object()}
        self.other_player_visual = {1: object()}
        self.active_projectiles = [{'x': 1.0}]
        self.thrown_objects = [{'x': 1.0}]
        self.active_bombs = [{
            'x': 5.0, 'y': 5.0, 'time': 123.0, 'source': 'remote',
            'power': 1, 'exploded': False,
        }]
        self.active_bomb_explosions = [{'x': 1.0}]
        self.break_effects = [{'x': 1.0}]
        self.visual_x = self.visual_y = 0.0
        self.world_surface = None
        self._gs1_level = None
        self._level_change_pending = None

    def _load_npc_scripts(self):
        pass

    def _trigger_playerenters(self):
        pass


class TestReloadClearsServerBombSeen:
    def test_server_bomb_seen_cleared_on_level_change(self):
        c = _fake_connected_client()
        h = _ReloadHarness(c)

        h._reload_level_scripts("level2.nw")

        # Remote and local bombs now share active_bombs.  There is no separate
        # first-seen map that can be repopulated or cleared out of order.
        assert h.active_bombs == []
        assert h.active_projectiles == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
