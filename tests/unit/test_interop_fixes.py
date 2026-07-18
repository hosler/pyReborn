"""Regression tests for client interop fixes vs the real GServer (gs2emu).

Covers the 2026-07-05 playtest findings:
1. PLPROP_MAXPOWER is FULL hearts on the wire (CURPOWER is halves) -
   GServer-v2 PlayerProps.cpp:171-186 / LevelItem.cpp:148-151.
2. PLO_WARPFAILED must restore the pre-warp state (warp_to_level flips
   level/pos optimistically).
3. PLO_PRIVATEMESSAGE bodies are toCSV(force_quoted=True) tokenized
   (StringUtils.h:895) - the quote wrappers must be stripped.
4. Bomb/arrow ammo is client-authoritative: fire must decrement locally,
   report the new count, and refuse at 0.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import (
    PacketID,
    parse_player_props,
    parse_private_message,
    build_bomb_count,
    build_arrow_count,
)


def _props_packet(*pairs):
    """Assemble a raw props payload from (prop_id, value_byte) pairs."""
    out = bytearray()
    for pid, val in pairs:
        out.append(pid + 32)
        out.append(val + 32)
    return bytes(out)


class TestMaxPowerDecode:
    """MAXPOWER(1) is whole hearts; CURPOWER(2) is half-hearts."""

    def test_maxpower_is_full_hearts(self):
        # gs2emu fullheart pickup: MAXPOWER=6, CURPOWER=12 => 6.0 / 6.0
        props = parse_player_props(_props_packet((1, 6), (2, 12)))
        assert props['max_hearts'] == 6.0
        assert props['hearts'] == 6.0

    def test_fresh_account_three_hearts(self):
        # Observed live from gs2emu (fresh account, MAXHP 3): raw bytes
        # MAXPOWER=3, CURPOWER=6.
        props = parse_player_props(_props_packet((1, 3), (2, 6)))
        assert props['max_hearts'] == 3.0
        assert props['hearts'] == 3.0


class TestPrivateMessageParse:
    """PM bodies arrive CSV-tokenized with every line force-quoted."""

    def _pm(self, body, sender=3):
        data = bytes([((sender >> 7) & 0x7F) + 32, (sender & 0x7F) + 32])
        return data + body.encode('latin-1')

    def test_gs2emu_player_pm(self):
        # GServer constructs '#bPrivate message:#b<msg>' then force-quotes
        # each line: '"","Private message:","hello there"'
        info = parse_private_message(self._pm('"","Private message:","hello there"'))
        assert info['from_id'] == 3
        assert info['type'] == 'Private message:'
        assert info['message'] == 'hello there'

    def test_gs2emu_multiline_pm(self):
        info = parse_private_message(
            self._pm('"","Private message:","line one","line two"'))
        assert info['message'] == 'line one\nline two'

    def test_npcserver_welcome_no_header(self):
        # NPC-server script PMs have no '<type>:' header - just quoted lines.
        info = parse_private_message(self._pm('"Welcome to the server!"'))
        assert info['type'] == ''
        assert info['message'] == 'Welcome to the server!'

    def test_server_message_header_first_field(self):
        # 'Server Message:#bFrom jail...' => header in field 0.
        info = parse_private_message(
            self._pm('"Server Message:","From jail you can only send PMs to admins (RCs)."'))
        assert info['type'] == 'Server Message:'
        assert info['message'].startswith('From jail')

    def test_escaped_quotes_and_backslashes(self):
        # toCSV doubles '"' and '\' inside quoted fields.
        info = parse_private_message(
            self._pm('"","Private message:","say ""hi"" c:\\\\path"'))
        assert info['message'] == 'say "hi" c:\\path'

    def test_pygserver_raw_tail_keeps_commas(self):
        # pygserver sends the message part unquoted; a comma in it must not
        # be split/rewritten.
        info = parse_private_message(
            self._pm('"sender","Private message:",hello, world'))
        assert info['type'] == 'Private message:'
        assert info['message'] == 'hello, world'


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


class TestAmmoClientAuthoritative:
    def test_put_bomb_decrements_and_reports(self):
        c = _fake_connected_client()
        c.player.bombs = 3
        assert c.put_bomb(30, 30) is True
        assert c.player.bombs == 2
        assert (int(PacketID.PLI_PLAYERPROPS), build_bomb_count(2)) in c._protocol.sent

    def test_put_bomb_refuses_at_zero(self):
        c = _fake_connected_client()
        c.player.bombs = 0
        assert c.put_bomb(30, 30) is False
        assert c._protocol.sent == []
        assert c.player.bombs == 0

    def test_shoot_arrow_decrements_and_reports(self):
        c = _fake_connected_client()
        c.player.arrows = 5
        assert c.shoot_arrow(30, 30, direction=2) is True
        assert c.player.arrows == 4
        assert (int(PacketID.PLI_PLAYERPROPS), build_arrow_count(4)) in c._protocol.sent

    def test_shoot_arrow_refuses_at_zero(self):
        c = _fake_connected_client()
        c.player.arrows = 0
        assert c.shoot_arrow(30, 30, direction=2) is False
        assert c._protocol.sent == []

    def test_server_echo_reconciles_prediction(self):
        # pygserver echoes the authoritative BOMBSCOUNT after PLI_BOMBADD;
        # the echo is an absolute value equal to the prediction, so applying
        # it must not double-decrement.
        c = _fake_connected_client()
        c.player.bombs = 3
        c.put_bomb(30, 30)
        assert c.player.bombs == 2
        c._handle_packet(PacketID.PLO_PLAYERPROPS, _props_packet((5, 2)))
        assert c.player.bombs == 2


class TestWarpFailedRestore:
    def _client_in_level(self, level="qa_testlevel.nw", x=30.0, y=30.0):
        c = _fake_connected_client()
        c._current_level_name = level
        c._pending_level_name = level
        c.player.x = x
        c.player.y = y
        c.levels[level] = [0] * 4096
        c.tiles = c.levels[level]
        c._tiles_level_name = level
        return c

    def test_rejected_warp_restores_prior_state(self):
        c = self._client_in_level()
        assert c.warp_to_level("bogus_nonexistent.nw", 5.0, 5.0) is True
        # Optimistic flip happened...
        assert c._current_level_name == "bogus_nonexistent.nw"
        # ...server rejects it (gs2emu sends the failed level name).
        c._handle_packet(PacketID.PLO_WARPFAILED, b"bogus_nonexistent.nw")
        assert c._current_level_name == "qa_testlevel.nw"
        assert c.player.x == 30.0
        assert c.player.y == 30.0
        assert c._awaiting_warp_confirm == ""
        assert c._warp_fallback is None
        assert c._tiles_level_name == "qa_testlevel.nw"

    def test_confirmed_warp_clears_fallback(self):
        c = self._client_in_level()
        c.warp_to_level("qa_tier3.nw", 10.0, 10.0)
        assert c._warp_fallback is not None
        # Server confirms with PLO_LEVELNAME.
        c._handle_packet(PacketID.PLO_LEVELNAME, b"qa_tier3.nw")
        assert c._warp_fallback is None
        assert c._current_level_name == "qa_tier3.nw"

    def test_stray_warpfailed_is_ignored(self):
        c = self._client_in_level()
        c._handle_packet(PacketID.PLO_WARPFAILED, b"whatever.nw")
        assert c._current_level_name == "qa_testlevel.nw"

    @staticmethod
    def _x2y2_props(x_tiles, y_tiles):
        def enc(v):
            raw = int(v * 16) << 1
            return bytes([((raw >> 7) & 0x7F) + 32, (raw & 0x7F) + 32])
        return bytes([78 + 32]) + enc(x_tiles) + bytes([79 + 32]) + enc(y_tiles)

    def test_gs2emu_silent_rejection_via_position_reanchor(self):
        # gs2emu sends NO PLO_WARPFAILED for a bad PLI_LEVELWARP - it
        # re-warps same-level, which emits only X2/Y2 self props (observed
        # live; GServer-v2 PlayerClientPackets.cpp:92-98 +
        # PlayerClient.cpp:1198-1218). That must also restore the pre-warp
        # level, with the server-sent position applied.
        c = self._client_in_level(x=30.0, y=30.5)
        c.warp_to_level("bogus_nonexistent.nw", 5.0, 5.0)
        assert c._current_level_name == "bogus_nonexistent.nw"
        c._handle_packet(PacketID.PLO_PLAYERPROPS, self._x2y2_props(30.0, 30.5))
        assert c._current_level_name == "qa_testlevel.nw"
        assert c.player.x == 30.0
        assert c.player.y == 30.5
        assert c._awaiting_warp_confirm == ""
        assert c._warp_fallback is None

    def test_props_without_position_do_not_trigger_restore(self):
        # A non-position props packet (e.g. a hearts echo) racing the warp
        # confirm must NOT be misread as a rejection.
        c = self._client_in_level()
        c.warp_to_level("qa_tier3.nw", 10.0, 10.0)
        c._handle_packet(PacketID.PLO_PLAYERPROPS, _props_packet((2, 6)))
        assert c._current_level_name == "qa_tier3.nw"
        assert c._awaiting_warp_confirm == "qa_tier3.nw"

    def test_pygserver_rejection_levelname_reanchor_clears_pending(self):
        # pygserver rejects a bad warp with PLAYERWARP + a re-send of the
        # OLD level (name+board). The LEVELNAME re-announcement must clear
        # the pending-warp state even though it doesn't match the target.
        c = self._client_in_level()
        c.warp_to_level("bogus_nonexistent.nw", 5.0, 5.0)
        c._handle_packet(PacketID.PLO_LEVELNAME, b"qa_testlevel.nw")
        assert c._current_level_name == "qa_testlevel.nw"
        assert c._awaiting_warp_confirm == ""
        assert c._warp_fallback is None


class TestGmapAdjacentPreloadLevelName:
    """Regression for the spawn-level mislabel bug: pygserver's
    PLI_ADJACENTLEVEL handler (player.py _handle_adjacent_level) streams a
    neighbouring GMAP segment's [PLO_LEVELNAME, board] for stitched rendering
    without ever moving the player and without a PLO_PLAYERWARP2 - the same
    PLO_LEVELNAME wire shape a genuine warp/spawn uses. The client used to
    trust every PLO_LEVELNAME("*.nw") that names a loaded gmap segment as "we
    are now here", so request_adjacent_levels() (called right after the .gmap
    downloads) would leave _current_level_name pointing at whichever neighbour
    preloaded last - e.g. spawning into chicken1.nw (world (94, 94.5), grid
    (1, 1)) but ending up reporting chicken8.nw (grid (2, 2)) even though the
    NPCs/chests that streamed in were chicken1.nw's.
    """

    def _client_with_grid(self):
        # 3x3 grid matching funtimes' chicken.gmap layout.
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

    def test_adjacent_preload_does_not_relabel_current_level(self):
        c = self._client_with_grid()
        c._current_level_name = "chicken1.nw"
        c._pending_level_name = "chicken1.nw"
        c.player.x, c.player.y = 94.0, 94.5  # world coords, grid (1, 1)

        # Adjacent-preload push for a diagonal neighbour: PLO_LEVELNAME alone,
        # no PLO_PLAYERWARP2 (pygserver never sends one for a preload).
        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken8.nw")

        assert c._current_level_name == "chicken1.nw"
        # Board-attribution target still moves so the incoming tiles land
        # under the right level.
        assert c._pending_level_name == "chicken8.nw"

    def test_adjacent_preload_of_every_neighbour_leaves_level_alone(self):
        # request_adjacent_levels() fires one PLI_ADJACENTLEVEL per neighbour;
        # simulate all 8 responses landing after the real spawn segment.
        c = self._client_with_grid()
        c._current_level_name = "chicken1.nw"
        c.player.x, c.player.y = 94.0, 94.5
        for name in ["chicken4.nw", "chicken5.nw", "chicken6.nw", "chicken2.nw",
                     "chicken7.nw", "chicken3.nw", "chicken9.nw", "chicken8.nw"]:
            c._handle_packet(PacketID.PLO_LEVELNAME, name.encode('latin-1'))
        assert c._current_level_name == "chicken1.nw"

    def test_real_gmap_warp_still_updates_current_level(self):
        # A genuine server-initiated warp within the gmap (RC teleport,
        # respawn, scripted setlevel2) always follows PLO_LEVELNAME with
        # PLO_PLAYERWARP2 - that packet is the authoritative "we moved"
        # signal and must still relabel the current level.
        c = self._client_with_grid()
        c._current_level_name = "chicken1.nw"
        c._pending_level_name = "chicken1.nw"
        c.player.x, c.player.y = 94.0, 94.5

        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken6.nw")
        # PLO_PLAYERWARP2: x, y, z, gmap_x, gmap_y (each gchar) + level name.
        # Target is grid (2, 0) -> local (10, 12) half-tiles = *2.
        warp2 = bytes([10 * 2 + 32, 12 * 2 + 32, 0 + 32, 2 + 32, 0 + 32]) + b"chicken6.nw"
        c._handle_packet(PacketID.PLO_PLAYERWARP2, warp2)

        assert c._current_level_name == "chicken6.nw"

    def test_first_gmap_segment_announcement_still_sets_level(self):
        # Before the .gmap grid loads (gmap_width == 0), the client can't yet
        # tell an adjacent-preload apart from a real transition by segment
        # membership - this path (login's very first PLO_LEVELNAME) must
        # still work exactly as before: unconditional assignment + reset.
        c = _fake_connected_client()
        assert c.gmap_width == 0
        c._handle_packet(PacketID.PLO_LEVELNAME, b"chicken1.nw")
        assert c._current_level_name == "chicken1.nw"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


class TestPlayerLeftRoster:
    """JOINLEAVELVL=0 in PLO_OTHERPLPROPS removes the player from the level
    roster (the server's leave notification; without handling it, departed
    players linger as ghosts at their last position)."""

    @staticmethod
    def _leave_packet(player_id):
        # [gshort id][prop 50][value 0], gchar-encoded (+32)
        return bytes([(player_id >> 7) + 32, (player_id & 0x7F) + 32, 50 + 32, 0 + 32])

    def test_leave_removes_player(self):
        c = _fake_connected_client()
        c.players[7] = {"id": 7, "x": 25.0, "y": 27.0}
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, self._leave_packet(7))
        assert 7 not in c.players

    def test_leave_fires_callback(self):
        c = _fake_connected_client()
        c.players[7] = {"id": 7, "x": 25.0, "y": 27.0}
        left = []
        c.on_player_left = left.append
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, self._leave_packet(7))
        assert left == [7]

    def test_leave_for_unknown_player_is_noop(self):
        c = _fake_connected_client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, self._leave_packet(9))
        assert 9 not in c.players


class TestSwordGmapSegmentFrame:
    """Sword hit tests must fold the attacker's gmap segment offset into
    target positions: self.player.x/y are world coords while the players
    dict carries wire-local (0-63) coords. Live repro: attacker at world
    (84,94) on chicken1.nw never hit a target it saw at (20,31.5)."""

    def test_hits_target_on_nonzero_segment(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 84.0, 94.0      # local (20,30) + segment (1,1)*64
        c.players[3] = {"id": 3, "x": 20.0, "y": 31.5}  # wire-local, same level
        hits = []
        c.attack_player = lambda pid, **kw: hits.append(pid)
        c._sword_hit_players(2)  # facing down, gap 1.5 -> must hit
        assert hits == [3]

    def test_still_hits_on_origin_segment(self):
        c = _fake_connected_client()
        c.player.x, c.player.y = 20.0, 30.0
        c.players[3] = {"id": 3, "x": 20.0, "y": 31.5}
        hits = []
        c.attack_player = lambda pid, **kw: hits.append(pid)
        c._sword_hit_players(2)
        assert hits == [3]
