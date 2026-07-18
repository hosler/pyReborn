"""Regression tests for the 2026-07-18 gmap coordinate/attribution playtest
findings (chicken.gmap, segment (1,1) = chicken1.nw):

1. players_visible frame poisoning - PLO_OTHERPLPROPS classic X/Y (15/16,
   always LEVEL-LOCAL) and high-precision X2/Y2 (78/79, WORLD pixels on a
   gmap for some server paths) both write into the same props['x']/['y']
   keys, so which prop arrived LAST silently flipped the frame stored per
   player. Sword hits at a normal 1.5-tile gap missed forever while
   poisoned (fixed hits reproduced as hit->miss->miss).
3. gmap board flip-flop - a GMAP adjacent-segment preload (streamed via
   PLO_LEVELNAME + PLO_BOARDPACKET for a neighbour, no PLO_PLAYERWARP2)
   used to unconditionally overwrite self.tiles, so the ACTIVE render/
   collision board flip-flopped to whichever neighbour last streamed.
4. NPC world-coord double-offset - PLO_NPCPROPS' X2/Y2 (75/76) can carry an
   already-world value on a real GServer-v2; adding the segment offset on
   top of that double-counted it.

See pyReborn/pyreborn/client.py's PLO_OTHERPLPROPS/PLO_BOARDPACKET/
PLO_NPCPROPS handlers and _sword_hit_players for the fixes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import PacketID


class _SentRecorder:
    """Stub protocol capturing send_packet calls."""

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


def _client_with_grid():
    # 3x3 grid matching funtimes' chicken.gmap layout (chicken1.nw at
    # grid (1, 1), chicken2.nw at (0, 1), per the live playtest repro).
    c = _fake_connected_client()
    names = [
        "chicken4.nw", "chicken5.nw", "chicken6.nw",
        "chicken2.nw", "chicken1.nw", "chicken7.nw",
        "chicken3.nw", "chicken9.nw", "chicken8.nw",
    ]
    c.gmap_width, c.gmap_height = 3, 3
    for i, name in enumerate(names):
        c.gmap_grid[(i % 3, i // 3)] = name
    return c


# =============================================================================
# Wire-format helpers (mirrors pygserver/protocol/packets.py's encoders)
# =============================================================================

def _gshort(v: int) -> bytes:
    return bytes([((v >> 7) & 0x7F) + 32, (v & 0x7F) + 32])


def _gint3(v: int) -> bytes:
    return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32, (v & 0x7F) + 32])


def _classic_pos(prop_id: int, tiles: float) -> bytes:
    """PLPROP_X/Y (15/16) or NPCPROP_X/Y (2/3): 1 byte, half-tile precision."""
    return bytes([prop_id + 32, int(tiles * 2) + 32])


def _pixel_pos(prop_id: int, tiles: float) -> bytes:
    """PLPROP_X2/Y2 (78/79) or NPCPROP_X2/Y2 (75/76): 2 bytes, pixels/16."""
    pixels = int(tiles * 16)
    if pixels < 0:
        value = ((-pixels) << 1) | 1
    else:
        value = pixels << 1
    return bytes([prop_id + 32, ((value >> 7) & 0x7F) + 32, (value & 0x7F) + 32])


def _other_player_props(pid: int, *prop_bytes: bytes) -> bytes:
    return _gshort(pid) + b"".join(prop_bytes)


def _npc_props(npc_id: int, *prop_bytes: bytes) -> bytes:
    return _gint3(npc_id) + b"".join(prop_bytes)


def _board(fill_tile: int) -> bytes:
    """8192-byte PLO_BOARDPACKET body: 4096 tiles, all `fill_tile`
    (little-endian gshort each)."""
    tile = bytes([fill_tile & 0xFF, (fill_tile >> 8) & 0xFF])
    return tile * 4096


# =============================================================================
# BUG 1 - players_visible frame poisoning
# =============================================================================

class TestOtherPlPropsFrameNormalization:
    """Classic X/Y (local) and X2/Y2 (world on a gmap) must not silently
    flip the frame players[pid]['x'/'y'] is stored in."""

    def test_local_update_leaves_no_world_coords(self):
        c = _fake_connected_client()
        data = _other_player_props(5, _classic_pos(15, 33.5), _classic_pos(16, 33.5))
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, data)
        assert c.players[5]['x'] == 33.5
        assert c.players[5]['y'] == 33.5
        assert c.players[5].get('world_x') is None
        assert c.players[5].get('world_y') is None

    def test_world_update_wraps_to_local_and_keeps_world(self):
        c = _fake_connected_client()
        # World (97.25, 97.25) = grid (1,1) local (33.25, 33.25).
        data = _other_player_props(5, _pixel_pos(78, 97.25), _pixel_pos(79, 97.25))
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, data)
        assert c.players[5]['x'] == 33.25
        assert c.players[5]['y'] == 33.25
        assert c.players[5]['world_x'] == 97.25
        assert c.players[5]['world_y'] == 97.25

    def test_local_then_world_does_not_poison_local_frame(self):
        """The live repro: classic X/Y arrives first (e.g. plain movement
        relay), then X2/Y2 with a world value (e.g. a hurt response
        round-tripped through the server) - 'x'/'y' must stay canonically
        local across both."""
        c = _fake_connected_client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            5, _classic_pos(15, 33.5), _classic_pos(16, 33.5)))
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            5, _pixel_pos(78, 97.25), _pixel_pos(79, 97.25)))
        assert c.players[5]['x'] == 33.25
        assert c.players[5]['y'] == 33.25
        assert c.players[5]['world_x'] == 97.25

    def test_world_then_local_invalidates_stale_world_coords(self):
        """A later LOCAL-only update (the player moved) must drop the
        previous world_x/world_y rather than let it silently survive next
        to a now-different local position."""
        c = _fake_connected_client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            5, _pixel_pos(78, 97.25), _pixel_pos(79, 97.25)))
        assert c.players[5]['world_x'] == 97.25

        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            5, _classic_pos(15, 40.0), _classic_pos(16, 40.0)))
        assert c.players[5]['x'] == 40.0
        assert 'world_x' not in c.players[5]
        assert 'world_y' not in c.players[5]


class TestSwordHitAfterNormalization:
    """A sword swing at a normal ~1.5-tile gap must land regardless of
    which prop(s) most recently updated the target - reproduces the
    hit->miss->miss cycle from repeated PLI_HURTPLAYER round-trips."""

    def _attacker(self):
        c = _client_with_grid()
        c._current_level_name = "chicken1.nw"
        c.player.x, c.player.y = 70.0, 70.0  # grid (1,1), local (6, 6)
        c.player.direction = 3  # right
        return c

    def test_hits_with_world_coords_from_x2y2(self):
        c = self._attacker()
        # Victim at world (71.5, 70.0): 1.5 tiles to the right.
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            9, _pixel_pos(78, 71.5), _pixel_pos(79, 70.0)))
        assert c.sword_attack(direction=3) is True
        assert (int(PacketID.PLI_HURTPLAYER) in [pid for pid, _ in c._protocol.sent])

    def test_hits_with_local_coords_same_segment(self):
        c = self._attacker()
        # Victim reported via classic X/Y (local 7.5, 6.0 == same segment).
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
            9, _classic_pos(15, 7.5), _classic_pos(16, 6.0)))
        assert c.sword_attack(direction=3) is True
        assert (int(PacketID.PLI_HURTPLAYER) in [pid for pid, _ in c._protocol.sent])

    def test_repeated_hit_miss_miss_cycle_now_hits_every_swing(self):
        """Simulates 3 consecutive swings, each preceded by the victim's
        hurt-response round-trip (X2/Y2 world) then a plain movement relay
        (classic X/Y local) - the exact interleave that used to flip the
        stored frame and make every other swing miss."""
        c = self._attacker()
        for i in range(3):
            c._protocol.sent.clear()
            # Hurt-response relay: world coords via X2/Y2.
            c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
                9, _pixel_pos(78, 71.5), _pixel_pos(79, 70.0)))
            assert c.sword_attack(direction=3) is True
            hits = [pid for pid, _ in c._protocol.sent if pid == int(PacketID.PLI_HURTPLAYER)]
            assert hits, f"swing {i} missed"
            # Plain movement relay: local coords via classic X/Y, same spot.
            c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other_player_props(
                9, _classic_pos(15, 7.5), _classic_pos(16, 70.0 % 64)))


# =============================================================================
# BUG 3 - gmap board flip-flop (self.tiles must not follow a preload)
# =============================================================================

class TestBoardAttributionStaysOnCurrentSegment:
    def _warp_into(self, c, level_name, fill_tile):
        """Simulate a real warp/spawn: PLO_LEVELNAME then PLO_BOARDPACKET,
        exactly like warp_to_level()'s optimistic flip + confirming board."""
        c._current_level_name = level_name
        c._pending_level_name = level_name
        c._handle_packet(PacketID.PLO_LEVELNAME, level_name.encode('latin-1'))
        c._handle_packet(PacketID.PLO_BOARDPACKET, _board(fill_tile))

    def test_adjacent_preload_does_not_clobber_active_board(self):
        c = _client_with_grid()
        self._warp_into(c, "chicken1.nw", fill_tile=1)
        assert c.tiles[0] == 1
        assert c._tiles_level_name == "chicken1.nw"

        # Adjacent-segment preload: LEVELNAME + board for a neighbour, no
        # PLAYERWARP2 - the player never actually moves.
        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken2.nw")
        c._handle_packet(PacketID.PLO_BOARDPACKET, _board(fill_tile=2))

        assert c.tiles[0] == 1, "preload clobbered the ACTIVE render board"
        assert c._tiles_level_name == "chicken1.nw"
        assert c.levels["chicken2.nw"][0] == 2

    def test_interleaved_preload_burst_lands_each_board_under_right_name(self):
        """8-neighbour preload burst: every LEVELNAME/board pair must land
        in self.levels[] under ITS OWN name, and self.tiles must stay on
        the real segment throughout - not just after the last one."""
        c = _client_with_grid()
        self._warp_into(c, "chicken1.nw", fill_tile=1)

        neighbours = [
            ("chicken4.nw", 4), ("chicken5.nw", 5), ("chicken6.nw", 6),
            ("chicken2.nw", 2), ("chicken7.nw", 7), ("chicken3.nw", 3),
            ("chicken9.nw", 9), ("chicken8.nw", 8),
        ]
        for name, fill in neighbours:
            c._handle_packet(PacketID.PLO_LEVELNAME, name.encode('latin-1'))
            c._handle_packet(PacketID.PLO_BOARDPACKET, _board(fill))
            # self.tiles must be unaffected by EVERY single preload, not
            # just be back to normal by the time the burst finishes.
            assert c.tiles[0] == 1, f"preload of {name} clobbered self.tiles"
            assert c._tiles_level_name == "chicken1.nw"

        for name, fill in neighbours:
            assert c.levels[name][0] == fill

    def test_real_warp_after_preload_burst_updates_active_board(self):
        """A genuine warp into a previously-preloaded neighbour must still
        make it the active board."""
        c = _client_with_grid()
        self._warp_into(c, "chicken1.nw", fill_tile=1)
        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken2.nw")
        c._handle_packet(PacketID.PLO_BOARDPACKET, _board(fill_tile=2))
        assert c.tiles[0] == 1  # still on chicken1

        # Real edge-cross into chicken2.nw (move() flips _current_level_name
        # synchronously at send time before the confirming packets return).
        c._current_level_name = "chicken2.nw"
        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken2.nw")
        c._handle_packet(PacketID.PLO_BOARDPACKET, _board(fill_tile=2))
        assert c.tiles[0] == 2
        assert c._tiles_level_name == "chicken2.nw"


# =============================================================================
# BUG 4 - NPC world-coord double-offset
# =============================================================================

class TestNpcWorldCoordDoubleOffsetGuard:
    def test_local_npc_coords_get_segment_offset_once(self):
        c = _client_with_grid()
        c._current_level_name = "chicken1.nw"  # grid (1, 1)
        c._pending_level_name = "chicken1.nw"
        c._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
            42, _classic_pos(2, 20.0), _classic_pos(3, 30.0)))
        npc = c.npcs[42]
        assert npc['x'] == 20.0
        assert npc['world_x'] == 20.0 + 64
        assert npc['world_y'] == 30.0 + 64

    def test_already_world_npc_coords_are_not_double_offset(self):
        """A real-GServer-v2 style NPCPROPS where X2/Y2 (75/76) already
        carries a world value must not get the segment offset added again."""
        c = _client_with_grid()
        c._current_level_name = "chicken1.nw"  # grid (1, 1)
        c._pending_level_name = "chicken1.nw"
        # 84.0/94.0 is already world (grid (1,1) local (20, 30) + 64).
        c._handle_packet(PacketID.PLO_NPCPROPS, _npc_props(
            42, _pixel_pos(75, 84.0), _pixel_pos(76, 94.0)))
        npc = c.npcs[42]
        assert npc['world_x'] == 84.0
        assert npc['world_y'] == 94.0

    def test_update_npc_world_coords_rerun_does_not_double_offset(self):
        """_update_npc_world_coords() (called again e.g. on gmap grid
        reload) must be idempotent for an NPC whose 'x' is already world."""
        c = _client_with_grid()
        c.npcs[42] = {'id': 42, '_level': 'chicken1.nw', 'x': 84.0, 'y': 94.0}
        c._update_npc_world_coords()
        c._update_npc_world_coords()
        assert c.npcs[42]['world_x'] == 84.0
        assert c.npcs[42]['world_y'] == 94.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
