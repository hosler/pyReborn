"""Leader-authoritative baddy damage (client.py Client.is_leader /
_leader_apply_baddy_damage) - client-authoritative combat parity task 2.

GServer-v2 makes the level's LEADER (PLO_ISLEADER) the sole resolver of
baddy damage: any other player's PLI_BADDYHURT is relayed to the leader
ONLY (msgPLI_BADDYHURT, PlayerClientPackets.cpp:523-539 -
`leader->sendPacket(...)`), and the leader applies the damage locally and
reports the result back via PLI_BADDYPROPS, which the server both stores
and relays to every OTHER player in the level (msgPLI_BADDYPROPS,
PlayerClientPackets.cpp:494-521 - the leader itself excluded from that
relay). Without this, a non-leader's hit only ever updates the leader's own
cosmetic copy of the baddy and never reaches anyone else, and the leader's
own attacks never apply damage until a self-relay round trip completes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import PacketID, build_baddy_hurt, build_baddy_props
from reborn_protocol import BDPROP, BDMODE


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


def _baddyprops_sent(c):
    return [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_BADDYPROPS)]


def _baddyhurt_sent(c):
    return [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_BADDYHURT)]


class TestLeaderRelayedBaddyHurt:
    """Task 2(a): PLO_BADDYHURT relayed from another player's PLI_BADDYHURT."""

    def test_non_leader_only_updates_local_copy(self):
        c = _fake_connected_client()
        c.is_leader = False
        c.baddies[5] = {'id': 5, 'power': 3, 'image': 'baddygray.png', 'mode': int(BDMODE.WALK)}

        c._handle_packet(PacketID.PLO_BADDYHURT, build_baddy_hurt(5, damage=1.0))

        assert c.baddies[5]['power'] == 1  # 3 - 2 half-hearts, existing behavior unchanged
        assert c.baddies[5]['mode'] == int(BDMODE.WALK)  # non-leader never touches mode
        assert _baddyprops_sent(c) == []  # non-leader never broadcasts

    def test_leader_applies_damage_and_broadcasts(self):
        c = _fake_connected_client()
        c.is_leader = True
        c.baddies[5] = {'id': 5, 'power': 3, 'image': 'baddygray.png', 'mode': int(BDMODE.WALK)}

        c._handle_packet(PacketID.PLO_BADDYHURT, build_baddy_hurt(5, damage=1.0))

        assert c.baddies[5]['power'] == 1
        assert c.baddies[5]['mode'] == int(BDMODE.HURT)
        sent = _baddyprops_sent(c)
        assert len(sent) == 1
        expected = build_baddy_props(5, {
            BDPROP.POWERIMAGE: (1, 'baddygray.png'),
            BDPROP.MODE: int(BDMODE.HURT),
        })
        assert sent[0] == expected

    def test_leader_kills_baddy_on_lethal_hit(self):
        c = _fake_connected_client()
        c.is_leader = True
        c.baddies[5] = {'id': 5, 'power': 1, 'image': 'baddygray.png', 'mode': int(BDMODE.WALK)}

        # 1.0 hearts = 2 half-hearts, more than the baddy's remaining power.
        c._handle_packet(PacketID.PLO_BADDYHURT, build_baddy_hurt(5, damage=1.0))

        assert c.baddies[5]['power'] == 0
        assert c.baddies[5]['mode'] == int(BDMODE.DEAD)
        sent = _baddyprops_sent(c)
        expected = build_baddy_props(5, {
            BDPROP.POWERIMAGE: (0, 'baddygray.png'),
            BDPROP.MODE: int(BDMODE.DEAD),
        })
        assert sent == [expected]

    def test_unknown_baddy_ignored(self):
        c = _fake_connected_client()
        c.is_leader = True
        c._handle_packet(PacketID.PLO_BADDYHURT, build_baddy_hurt(99, damage=1.0))
        assert _baddyprops_sent(c) == []


class TestLeaderOwnAttack:
    """Task 2(b): the leader's own attacks apply locally + broadcast instead
    of firing PLI_BADDYHURT and waiting on a self-relay round trip (which
    would also double-apply once the echo landed in the handler above)."""

    def test_leader_sword_hit_applies_locally_no_baddyhurt_sent(self):
        c = _fake_connected_client()
        c.is_leader = True
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.player.sword_power = 2  # 1.0 heart = 2 half-hearts
        c.baddies[5] = {'id': 5, 'x': 30.0, 'y': 32.0, 'power': 3,
                         'image': 'baddygray.png', 'mode': int(BDMODE.WALK)}

        c.sword_attack(direction=2)

        assert _baddyhurt_sent(c) == []  # leader never sends PLI_BADDYHURT for its own hit
        assert c.baddies[5]['power'] == 1  # 3 - 2 half-hearts, applied locally
        assert c.baddies[5]['mode'] == int(BDMODE.HURT)
        assert len(_baddyprops_sent(c)) == 1

    def test_non_leader_sword_hit_still_sends_baddyhurt(self):
        # Regression: non-leader behavior must stay exactly as before.
        c = _fake_connected_client()
        c.is_leader = False
        c.player.x, c.player.y = 30.0, 30.0
        c.player.direction = 2
        c.player.sword_power = 2
        c.baddies[5] = {'id': 5, 'x': 30.0, 'y': 32.0, 'power': 3}

        c.sword_attack(direction=2)

        assert len(_baddyhurt_sent(c)) == 1
        assert _baddyprops_sent(c) == []
        # No local application - server/leader resolves it.
        assert c.baddies[5]['power'] == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
