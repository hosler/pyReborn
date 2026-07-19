"""Regression tests for client-side GS1 gaps vs GServer-v2's docs
(scripting-gs1-events.md, scripting-gs1-flags.md, npcserver.md "Emulating
sword hits"):

1. `hitobjects power,x,y` command (previously silently ignored) hitting local
   NPCs/baddies, respecting hidden/dontblock NPCs.
2. `keypressed` event + the keydown() control-function indices it relies on.
3. `washit` reacting to both the sword-hit path and `hitobjects`.
4. `#L` resolving to the SOURCE NPC's level, not the player's.
5. The `visible` flag being readable (not just written by hide/show/destroy).
6. New builtin flags backed by real client state: carrying/carriesbush/
   carriesstone/carriesvase, playerswimming, playeronhorse, weaponsenabled,
   playerfreezetime.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.packets import PacketID, build_baddy_hurt
from pyreborn.tiletypes import TILE_TYPES, TileType


class _SentRecorder:
    """Stub protocol capturing send_packet calls (Client.connected proxies
    to this object's .connected)."""

    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    return c


def _this(gs1, key):
    """The `this.` scope dict for a loaded script/weapon prog."""
    return gs1._progs[key]["scopes"]["this"]


class TestHitObjects:
    def test_hits_visible_npc_and_fires_washit(self):
        c = Client("localhost", 14900)
        c.npcs[1] = {'x': 10.0, 'y': 10.0}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (washit) { hide; }", npc_id=1, x=10, y=10)
        gs1.hit_objects_at(10, 10, power=1.0)
        assert c.npcs[1].get('visible') is False

    def test_ignores_hidden_npc(self):
        c = Client("localhost", 14900)
        c.npcs[1] = {'x': 10.0, 'y': 10.0, 'visible': False}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (washit) { this.hit = 1; }", npc_id=1, x=10, y=10)
        gs1.hit_objects_at(10, 10)
        assert 'hit' not in _this(gs1, 'npc_1')

    def test_ignores_dontblock_npc(self):
        c = Client("localhost", 14900)
        c.npcs[1] = {'x': 10.0, 'y': 10.0, 'dontblock': True}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (washit) { this.hit = 1; }", npc_id=1, x=10, y=10)
        gs1.hit_objects_at(10, 10)
        assert 'hit' not in _this(gs1, 'npc_1')

    def test_ignores_npc_out_of_range(self):
        c = Client("localhost", 14900)
        c.npcs[1] = {'x': 10.0, 'y': 10.0}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (washit) { this.hit = 1; }", npc_id=1, x=10, y=10)
        gs1.hit_objects_at(20, 20)
        assert 'hit' not in _this(gs1, 'npc_1')

    def test_hurts_baddy_in_range(self):
        c = _fake_connected_client()
        c.baddies[3] = {'x': 10.0, 'y': 10.0}
        gs1 = ClientGS1(c)
        gs1.hit_objects_at(10, 10, power=1.5)
        assert (int(PacketID.PLI_BADDYHURT), build_baddy_hurt(3, 1.5)) in c._protocol.sent

    def test_command_dispatched_from_script(self):
        # End-to-end: a weapon script calling `hitobjects` (npcserver.md's
        # sword-emulation pattern) must reach hit_objects_at via _dispatch.
        c = Client("localhost", 14900)
        c.npcs[9] = {'x': 5.0, 'y': 5.0}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_9', "if (washit) { hide; }", npc_id=9, x=5, y=5)
        gs1.load_weapon('swordemu', "hitobjects 1,5,5;")
        gs1.trigger_event('created', name='weapon_swordemu')
        assert c.npcs[9].get('visible') is False


class TestKeypressed:
    def test_fires_with_p_params_and_keydown_state(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script(
            'npc_1',
            "if (keypressed) { this.code = #p(0); setstring this.ch,#p(1); "
            "this.down5 = keydown(5); this.down0 = keydown(0); }",
            npc_id=1)
        gs1.keys_dir = {5}   # sword (S) held this frame
        gs1.fire_keypress(83, 's')
        this = _this(gs1, 'npc_1')
        assert this['code'] == 83.0
        assert this['ch'] == 's'
        assert this['down5'] == 1.0
        assert this['down0'] == 0.0

    def test_p_params_cleared_after_event(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.fire_keypress(65, 'a')
        assert gs1._proj_params == []


class TestVisibleFlag:
    def test_defaults_true_and_tracks_hide(self):
        c = Client("localhost", 14900)
        c.npcs[1] = {'x': 0.0, 'y': 0.0}
        gs1 = ClientGS1(c)
        gs1.load_script(
            'npc_1',
            "if (created) { this.before = visible; hide; this.after = visible; }",
            npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        this = _this(gs1, 'npc_1')
        assert this['before'] == 1.0
        assert this['after'] == 0.0


class TestLevelMessageCode:
    def test_uses_npc_level_not_player_level(self):
        c = Client("localhost", 14900)
        c.player.level = "playerlevel.nw"
        c.npcs[1] = {'x': 0.0, 'y': 0.0, '_level': 'npclevel.nw'}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { setstring this.lvl,#L; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['lvl'] == 'npclevel.nw'

    def test_falls_back_to_player_level_without_npc_level(self):
        c = Client("localhost", 14900)
        c.player.level = "playerlevel.nw"
        c.npcs[1] = {'x': 0.0, 'y': 0.0}
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { setstring this.lvl,#L; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['lvl'] == 'playerlevel.nw'


class TestNewBuiltinFlags:
    def test_carrying_and_carriesbush(self):
        c = Client("localhost", 14900)
        c.player.pickup_object("bush", (1, 2, 3, 4), (5, 5))
        gs1 = ClientGS1(c)
        gs1.load_script(
            'npc_1',
            "if (created) { this.carrying = carrying; this.bush = carriesbush; "
            "this.stone = carriesstone; this.vase = carriesvase; }",
            npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        this = _this(gs1, 'npc_1')
        assert this['carrying'] == 1.0
        assert this['bush'] == 1.0
        assert this['stone'] == 0.0
        assert this['vase'] == 0.0

    def test_carriesstone_for_rock_and_carriesvase_for_pot(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script(
            'npc_1',
            "if (created) { this.stone = carriesstone; this.vase = carriesvase; }",
            npc_id=1)

        c.player.pickup_object("rock", (1, 2, 3, 4), (5, 5))
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['stone'] == 1.0
        assert _this(gs1, 'npc_1')['vase'] == 0.0

        c.player.carried_object_type = "pot"
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['stone'] == 0.0
        assert _this(gs1, 'npc_1')['vase'] == 1.0

    def test_not_carrying_is_false(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { this.c = carrying; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['c'] == 0.0

    def test_playeronhorse(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { this.h = playeronhorse; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['h'] == 0.0

        c.player.horse_image = "horse.png"
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['h'] == 1.0

    def test_playerswimming(self):
        water_id = next(i for i, t in enumerate(TILE_TYPES) if t == TileType.WATER)
        dry_id = next(i for i, t in enumerate(TILE_TYPES) if t == TileType.NONBLOCK)
        c = Client("localhost", 14900)
        c.tiles = [dry_id] * 4096
        c.player.x, c.player.y = 5.0, 5.0
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { this.s = playerswimming; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['s'] == 0.0

        c.tiles[5 * 64 + 5] = water_id
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['s'] == 1.0

    def test_weaponsenabled_defaults_true_and_toggles(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        assert gs1.weapons_enabled is True
        gs1.load_script('npc_1', "if (created) { this.w = weaponsenabled; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['w'] == 1.0

        gs1.load_weapon('w', "disableweapons;")
        gs1.trigger_event('created', name='weapon_w')
        assert gs1.weapons_enabled is False
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['w'] == 0.0

        gs1.load_weapon('w', "enableweapons;")
        gs1.trigger_event('created', name='weapon_w')
        assert gs1.weapons_enabled is True

    def test_playerfreezetime_counts_down_from_freezeplayer(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script('npc_1', "if (created) { this.ft = playerfreezetime; }", npc_id=1)
        gs1.trigger_npc_event(1, 'created')
        assert _this(gs1, 'npc_1')['ft'] == -1.0

        gs1.load_weapon('w', "freezeplayer 2;")
        gs1.trigger_event('created', name='weapon_w')
        gs1.trigger_npc_event(1, 'created')
        ft = _this(gs1, 'npc_1')['ft']
        assert 0.0 < ft <= 2.0

    def test_weapon_message_codes_selected_index_image_and_oob(self):
        c = Client("localhost", 14900)
        c.weapons = {
            "bomb": {"name": "bomb", "image": "bomb.png"},
            "bow": {"name": "bow", "image": "bow.png"},
        }
        gs1 = ClientGS1(c)
        gs1.selected_weapon_index = lambda: 1
        gs1.load_script(
            "npc_1",
            "if (created) { setstring this.n,#w; setstring this.i,#W; "
            "setstring this.n0,#w(0); setstring this.i0,#W(0); "
            "setstring this.bad,#w(9); }",
            npc_id=1,
        )
        gs1.trigger_npc_event(1, "created")
        values = _this(gs1, "npc_1")
        assert (values["n"], values["i"]) == ("bow", "bow.png")
        assert (values["n0"], values["i0"]) == ("bomb", "bomb.png")
        assert values["bad"] == ""

    def test_timevar2_is_live_monotonic_milliseconds(self):
        c = Client("localhost", 14900)
        gs1 = ClientGS1(c)
        gs1.load_script("npc_1", "if (created) { this.t=timevar2; }", npc_id=1)
        gs1.trigger_npc_event(1, "created")
        first = _this(gs1, "npc_1")["t"]
        time.sleep(0.002)
        gs1.trigger_npc_event(1, "created")
        second = _this(gs1, "npc_1")["t"]
        assert isinstance(first, float)
        assert second > first

    def test_player_and_npc_glovepower_scales_are_asymmetric(self):
        c = Client("localhost", 14900)
        c.player.glove_power = 2
        gs1 = ClientGS1(c)
        gs1.load_script(
            "npc_1",
            "if (created) { this.glovepower=1; this.pg=playerglovepower; "
            "this.ng=this.glovepower; }",
            npc_id=1,
        )
        gs1.trigger_npc_event(1, "created")
        values = _this(gs1, "npc_1")
        assert values["pg"] == 3.0
        assert values["ng"] == 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
