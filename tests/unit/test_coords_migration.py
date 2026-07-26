"""The coordinate-frame call sites now routed through reborn_protocol.coords.

Every site here used to re-derive `math.floor(x/64)` / `x % 64` / `ly*64+lx`
inline. These tests pin the *behaviour* at the places that historically broke
(segment boundaries, negative world coords, the 63->64 rollover) so the shared
implementation can't silently drift from what the call sites expect.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from reborn_protocol.coords import LEVEL_SIZE

from pyreborn import Client
from pyreborn.game.camera import Camera2D
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.minimap import map_entity_positions
from pyreborn.game.render_objects import LevelObjectsRenderMixin
from pyreborn.packets import PacketID


# Same 3x3 chicken.gmap layout the rest of this suite uses
# (tests/unit/test_collision_gmap_frames.py): chicken1.nw at grid (1, 1).
_NAMES = [
    "chicken4.nw", "chicken5.nw", "chicken6.nw",
    "chicken2.nw", "chicken1.nw", "chicken7.nw",
    "chicken3.nw", "chicken9.nw", "chicken8.nw",
]


class _Stub:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data):
        self.sent.append((packet_id, data))
        return True


def _client():
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _Stub()
    return c


def _gmap_client():
    c = _client()
    c.gmap_width, c.gmap_height = 3, 3
    for i, name in enumerate(_NAMES):
        c.gmap_grid[(i % 3, i // 3)] = name
    c._current_level_name = "chicken1.nw"
    c.levels["chicken1.nw"] = [0] * 4096
    c.tiles = c.levels["chicken1.nw"]
    c._tiles_level_name = "chicken1.nw"
    return c


class _Harness(CollisionMixin, LevelObjectsRenderMixin):
    def __init__(self, client):
        self.client = client
        self.tile_corrections = {}


# =============================================================================
# Client: world position -> gmap segment
# =============================================================================

class TestCurrentLevelFromPosition:
    @pytest.mark.parametrize("wx,wy,expected", [
        (0.0, 0.0, "chicken4.nw"),          # grid (0, 0)
        (63.9375, 63.9375, "chicken4.nw"),  # last tile before the seam
        (64.0, 64.0, "chicken1.nw"),        # exactly on the seam -> next cell
        (64.0, 0.0, "chicken5.nw"),
        (191.5, 191.5, "chicken8.nw"),      # grid (2, 2)
    ])
    def test_segment_lookup_at_boundaries(self, wx, wy, expected):
        c = _gmap_client()
        c.player.x, c.player.y = wx, wy
        assert c.get_current_level_from_position() == expected

    def test_negative_world_position_floors_off_the_grid(self):
        """floor(-0.5/64) == -1, so a position just left of the gmap origin is
        in cell (-1, 0) — not (0, 0) the way int() truncation would say."""
        c = _gmap_client()
        c.player.x, c.player.y = -0.5, 0.0
        # (-1, 0) is not in the grid, so the current level name stands.
        assert c.get_current_level_from_position() == "chicken1.nw"


class TestMoveSeamCrossing:
    def test_crossing_a_seam_announces_the_new_segment(self):
        """A step from world x=63.9 to 64.15 crosses grid (0,1) -> (1,1), so
        move() must re-home us on chicken1.nw."""
        c = _gmap_client()
        c._current_level_name = "chicken2.nw"
        c.player.x, c.player.y = 63.9, 70.0
        assert c.move(1, 0, step=0.25) is True
        assert c.player.x == pytest.approx(64.15)
        assert c._current_level_name == "chicken1.nw"

    def test_no_seam_crossing_inside_one_segment(self):
        c = _gmap_client()
        c.player.x, c.player.y = 70.0, 70.0
        assert c.move(1, 0, step=0.25) is True
        assert c._current_level_name == "chicken1.nw"

    def test_seam_crossing_sends_local_coords_not_world(self):
        """The LEVELWARP that announces the crossing carries local (0-63)
        coords: world 64.15 -> local 0.15, encoded as a gchar half-tile."""
        c = _gmap_client()
        c._current_level_name = "chicken2.nw"
        c.player.x, c.player.y = 63.9, 70.0
        c.move(1, 0, step=0.25)
        warps = [d for pid, d in c._protocol.sent
                 if pid == PacketID.PLI_LEVELWARP]
        assert len(warps) == 1
        # build_level_warp: byte = int(coord*2) + 32
        assert warps[0][0] == int(0.15 * 2) + 32
        assert warps[0][1] == int(6.0 * 2) + 32


# =============================================================================
# Client: level board indexing
# =============================================================================

class TestLevelIndexing:
    def test_get_tile_reads_row_major(self):
        c = _client()
        c.tiles = [0] * 4096
        c.tiles[7 * LEVEL_SIZE + 3] = 99
        assert c.get_tile(3, 7) == 99

    @pytest.mark.parametrize("x,y", [(-1, 0), (0, -1), (64, 0), (0, 64)])
    def test_get_tile_out_of_bounds_is_zero(self, x, y):
        c = _client()
        c.tiles = [5] * 4096
        assert c.get_tile(x, y) == 0

    def test_board_modify_patches_the_right_cells(self):
        c = _client()
        c.levels["a.nw"] = [0] * 4096
        c._tiles_level_name = "a.nw"
        c.tiles = c.levels["a.nw"]
        c._apply_board_modify("a.nw", {
            'layer': 0, 'x': 2, 'y': 3, 'width': 2, 'height': 2,
            'tiles': [11, 12, 13, 14],
        })
        board = c.levels["a.nw"]
        assert board[3 * LEVEL_SIZE + 2] == 11
        assert board[3 * LEVEL_SIZE + 3] == 12
        assert board[4 * LEVEL_SIZE + 2] == 13
        assert board[4 * LEVEL_SIZE + 3] == 14


# =============================================================================
# Collision: world -> level-local, only on a gmap
# =============================================================================

class TestWorldToLevelLocal:
    def test_gmap_wraps_into_the_owning_segment(self):
        c = _gmap_client()
        h = _Harness(c)
        assert h._world_to_level_local(64 + 5.3, 128 + 6.7) == (5, 6)

    def test_gmap_negative_world_uses_floor_then_wrap(self):
        """floor(-1.5) == -2, and -2 % 64 == 62 — one tile left of what
        int(-1.5) % 64 == 63 would give."""
        c = _gmap_client()
        h = _Harness(c)
        assert h._world_to_level_local(-1.5, -1.5) == (62, 62)

    def test_standalone_level_does_not_wrap(self):
        c = _client()
        c._current_level_name = "a.nw"
        c.levels["a.nw"] = [0] * 4096
        h = _Harness(c)
        assert h._world_to_level_local(-1.5, 70.0) == (-2, 70)
        # ...and an off-board probe reads as out-of-world, not the far column.
        assert h._get_tile_at(-1.5, 5.0) == -1

    def test_tile_lookup_crosses_a_seam_into_the_neighbour(self):
        c = _gmap_client()
        c.levels["chicken2.nw"] = [0] * 4096      # grid (0, 1)
        c.levels["chicken2.nw"][5 * LEVEL_SIZE + 63] = 77
        h = _Harness(c)
        # World (63.5, 64 + 5.5) is the last column of grid (0, 1).
        assert h._get_tile_at(63.5, 64 + 5.5) == 77

    def test_gmap_perimeter_blocks(self):
        c = _gmap_client()
        h = _Harness(c)
        assert h._is_blocked_at(-0.5, 10.0) is True
        assert h._is_blocked_at(3 * LEVEL_SIZE + 0.5, 10.0) is True
        assert h._is_blocked_at(10.0, 10.0) is False


# =============================================================================
# Segment origins used by the renderers
# =============================================================================

class TestSegmentOrigin:
    def test_current_segment_origin_on_a_gmap(self):
        c = _gmap_client()
        h = _Harness(c)
        assert h._current_segment_origin() == (64, 64)

    def test_current_segment_origin_standalone_is_zero(self):
        c = _client()
        c._current_level_name = "a.nw"
        h = _Harness(c)
        assert h._current_segment_origin() == (0, 0)


class TestMinimapPositions:
    def test_remote_player_local_coords_fold_into_the_world_span(self):
        c = _gmap_client()
        c.player.x, c.player.y = 64.0, 64.0
        c.players[7] = {'x': 32.0, 'y': 32.0, 'level': "chicken8.nw"}
        points = list(map_entity_positions(c))
        span = 3 * LEVEL_SIZE
        assert points[0][:2] == (64.0 / span, 64.0 / span)
        # chicken8.nw is grid (2, 2): local 32 -> world 160.
        assert points[1][:2] == (160.0 / span, 160.0 / span)

    def test_standalone_span_is_one_segment(self):
        c = _client()
        c.player.x, c.player.y = 32.0, 16.0
        points = list(map_entity_positions(c))
        assert points[0][:2] == (0.5, 0.25)


# =============================================================================
# Camera transform, forward and inverse
# =============================================================================

class TestCameraTransform:
    def test_centre_maps_to_screen_centre(self):
        cam = Camera2D(640, 480, 16)
        cam.set_center(35.5, 30.5)
        assert cam.world_to_screen(35.5, 30.5) == (320.0, 240.0)

    @pytest.mark.parametrize("zoom", [0.5, 1.0, 2.0])
    def test_screen_to_world_round_trips(self, zoom):
        cam = Camera2D(640, 480, 16)
        cam.zoom = zoom
        cam.set_center(35.5, 30.5)
        for wx, wy in ((0, 0), (35.5, 30.5), (-4.25, 200.75)):
            sx, sy = cam.world_to_screen(wx, wy)
            rx, ry = cam.screen_to_world(sx, sy)
            assert (rx, ry) == pytest.approx((wx, wy))

    def test_render_offset_shifts_pixels_not_the_centre(self):
        cam = Camera2D(640, 480, 16)
        cam.set_center(35.5, 30.5)
        cam.set_render_offset(3.0, -2.0)
        assert cam.world_to_screen(35.5, 30.5) == (323.0, 238.0)
        assert cam.center == (35.5, 30.5)

    def test_visible_tile_range_brackets_the_view(self):
        cam = Camera2D(640, 480, 16)
        cam.set_center(32.0, 32.0)
        assert cam.visible_tile_range() == (12, 17, 52, 47)

    def test_visible_tile_range_floors_negative_edges(self):
        cam = Camera2D(640, 480, 16)
        cam.set_center(2.0, 2.0)
        min_tx, min_ty, _, _ = cam.visible_tile_range()
        assert (min_tx, min_ty) == (-18, -13)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
