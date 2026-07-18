"""Regression tests for sword swings hitting NPCs and baddies, not just
players (client.py sword_attack/_sword_hit_npcs/_sword_hit_baddies).

Before this fix, sword_attack() only iterated self.players — NPCs never got
`washit` and baddies never took real (PLI_BADDYHURT) damage from a swing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import PacketID, build_baddy_hurt


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


class TestSwordHitNpcs:
    def test_swing_hits_npc_in_arc(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2  # facing down
        c.npcs[1] = {'x': 30.0, 'y': 32.0, 'world_x': 30.0, 'world_y': 32.0}
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=2)
        assert hits == [1]

    def test_hidden_npc_not_hit(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.npcs[1] = {'x': 30.0, 'y': 32.0, 'world_x': 30.0, 'world_y': 32.0,
                     'visible': False}
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=2)
        assert hits == []

    def test_dontblock_npc_not_hit(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.npcs[1] = {'x': 30.0, 'y': 32.0, 'world_x': 30.0, 'world_y': 32.0,
                     'dontblock': True}
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=2)
        assert hits == []

    def test_npc_out_of_arc_not_hit(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2  # facing down
        # NPC is behind the player (up), not in the down-swing arc.
        c.npcs[1] = {'x': 30.0, 'y': 20.0, 'world_x': 30.0, 'world_y': 20.0}
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=2)
        assert hits == []

    def test_npc_uses_world_coords_over_local(self):
        # On a GMAP, an NPC's raw x/y are level-local (0-63); world_x/world_y
        # (set from PLO_NPCPROPS + gmap_grid, client.py:2267-2282) must be what
        # gets compared to the player's world position, or the arc check
        # misses NPCs on any segment but the origin one.
        c = _fake_connected_client()
        c.player.x, c.player.y = 66.0, 30.0   # world coords, segment (1, 0)
        c.player.direction = 2                # facing down
        c.npcs[1] = {'x': 2.0, 'y': 32.0,       # local coords (would miss)
                     'world_x': 66.0, 'world_y': 32.0}  # world coords (hits)
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=2)
        assert hits == [1]


class TestSwordHitBaddies:
    def test_swing_hurts_baddy_in_arc(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.player.sword_power = 2
        c.baddies[5] = {'x': 30.0, 'y': 32.0}
        c.sword_attack(direction=2)
        assert (int(PacketID.PLI_BADDYHURT), build_baddy_hurt(5, 1.0)) in c._protocol.sent

    def test_baddy_out_of_arc_not_hurt(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.baddies[5] = {'x': 30.0, 'y': 20.0}
        c.sword_attack(direction=2)
        assert not any(pid == int(PacketID.PLI_BADDYHURT) for pid, _ in c._protocol.sent)

    def test_baddy_uses_gmap_segment_offset(self):
        # Baddy positions are level-local (no world_x/world_y, unlike NPCs);
        # the current segment's offset must be folded in before comparing to
        # the player's world position.
        c = _fake_connected_client()
        c.gmap_grid[(0, 0)] = "seg0.nw"
        c.gmap_grid[(1, 0)] = "seg1.nw"
        c._current_level_name = "seg1.nw"
        c.player.x, c.player.y = 66.0, 30.0   # world coords, inside segment (1,0)
        c.player.direction = 2
        c.baddies[5] = {'x': 2.0, 'y': 32.0}  # local coords within seg1
        c.sword_attack(direction=2)
        assert any(pid == int(PacketID.PLI_BADDYHURT) for pid, _ in c._protocol.sent)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
