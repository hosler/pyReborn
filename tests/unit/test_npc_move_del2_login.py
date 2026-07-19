"""Unit coverage for newly-wired server->client packets found in the 2026-07
GServer-v2 IEnums.h sweep:

- PLO_MOVE (165): legacy (pre-CLVER_2_3) NPC move-queue update, the
  GCHAR-precision sibling of the already-handled PLO_MOVE2 (189)
  (server/src/object/NPC.cpp getMoveQueuePacketData / sendMoveQueueToPlayer /
  sendMoveQueueToLevel).
- PLO_NPCDEL2 (150): NPC delete scoped to an explicit level name, sent
  instead of PLO_NPCDEL when the target player isn't currently on the NPC's
  level (server/src/Server.cpp:1950-1954, object/NPC.cpp:857-870).
- PLO_UNKNOWN168 (168): blank "you are logged in" marker
  (server/src/player/Player.cpp:700-709).

PLO_NPCACTION (26) and PLO_GHOSTTEXT (173) are deliberately NOT covered here:
GServer-v2 never actually sends either (they only appear in Player.cpp's
FOR_OUTPUT_PACKETS enum-name table, with no sendPacket call anywhere in
server/src) - a test locks in that they stay out of HANDLED_PLO_IDS.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn.client import Client, HANDLED_PLO_IDS
from pyreborn.packets import PacketID, parse_move, parse_npcdel2
from reborn_protocol import PacketBuilder


# =============================================================================
# PLO_MOVE (165) - parse_move
# =============================================================================

def _move_packet(npc_id, pos_x8, pos_y8, dx_units, dy_units,
                  time_increments, options):
    """Build a raw PLO_MOVE payload matching GServer-v2's 'result.first'
    encoding (NPC.cpp:447-457): GINT3 id, then 2 GCHAR pos (tiles*8), 2 GCHAR
    delta (+100 offset), GSHORT time, GCHAR options."""
    b = PacketBuilder()
    b.write_gint3(npc_id)
    b.write_gchar(pos_x8)
    b.write_gchar(pos_y8)
    b.write_gchar(dx_units + 100)
    b.write_gchar(dy_units + 100)
    b.write_gshort(time_increments)
    b.write_gchar(options)
    return b.build()


class TestParseMove:
    def test_decodes_position_and_delta(self):
        # NPC at local pixel (80, 96) -> tiles*8 units 10/12, moving +2/-1
        # tiles (dx=+2*16=32px -> /8=4 units, dy=-1*16=-16px -> /8=-2 units),
        # 3 seconds (60 * 50ms), options bitmask 5.
        data = _move_packet(npc_id=42, pos_x8=10, pos_y8=12,
                             dx_units=4, dy_units=-2,
                             time_increments=60, options=5)
        info = parse_move(data)
        assert info['npc_id'] == 42
        assert info['x'] == 10 * 8 / 16.0  # 5.0 tiles
        assert info['y'] == 12 * 8 / 16.0  # 6.0 tiles
        assert info['dx'] == 4 * 8 / 16.0  # 2.0 tiles
        assert info['dy'] == -2 * 8 / 16.0  # -1.0 tiles
        assert info['duration_ms'] == 60 * 50
        assert info['options'] == 5

    def test_negative_delta_clamped_at_offset_floor(self):
        # dx_units below -100 can't be represented (gchar floors at 0), so
        # the offset write clamps to 0 -> decodes back as exactly -100.
        data = _move_packet(npc_id=1, pos_x8=0, pos_y8=0,
                             dx_units=-999, dy_units=0,
                             time_increments=0, options=0)
        info = parse_move(data)
        assert info['dx'] == -100 * 8 / 16.0


# =============================================================================
# PLO_MOVE (165) wired into Client._handle_packet - mirrors PLO_MOVE2
# =============================================================================

class TestClientHandlesMove:
    def test_updates_existing_npc_position_and_move_cache(self):
        client = Client("localhost", 14900)
        client.npcs[7] = {'id': 7, 'x': 1.0, 'y': 1.0, '_level': 'foo.nw'}

        data = _move_packet(npc_id=7, pos_x8=20, pos_y8=24,
                             dx_units=0, dy_units=0,
                             time_increments=10, options=0)
        client._handle_packet(PacketID.PLO_MOVE, data)

        assert client.npcs[7]['x'] == 20 * 8 / 16.0
        assert client.npcs[7]['y'] == 24 * 8 / 16.0
        assert 7 in client.npc_moves
        assert client.npc_moves[7]['duration_ms'] == 10 * 50

    def test_fires_on_npc_move_callback(self):
        client = Client("localhost", 14900)
        seen = []
        client.on_npc_move = seen.append

        data = _move_packet(npc_id=3, pos_x8=0, pos_y8=0,
                             dx_units=0, dy_units=0,
                             time_increments=0, options=0)
        client._handle_packet(PacketID.PLO_MOVE, data)

        assert len(seen) == 1
        assert seen[0]['npc_id'] == 3

    def test_move_is_registered_handled(self):
        assert int(PacketID.PLO_MOVE) in HANDLED_PLO_IDS


# =============================================================================
# PLO_NPCDEL2 (150) - parse_npcdel2
# =============================================================================

def _npcdel2_packet(level, npc_id):
    b = PacketBuilder()
    b.write_gstring(level)
    b.write_gint3(npc_id)
    return b.build()


class TestParseNpcDel2:
    def test_decodes_level_and_id(self):
        info = parse_npcdel2(_npcdel2_packet("chicken.nw", 99))
        assert info['level'] == "chicken.nw"
        assert info['npc_id'] == 99


# =============================================================================
# PLO_NPCDEL2 (150) wired into Client._handle_packet
# =============================================================================

class TestClientHandlesNpcDel2:
    def test_removes_from_live_roster_and_fires_callback(self):
        client = Client("localhost", 14900)
        client.npcs[5] = {'id': 5, '_level': 'other.nw'}
        deleted = []
        client.on_npc_del = deleted.append

        client._handle_packet(PacketID.PLO_NPCDEL2, _npcdel2_packet("other.nw", 5))

        assert 5 not in client.npcs
        assert deleted == [5]

    def test_purges_stale_per_level_cache(self):
        # This is the whole reason the server scopes the delete to a level:
        # a client that visited 'other.nw' in the past has it cached, even
        # though it's not currently on that level (so not in self.npcs).
        client = Client("localhost", 14900)
        client._npc_cache["other.nw"] = {5: {'id': 5, '_level': 'other.nw'}}

        client._handle_packet(PacketID.PLO_NPCDEL2, _npcdel2_packet("other.nw", 5))

        assert 5 not in client._npc_cache["other.nw"]

    def test_unknown_npc_id_is_a_harmless_no_op(self):
        client = Client("localhost", 14900)
        client._handle_packet(PacketID.PLO_NPCDEL2, _npcdel2_packet("nowhere.nw", 123))
        assert client.npcs == {}

    def test_npcdel2_is_registered_handled(self):
        assert int(PacketID.PLO_NPCDEL2) in HANDLED_PLO_IDS


# =============================================================================
# PLO_UNKNOWN168 (168) - blank login-complete marker
# =============================================================================

class TestClientHandlesLoginComplete:
    def test_sets_flag_and_fires_callback(self):
        client = Client("localhost", 14900)
        assert client.login_complete is False
        fired = []
        client.on_login_complete = lambda: fired.append(True)

        client._handle_packet(PacketID.PLO_UNKNOWN168, b"")

        assert client.login_complete is True
        assert fired == [True]

    def test_missing_callback_does_not_raise(self):
        client = Client("localhost", 14900)
        client._handle_packet(PacketID.PLO_UNKNOWN168, b"")
        assert client.login_complete is True


# =============================================================================
# PLO_NPCACTION (26) / PLO_GHOSTTEXT (173) - never sent by GServer-v2, stay
# unhandled (verified: no sendPacket call for either exists in server/src;
# they only appear in Player.cpp's packet-name enum table).
# =============================================================================

def test_npcaction_and_ghosttext_intentionally_unhandled():
    assert int(PacketID.PLO_NPCACTION) not in HANDLED_PLO_IDS
    assert int(PacketID.PLO_GHOSTTEXT) not in HANDLED_PLO_IDS


def test_unknown190_is_a_harmless_noop_and_stays_unregistered_sender_side():
    # GServer-v2 never sends packet 190 either (no sendPacket call anywhere
    # in server/src), but the client still no-ops safely if some other
    # server implementation does.
    client = Client("localhost", 14900)
    client._handle_packet(PacketID.PLO_UNKNOWN190, b"")  # must not raise
