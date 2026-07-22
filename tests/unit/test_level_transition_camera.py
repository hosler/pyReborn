"""Discrete level transitions hold the old view until the new board arrives."""

import pygame

from pyreborn import Client
from pyreborn.game import render as render_module
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


def test_link_touch_holds_through_old_stream_until_destination_board():
    client = _client(x=10.0, y=10.0)
    client.player.direction = 0
    client.links["outside.nw"] = [{
        "dest_level": "inside.nw", "x": 11, "y": 11,
        "width": 1, "height": 1, "dest_x": "5", "dest_y": "6",
    }]
    view = _CameraHarness(client, 10.0, 10.0)
    original_tiles = client.tiles

    link = client.check_link_collision()
    assert link is not None
    assert client.use_link(link)
    assert client._local_level_transition == "inside.nw"
    assert client._protocol.sent[-1][0] == PacketID.PLI_LEVELWARP

    # A board response queued before the link warp must be cached without
    # becoming active or releasing the held old view.
    client._handle_packet(PacketID.PLO_LEVELNAME, b"outside.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board(3))
    assert client._current_level_name == "inside.nw"
    assert client.tiles is original_tiles
    assert client._local_level_transition == "inside.nw"
    view._update_visual_position(1.0)
    assert (view.visual_x, view.visual_y) == (10.0, 10.0)

    # pygserver sends destination LEVELNAME, raw board, then PLAYERWARP.
    client._handle_packet(PacketID.PLO_LEVELNAME, b"inside.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board(4))
    assert client._tiles_level_name == "inside.nw"
    assert client._local_level_transition == ""


def test_authoritative_playerwarp_releases_rejected_transition():
    client = _client()
    client.warp_to_level("missing.nw", 5.0, 6.0)
    client._handle_packet(PacketID.PLO_LEVELNAME, b"outside.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board())
    assert client._local_level_transition == "missing.nw"

    client._handle_packet(
        PacketID.PLO_PLAYERWARP,
        bytes((int(30.0 * 2) + 32, int(30.0 * 2) + 32)) + b"outside.nw")
    assert client._current_level_name == "outside.nw"
    assert client._local_level_transition == ""


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


_GMAP_FILE = (
    "GRMAP001\n"
    "WIDTH 2\n"
    "HEIGHT 1\n"
    "LEVELNAMES\n"
    '"west.nw","east.nw",\n'
    "LEVELNAMESEND\n"
)


def test_gmap_reentry_holds_until_world_frame_is_reestablished():
    """Leaving an interior back onto a gmap segment: the destination board
    arriving is NOT enough - the grid was dropped by _exit_gmap, so a release
    at that point snaps the camera in the standalone LOCAL frame and the
    .gmap reload then jumps it again into world coordinates (live-traced
    double jump). The hold must survive until the grid is rebuilt."""
    client = _client(level="house.nw", x=29.5, y=38.0)
    # The session saw the gmap earlier; entering the house dropped the grid.
    client.load_gmap(_GMAP_FILE)
    client._exit_gmap("house.nw")
    assert client.gmap_width == 0
    assert "east.nw" in client._known_gmap_segments
    view = _CameraHarness(client, 29.5, 38.0)

    assert client.warp_to_level("east.nw", 10.5, 25.0)
    assert client._local_level_transition == "east.nw"

    # Destination board becomes active - previously the release point.
    client._handle_packet(PacketID.PLO_LEVELNAME, b"east.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board())
    assert client._tiles_level_name == "east.nw"
    assert client._local_level_transition == "east.nw", \
        "hold must survive the local interim frame of a gmap re-entry"
    view._update_visual_position(1.0)
    assert (view.visual_x, view.visual_y) == (29.5, 38.0)

    # The .gmap reload re-establishes the world frame: release + snap.
    client._gmap_spawn_x, client._gmap_spawn_y = 1, 0
    client.load_gmap(_GMAP_FILE)
    assert client.in_gmap_segment
    assert client._local_level_transition == ""
    assert (client.player.x, client.player.y) == (64 + 10.5, 25.0)
    view._update_visual_position(0.001)
    assert (view.visual_x, view.visual_y) == (64 + 10.5, 25.0)


def test_transition_to_plain_level_still_releases_on_board():
    """A destination that was never a gmap segment keeps the old behavior:
    active board = presentable, release immediately."""
    client = _client()
    client.load_gmap(_GMAP_FILE)
    client._exit_gmap("outside.nw")
    client.warp_to_level("inside.nw", 5.0, 6.0)
    client._handle_packet(PacketID.PLO_LEVELNAME, b"inside.nw")
    client._handle_packet(PacketID.PLO_BOARDPACKET, _board())
    assert client._local_level_transition == ""


def _edge_link(direction):
    links = (
        {"x": 20, "y": 0, "width": 2, "height": 1,
         "dest_x": "20", "dest_y": "60"},
        {"x": 0, "y": 20, "width": 1, "height": 2,
         "dest_x": "60", "dest_y": "20"},
        {"x": 20, "y": 62, "width": 2, "height": 1,
         "dest_x": "20", "dest_y": "1"},
        {"x": 62, "y": 20, "width": 1, "height": 2,
         "dest_x": "1", "dest_y": "20"},
    )
    return {"dest_level": "next.nw", **links[direction]}


def test_edge_link_inference_matches_all_walk_directions():
    for direction in range(4):
        client = _client()
        client.player.direction = direction
        link = _edge_link(direction)
        assert client.use_link(link)
        assert client._local_level_transition_direction == direction


def test_ambiguous_door_and_wrong_destination_edge_do_not_slide():
    client = _client()
    client.player.direction = 3
    door = {"dest_level": "inside.nw", "x": 20, "y": 20,
            "width": 2, "height": 2, "dest_x": "1", "dest_y": "20"}
    assert client.use_link(door)
    assert client._local_level_transition_direction is None

    client = _client()
    client.player.direction = 3
    wrong_edge = _edge_link(3)
    wrong_edge["dest_x"] = "30"
    assert client.use_link(wrong_edge)
    assert client._local_level_transition_direction is None


def test_dead_player_link_warp_never_arms_slide():
    client = _client()
    client.player.direction = 3
    client.player.hearts = 0
    assert client.use_link(_edge_link(3))
    assert client._local_level_transition
    assert client._local_level_transition_direction is None


class _ViewportStub:
    def __init__(self):
        self.presented = 0

    def present(self):
        self.presented += 1


class _SlideHarness(RenderMixin):
    def __init__(self, client):
        self.client = client
        self.screen = pygame.Surface((40, 30))
        self.screen.fill((10, 20, 30))
        self._transition_scene_frame = self.screen.copy()
        self.viewport = _ViewportStub()
        self.camera = type("Camera", (), {"zoom": 1.0})()
        self.scene_renders = 0

    def _sync_camera(self):
        pass

    def _render_scene(self):
        self.scene_renders += 1
        self.screen.fill((80, 90, 100))

    def _check_and_render_signs(self):
        pass

    def _render_ui(self):
        pass

    def _render_combat_presentation(self):
        pass


def test_renderer_state_machine_hold_slide_done(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(render_module.time, "monotonic", lambda: clock[0])
    client = _client()
    client.player.direction = 3
    assert client.use_link(_edge_link(3))
    client._local_level_transition_started = clock[0]
    view = _SlideHarness(client)

    view._render()
    assert view._transition_frame is not None
    assert view.scene_renders == 0

    client._tiles_level_name = "next.nw"
    client._maybe_release_local_transition()
    clock[0] += 0.01
    view._render()
    assert view._level_transition_slide is not None
    assert view._level_transition_input_frozen
    assert view.scene_renders == 1

    clock[0] += view.TRANSITION_SLIDE_S + 0.001
    view._render()
    assert getattr(view, '_level_transition_slide', None) is None
    assert not view._level_transition_input_frozen


def test_renderer_hold_timeout_fails_open_without_slide(monkeypatch):
    clock = [20.0]
    monkeypatch.setattr(render_module.time, "monotonic", lambda: clock[0])
    client = _client()
    client.player.direction = 3
    assert client.use_link(_edge_link(3))
    client._local_level_transition_started = clock[0]
    view = _SlideHarness(client)
    view._render()

    clock[0] += view.TRANSITION_HOLD_MAX_S + 0.01
    view._render()
    assert client._local_level_transition == ""
    assert getattr(view, '_level_transition_slide', None) is None
    assert view.scene_renders == 1


def test_renderer_slide_timeout_fails_open():
    client = _client()
    view = _SlideHarness(client)
    view._level_transition_input_frozen = True
    view._level_transition_slide = {
        "source": view.screen.copy(), "destination": view.screen.copy(),
        "direction": 3, "started": 1.0,
    }
    assert not view._draw_transition_slide(2.01)
    assert view._level_transition_slide is None
    assert not view._level_transition_input_frozen
