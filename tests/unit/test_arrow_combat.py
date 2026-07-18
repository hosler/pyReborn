"""Victim-side arrow flight simulation (client.py _tick_arrow_sims and
friends) - client-authoritative combat parity task 1.

Real GServer-v2 without a running NPCServer never runs its own arrow
collision detection (msgPLI_ARROWADD only calls level->addArrow() when
hasNPCServer() is true) - it just relays PLO_ARROWADD to everyone else in
the level. That means on a real server the VICTIM is the only one who can
notice they got shot: each client must simulate every other player's arrow
itself and self-apply damage when its own collision box connects.

These tests exercise the pure simulation geometry (hit/dodge/timing) via
direct calls to the tick/advance helpers (so they don't depend on real wall-
clock time or a live socket), plus the PLO_ARROWADD/PLO_HURTPLAYER packet
wiring and the double-damage guard against a server (pygserver) that also
runs its own independent arrow simulation.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import PacketID, parse_arrow_add
from reborn_protocol import PacketBuilder


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


def _build_plo_arrowadd(owner_id, x, y, direction, sprite=0, power=1,
                         reflect=False, from_player=True):
    """Build a PLO_ARROWADD (19) payload matching parse_arrow_add's format:
    {GSHORT owner_id}{GCHAR x2}{GCHAR y2}{GCHAR flags}{GCHAR sprite}{GCHAR power}."""
    flags = (direction & 0x03) | (0x04 if reflect else 0) | (0x08 if from_player else 0)
    b = PacketBuilder()
    b.write_gshort(owner_id)
    b.write_gchar(int(x * 2))
    b.write_gchar(int(y * 2))
    b.write_gchar(flags)
    b.write_gchar(sprite)
    b.write_gchar(power)
    return b.build()


def _build_plo_hurtplayer(attacker_id, damage_half_hearts, hurt_dx=0, hurt_dy=0):
    """Build a PLO_HURTPLAYER (40) payload matching parse_hurt_player's
    format: {GSHORT attacker_id}{GCHAR hurtdx}{GCHAR hurtdy}{GCHAR power}."""
    b = PacketBuilder()
    b.write_gshort(attacker_id)
    b.write_gchar(hurt_dx)
    b.write_gchar(hurt_dy)
    b.write_gchar(damage_half_hearts)
    return b.build()


class TestArrowWireFormat:
    def test_parse_arrowadd_roundtrip(self):
        data = _build_plo_arrowadd(owner_id=7, x=10.5, y=20.0, direction=3, power=2)
        info = parse_arrow_add(data)
        assert info['owner_id'] == 7
        assert info['x'] == pytest.approx(10.5)
        assert info['y'] == pytest.approx(20.0)
        assert info['direction'] == 3
        assert info['power'] == 2


class TestArrowSimGeometry:
    """Direct calls to _start_arrow_sim/_tick_arrow_sims so timing is fully
    controlled (no real sleeps)."""

    def test_hit_when_arrow_crosses_player(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 3, 'x': 25.0, 'y': 30.0, 'direction': 3}  # heading right, toward us
        c._start_arrow_sim(info, now=0.0)
        assert len(c._arrow_sims) == 1

        initial_hearts = c.player.hearts
        # Enough time for the arrow (8 tiles/sec) to cross our position
        # (5 tiles away) well before the 2s lifetime expires.
        c._tick_arrow_sims(now=1.0)

        # The hit is detected but not applied immediately - it's queued for
        # _ARROW_HIT_GRACE seconds first (see _tick_arrow_sims) to give a
        # server that also runs its own arrow simulation, like pygserver, a
        # chance to report the SAME hit first and be deduped instead of
        # double-applied.
        assert c.player.hearts == initial_hearts
        assert c._arrow_sims == []  # consumed on hit
        assert len(c._pending_arrow_hits) == 1

        c._tick_arrow_sims(now=1.0 + c._ARROW_HIT_GRACE)
        assert c.player.hearts == pytest.approx(initial_hearts - c._ARROW_DAMAGE)
        assert c._pending_arrow_hits == []

    def test_dodge_when_player_moves_away(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 3, 'x': 20.0, 'y': 30.0, 'direction': 3}  # heading right
        c._start_arrow_sim(info, now=0.0)

        # We dodge: move well away from the arrow's path before it arrives.
        c.player.x, c.player.y = 30.0, 50.0
        initial_hearts = c.player.hearts

        # Tick partway through flight - arrow is near our OLD position but
        # we're not there anymore, so no hit yet.
        c._tick_arrow_sims(now=1.0)
        assert c.player.hearts == initial_hearts
        assert len(c._arrow_sims) == 1  # still in flight, hasn't expired

        # Tick past the arrow's 2s lifetime - it should be dropped as a
        # miss, not linger forever.
        c._tick_arrow_sims(now=2.1)
        assert c.player.hearts == initial_hearts
        assert c._arrow_sims == []

    def test_arrow_moving_away_never_hits(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        # Arrow starts right next to us but heads AWAY (left, away from our
        # position which is to its right).
        info = {'owner_id': 3, 'x': 29.5, 'y': 30.0, 'direction': 1}  # heading left
        c._start_arrow_sim(info, now=0.0)
        initial_hearts = c.player.hearts

        c._tick_arrow_sims(now=2.1)
        assert c.player.hearts == initial_hearts
        assert c._arrow_sims == []

    def test_expired_arrow_is_pruned_without_hit(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        # Arrow far enough away that it would eventually reach us, but not
        # before its lifetime runs out (2s * 8 tiles/s = 16 tiles max range;
        # this one is 20 tiles out).
        info = {'owner_id': 3, 'x': 10.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)
        initial_hearts = c.player.hearts

        c._tick_arrow_sims(now=2.1)
        assert c.player.hearts == initial_hearts
        assert c._arrow_sims == []

    def test_own_recent_arrow_echo_not_simulated(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        # shoot_arrow() records the self-fire signature under
        # _own_recent_arrows; a matching PLO_ARROWADD echo (as pygserver
        # sends, broadcasting to the whole level including the shooter)
        # must not be simulated as an incoming attack.
        c.player.arrows = 1
        assert c.shoot_arrow(x=30.0, y=30.0, direction=2) is True

        info = {'owner_id': 0, 'x': 30.0, 'y': 30.0, 'direction': 2}
        c._start_arrow_sim(info)
        assert c._arrow_sims == []

    def test_full_packet_path_starts_a_sim(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        data = _build_plo_arrowadd(owner_id=9, x=25.0, y=30.0, direction=3)
        c._handle_packet(PacketID.PLO_ARROWADD, data)
        assert len(c._arrow_sims) == 1
        assert c._arrow_sims[0]['owner_id'] == 9


class TestArrowDoubleDamageGuard:
    """pygserver runs its own independent server-side arrow simulation in
    parallel with ours (see combat.py's CombatManager) and sends a real
    PLO_HURTPLAYER for the same hit our own sim would also detect - on its
    own schedule, with no awareness of what our client has or hasn't
    applied yet. Either side may resolve first; only one hit may ever be
    applied.

    Live pygserver repro that motivated the grace-period design (see
    _ARROW_HIT_GRACE): applying our own detected hit IMMEDIATELY let
    pygserver's own independent detection land moments later and silently
    subtract a second, unguarded 0.5 hearts via its own CURPOWER push - a
    single 0.5-heart arrow took a full 1.0 hearts. Queuing our own
    application for a short grace period lets a genuinely-independent
    server-side hit (if the server sends one at all) arrive and be recorded
    first.
    """

    def test_client_detects_first_server_echo_during_grace_is_dropped(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 5, 'x': 25.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)

        initial_hearts = c.player.hearts
        # Our own sim detects the hit and queues it (not yet applied).
        c._tick_arrow_sims(now=1.0)
        assert c.player.hearts == initial_hearts
        assert len(c._pending_arrow_hits) == 1

        # The server's own independent simulation detects the SAME hit
        # during our grace window and sends a real PLO_HURTPLAYER for it.
        data = _build_plo_hurtplayer(attacker_id=5, damage_half_hearts=1)
        c._handle_packet(PacketID.PLO_HURTPLAYER, data)
        after_server_hit = c.player.hearts
        assert after_server_hit == pytest.approx(initial_hearts - 0.5)
        # Our own pending application for that owner is cancelled.
        assert c._pending_arrow_hits == []

        # Once our grace period elapses there's nothing left to apply.
        c._tick_arrow_sims(now=1.0 + c._ARROW_HIT_GRACE)
        assert c.player.hearts == after_server_hit

    def test_server_detects_first_client_sim_is_dropped(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 5, 'x': 25.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)
        assert len(c._arrow_sims) == 1

        initial_hearts = c.player.hearts
        # The server's own simulation resolves the hit FIRST and tells us
        # via a real PLO_HURTPLAYER, before our own sim has caught up.
        data = _build_plo_hurtplayer(attacker_id=5, damage_half_hearts=1)
        c._handle_packet(PacketID.PLO_HURTPLAYER, data)
        after_server_hit = c.player.hearts
        assert after_server_hit == pytest.approx(initial_hearts - 0.5)

        # The in-flight sim from that same owner must be consumed so it
        # doesn't apply again once it catches up.
        assert c._arrow_sims == []
        c._tick_arrow_sims(now=1.0)
        assert c.player.hearts == after_server_hit

    def test_server_hit_before_sim_exists_still_suppresses_later_sim(self):
        # Regression: PLO_HURTPLAYER and PLO_ARROWADD aren't guaranteed to
        # arrive in a particular order - the server's own hit can land
        # before we've even started simulating that arrow ourselves. The
        # suppression must still apply once our sim does start and catches
        # up to the same hit, or it double-applies (live pygserver repro:
        # 1.0 hearts of damage from what should have been a single 0.5-heart
        # arrow hit).
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        initial_hearts = c.player.hearts

        data = _build_plo_hurtplayer(attacker_id=5, damage_half_hearts=1)
        c._handle_packet(PacketID.PLO_HURTPLAYER, data)
        after_server_hit = c.player.hearts
        assert after_server_hit == pytest.approx(initial_hearts - 0.5)

        # Only now does the PLO_ARROWADD relay for that same arrow arrive.
        info = {'owner_id': 5, 'x': 25.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)
        c._tick_arrow_sims(now=1.0)

        assert c.player.hearts == after_server_hit

    def test_no_server_echo_applies_after_grace_period(self):
        # Real GServer-v2 never sends a server-side arrow hurt at all (pure
        # relay - see msgPLI_ARROWADD) - our own detection must still apply
        # once the grace period elapses with nothing else arriving.
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 5, 'x': 25.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)
        initial_hearts = c.player.hearts

        c._tick_arrow_sims(now=1.0)
        assert c.player.hearts == initial_hearts  # queued, not yet applied
        c._tick_arrow_sims(now=1.0 + c._ARROW_HIT_GRACE)
        assert c.player.hearts == pytest.approx(initial_hearts - c._ARROW_DAMAGE)

    def test_unrelated_owner_not_suppressed(self):
        # A hurt from a DIFFERENT attacker while an unrelated arrow sim is
        # in flight must apply normally.
        c = _fake_connected_client()
        c.player.x, c.player.y = 30.0, 30.0
        info = {'owner_id': 5, 'x': 25.0, 'y': 30.0, 'direction': 3}
        c._start_arrow_sim(info, now=0.0)

        initial_hearts = c.player.hearts
        data = _build_plo_hurtplayer(attacker_id=99, damage_half_hearts=1)
        c._handle_packet(PacketID.PLO_HURTPLAYER, data)
        assert c.player.hearts == pytest.approx(initial_hearts - 0.5)
        # The unrelated in-flight sim (owner 5) is untouched.
        assert len(c._arrow_sims) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
