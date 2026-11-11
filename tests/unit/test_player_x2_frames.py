"""Player X2/Y2 (78/79) are LEVEL-LOCAL pixels, resolved against the player's
own gmap segment.

The reference server stores and relays the value it received unchanged
(GServer-v2 beta4 server/src/player/PlayerProps.cpp, the X2/Y2 setters store
`account.character.localPixelX/Y`); the segment travels separately in
GMAPLEVELX/Y (43/44). The decompiled reference client computes world as
local + (mapX << 6) (FourPlay TPlayer.cpp). A local just past a segment edge
(70.25, -1.5) is legitimate and is relayed as-is, so the decode must take the
frame from the prop, never from the value's magnitude.
"""

import pytest
from reborn_protocol.coords import local_to_world

from pyreborn import Client
from pyreborn.packets import PacketID


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _gshort(v):
    return bytes([((v >> 7) & 0x7F) + 32, (v & 0x7F) + 32])


def _pixel_pos(prop_id, tiles):
    pixels = int(round(tiles * 16))
    value = ((-pixels) << 1) | 1 if pixels < 0 else pixels << 1
    return bytes([prop_id + 32, ((value >> 7) & 0x7F) + 32, (value & 0x7F) + 32])


def _byte_prop(prop_id, v):
    return bytes([prop_id + 32, v + 32])


def _grid(gx, gy):
    return _byte_prop(43, gx) + _byte_prop(44, gy)


def _other(pid, *parts):
    return _gshort(pid) + b"".join(parts)


def _client(gmap=True, level="chicken1.nw"):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    if gmap:
        names = ["chicken4.nw", "chicken5.nw", "chicken6.nw",
                 "chicken2.nw", "chicken1.nw", "chicken7.nw",
                 "chicken3.nw", "chicken9.nw", "chicken8.nw"]
        c.gmap_width, c.gmap_height = 3, 3
        for i, name in enumerate(names):
            c.gmap_grid[(i % 3, i // 3)] = name
    c._current_level_name = level
    return c


EDGE_LOCALS = [70.25, -1.5]


class TestOtherPlayerEdgeLocals:
    @pytest.mark.parametrize("local", EDGE_LOCALS)
    def test_x_edge_local_resolves_against_players_segment(self, local):
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(1, 1), _pixel_pos(78, local), _pixel_pos(79, 30.0)))
        p = c.players[5]
        assert p['x'] == local
        assert (p['world_x'], p['world_y']) == local_to_world(local, 30.0, 1, 1)

    @pytest.mark.parametrize("local", EDGE_LOCALS)
    def test_y_edge_local_resolves_against_players_segment(self, local):
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(1, 1), _pixel_pos(78, 30.0), _pixel_pos(79, local)))
        p = c.players[5]
        assert p['y'] == local
        assert (p['world_x'], p['world_y']) == local_to_world(30.0, local, 1, 1)

    @pytest.mark.parametrize("local", EDGE_LOCALS)
    def test_other_segment_than_ours(self, local):
        c = _client()   # we stand on (1, 1); they are on (2, 0)
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(2, 0), _pixel_pos(78, local), _pixel_pos(79, local)))
        p = c.players[5]
        assert (p['world_x'], p['world_y']) == local_to_world(local, local, 2, 0)

    def test_same_segment_in_range(self):
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(1, 1), _pixel_pos(78, 33.25), _pixel_pos(79, 33.25)))
        p = c.players[5]
        assert (p['x'], p['y']) == (33.25, 33.25)
        assert (p['world_x'], p['world_y']) == (97.25, 97.25)

    def test_later_x2_only_update_uses_the_known_segment(self):
        # The reference relays a move as X2/Y2 alone, no grid props.
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(1, 1), _pixel_pos(78, 30.0), _pixel_pos(79, 30.0)))
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _pixel_pos(78, 70.25)))
        p = c.players[5]
        assert (p['world_x'], p['world_y']) == local_to_world(70.25, 30.0, 1, 1)

    def test_segment_unknown_leaves_world_unset_then_resolves(self):
        # X2 arrives before any grid prop: the frame is local, but the
        # segment is not known yet, so no world position is guessed.
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _pixel_pos(78, 70.25), _pixel_pos(79, 97.25)))
        p = c.players[5]
        assert (p['x'], p['y']) == (70.25, 97.25)
        assert p.get('world_x') is None and p.get('world_y') is None
        # The grid props arrive later on their own.
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(5, _grid(0, 1)))
        assert (p['world_x'], p['world_y']) == local_to_world(70.25, 97.25, 0, 1)

    def test_segment_change_moves_world_with_it(self):
        c = _client()
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(1, 1), _pixel_pos(78, 63.5), _pixel_pos(79, 30.0)))
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _grid(2, 1), _pixel_pos(78, 0.0)))
        p = c.players[5]
        assert (p['world_x'], p['world_y']) == local_to_world(0.0, 30.0, 2, 1)

    def test_single_level_has_no_world_frame_and_no_wrap(self):
        c = _client(gmap=False, level="onlinestartlocal.nw")
        c._handle_packet(PacketID.PLO_OTHERPLPROPS, _other(
            5, _pixel_pos(78, 30.5), _pixel_pos(79, 40.0)))
        p = c.players[5]
        assert (p['x'], p['y']) == (30.5, 40.0)
        assert p.get('world_x') is None and p.get('world_y') is None


class TestOwnPlayerEdgeLocals:
    @pytest.mark.parametrize("local", EDGE_LOCALS)
    def test_x_edge_local(self, local):
        c = _client()
        c._handle_packet(PacketID.PLO_PLAYERPROPS,
                         _pixel_pos(78, local) + _pixel_pos(79, 30.0))
        assert (c.player.x, c.player.y) == local_to_world(local, 30.0, 1, 1)

    @pytest.mark.parametrize("local", EDGE_LOCALS)
    def test_y_edge_local(self, local):
        c = _client()
        c._handle_packet(PacketID.PLO_PLAYERPROPS,
                         _pixel_pos(78, 30.0) + _pixel_pos(79, local))
        assert (c.player.x, c.player.y) == local_to_world(30.0, local, 1, 1)

    def test_same_segment_in_range(self):
        c = _client()
        c._handle_packet(PacketID.PLO_PLAYERPROPS,
                         _pixel_pos(78, 33.25) + _pixel_pos(79, 33.25))
        assert (c.player.x, c.player.y) == (97.25, 97.25)

    def test_single_level(self):
        c = _client(gmap=False, level="onlinestartlocal.nw")
        c._handle_packet(PacketID.PLO_PLAYERPROPS,
                         _pixel_pos(78, 30.5) + _pixel_pos(79, 40.0))
        assert (c.player.x, c.player.y) == (30.5, 40.0)


class TestSeamStepEncodesHomeSegmentLocal:
    """The step that crosses a seam goes out local to the segment the server
    still homes us in (64.0, -0.5), like the reference client's getlocalx();
    wrapping it to the far edge of the OLD segment showed us a whole segment
    away to everyone else until the PLI_LEVELWARP landed."""

    @pytest.mark.parametrize("start, step, expect, level", [
        ((127.5, 96.0), (1, 0), (64.0, 32.0), "chicken7.nw"),
        ((64.0, 96.0), (-1, 0), (-0.5, 32.0), "chicken2.nw"),
        ((96.0, 127.5), (0, 1), (32.0, 64.0), "chicken9.nw"),
        ((96.0, 64.0), (0, -1), (32.0, -0.5), "chicken5.nw"),
    ])
    def test_crossing_step(self, start, step, expect, level):
        from pyreborn.packets import parse_player_props
        c = _client()
        c.player.x, c.player.y = start
        c._use_pixel_props = True
        assert c.move(*step, step=0.5)
        sent = c._protocol.sent
        props_packets = [d for pid, d in sent if pid == int(PacketID.PLI_PLAYERPROPS)]
        sent_props = parse_player_props(props_packets[0])
        assert (sent_props['x'], sent_props['y']) == expect
        assert int(PacketID.PLI_LEVELWARP) in [pid for pid, _ in sent]
        assert c._current_level_name == level

    def test_in_segment_step_is_plain_local(self):
        from pyreborn.packets import parse_player_props
        c = _client()
        c.player.x, c.player.y = 100.0, 100.0
        c._use_pixel_props = True
        assert c.move(1, 0, step=0.5)
        sent = c._protocol.sent
        assert [pid for pid, _ in sent] == [int(PacketID.PLI_PLAYERPROPS)]
        sent_props = parse_player_props(sent[0][1])
        assert (sent_props['x'], sent_props['y']) == (36.5, 36.0)
