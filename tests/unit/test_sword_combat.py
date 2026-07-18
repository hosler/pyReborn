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
from pyreborn.packets import PacketID, build_baddy_hurt, parse_baddy_hurt


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
        # _sword_hit_baddies passes the swing's direction vector through as
        # hurt_dx/hurt_dy (down = (0, 1)) - see build_baddy_hurt.
        expected = build_baddy_hurt(5, 1.0, hurt_dx=0.0, hurt_dy=1.0)
        assert (int(PacketID.PLI_BADDYHURT), expected) in c._protocol.sent

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


class TestSwordArcSymmetry:
    """Regression for the up/down reach asymmetry: the target side of the
    forward-distance projection used to add +1.0 to the target's Y while the
    attacker's own center used +1.5, so up and down swings measured against
    different reference points (see the comment on Client._SWORD_REACH).
    Down-swing effective reach was REACH+0.5, up-swing REACH-0.5 - a full
    1-tile gap - while left/right (which never had the mismatch) were fine.
    """

    GAP_HITS = 2.2   # within the fixed symmetric reach (2.5) on every side
    GAP_MISSES = 2.6  # just past the fixed symmetric reach on every side

    DIRECTIONS = {
        0: (0, -1),  # up
        1: (-1, 0),  # left
        2: (0, 1),   # down
        3: (1, 0),   # right
    }

    def _hit(self, direction: int, gap: float) -> bool:
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = direction
        fx, fy = self.DIRECTIONS[direction]
        c.npcs[1] = {'x': 30.0 + fx * gap, 'y': 30.0 + fy * gap,
                     'world_x': 30.0 + fx * gap, 'world_y': 30.0 + fy * gap}
        hits = []
        c.on_sword_hit_npc = hits.append
        c.sword_attack(direction=direction)
        return hits == [1]

    @pytest.mark.parametrize("direction", [0, 1, 2, 3])
    def test_symmetric_hit_at_same_gap(self, direction):
        assert self._hit(direction, self.GAP_HITS) is True

    @pytest.mark.parametrize("direction", [0, 1, 2, 3])
    def test_symmetric_miss_at_same_gap(self, direction):
        assert self._hit(direction, self.GAP_MISSES) is False

    def test_up_and_down_reach_match(self):
        # The specific live-playtest evidence: down hit at a 2.2-tile gap,
        # up did not (needed <= ~1.2-2.0 pre-fix). Both must now agree.
        assert self._hit(0, self.GAP_HITS) == self._hit(2, self.GAP_HITS)


class TestBaddyHurtWireFormat:
    """PLI/PLO_BADDYHURT wire format (GServer-v2 msgPLI_BADDYHURT,
    PlayerClientPackets.cpp:523-539, commit e0cd07af9bb4be09c54c0335f222dd0eacb71c1):
    [GUChar baddyId][GChar hurtDX][GChar hurtDY][GUChar damage, half-hearts].
    hurtDX/hurtDY use the "midpoint: 64" gchar idiom.
    """

    def test_build_is_four_bytes(self):
        data = build_baddy_hurt(5, 1.0, hurt_dx=0.0, hurt_dy=1.0)
        assert len(data) == 4

    def test_neutral_direction_encodes_midpoint(self):
        # hurt_dx=hurt_dy=0.0 -> raw byte 64 (midpoint) + 32 header offset.
        data = build_baddy_hurt(5, 1.0)
        assert data[1] == 64 + 32
        assert data[2] == 64 + 32

    def test_roundtrip_direction_and_damage(self):
        data = build_baddy_hurt(7, 1.5, hurt_dx=-1.0, hurt_dy=1.0)
        parsed = parse_baddy_hurt(data)
        assert parsed['baddy_id'] == 7
        assert parsed['knockback_x'] == -64
        assert parsed['knockback_y'] == 64
        assert parsed['power'] == 3  # 1.5 hearts -> 3 half-hearts

    def test_roundtrip_no_direction(self):
        data = build_baddy_hurt(5, 1.0)
        parsed = parse_baddy_hurt(data)
        assert parsed['knockback_x'] == 0
        assert parsed['knockback_y'] == 0
        assert parsed['power'] == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
