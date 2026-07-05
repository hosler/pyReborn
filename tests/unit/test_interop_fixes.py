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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
