"""Discrete level transitions hold the old view until the new board arrives."""

from pyreborn import Client
from pyreborn.game.render import RenderMixin
from pyreborn.packets import PacketID


class _ProtocolStub:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data):
        self.sent.append((packet_id, data))
        return True


class _CameraHarness(RenderMixin):
    def __init__(self, client, x, y):
        self.client = client
        self.visual_x = x
        self.visual_y = y
        self.follow_speed = 24.0
        self._seen_level_transition_epoch = (
            client._local_level_transition_epoch)


def _client(level="outside.nw", x=30.0, y=30.0):
    client = Client("localhost", 14900)
    client._protocol = _ProtocolStub()
    client._authenticated = True
    client._current_level_name = level
    client._pending_level_name = level
    client.player.x = x
    client.player.y = y
    client.tiles = [1] * 4096
    client.levels[level] = client.tiles
    client._tiles_level_name = level
    return client


def _board(tile_id=2):
    encoded = bytes((tile_id & 0xff, (tile_id >> 8) & 0xff))
    return encoded * 4096


def test_camera_holds_and_player_is_suppressed_while_board_is_pending():
    client = _client()
    view = _CameraHarness(client, 30.0, 30.0)

    assert client.warp_to_level("inside.nw", 5.0, 6.0)
    assert (client.player.x, client.player.y) == (5.0, 6.0)
    assert client._local_level_transition == "inside.nw"

    view._update_visual_position(1.0)
    assert (view.visual_x, view.visual_y) == (30.0, 30.0)
    # EntityRenderMixin uses this same dedicated signal to omit the local
    # sprite while the held old-level view is on screen.
    assert client._local_level_transition


def test_camera_snaps_without_lerp_when_destination_board_arrives():
    client = _client(x=5.0, y=5.0)
    view = _CameraHarness(client, 5.0, 5.0)
    client.warp_to_level("inside.nw", 5.5, 5.5)

    client._handle_packet(PacketID.PLO_LEVELNAME, b"inside.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board())
    assert client._tiles_level_name == "inside.nw"
    assert client._local_level_transition == ""

    # A 0.5-tile change would normally interpolate for this tiny dt. The
    # completion epoch must force an exact transition snap instead.
    view._update_visual_position(0.001)
    assert (view.visual_x, view.visual_y) == (5.5, 5.5)


def test_same_level_position_warp_does_not_hold_camera():
    client = _client(x=10.0, y=10.0)
    view = _CameraHarness(client, 10.0, 10.0)

    assert client.warp_to_level("outside.nw", 40.0, 41.0)
    assert client._local_level_transition == ""
    view._update_visual_position(0.001)
    assert (view.visual_x, view.visual_y) == (40.0, 41.0)


def test_gmap_segment_crossing_remains_continuous():
    client = _client(level="west.nw", x=63.75, y=20.0)
    client.gmap_grid = {(0, 0): "west.nw", (1, 0): "east.nw"}
    client.gmap_width = 2
    client.gmap_height = 1

    assert client.move(1, 0, step=0.5)
    assert client._current_level_name == "east.nw"
    assert client._local_level_transition == ""

