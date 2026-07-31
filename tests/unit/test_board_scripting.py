"""Script-visible board state: movement-flag ownership and tiles[]/updateboard.

Two live LTTP (hastur:14912) client bugs, 2026-07-26:

1. `ClientGS1.clear()` (a LEVEL change) used to force default_movement back to
   True. The reference client only resets it at session boundaries (FourPlay
   quattroplay src/TPlayer.cpp:1549 resetAttributes / :5573 loadStartLevel,
   TServerPlayer.cpp:239 initPlayerVars) — never on a level change. LTTP's GS2
   -Player/Movement calls disabledefmovement ONCE in onCreated, so the first
   level announce re-enabled native movement, gated off the scripted-movement
   probe chain (gmap seam announces, link warps) and double-drove the player.

2. GS2 used a detached 64x64 LOCAL snapshot for `tiles[]`. World coords indexed
   out to None, and writes changed the copy. GS1 kept `tiles[]` read-only-local.
   `updateboard` did not exist. Both now route through the gmap-aware board
   helpers in gs1_client (board_tile_read/board_tile_write/
   board_update_region), frame math from reborn_protocol.coords, with writes
   going through Client._apply_board_modify + on_board_modify like a server
   delta. updateboard oracle: GServer-v2 GS1Commands.cpp:3560-3575.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.gs1_client import (
    ClientGS1, board_tile_read, board_tile_write, board_update_region,
    board_world_dims,
)
from pyreborn.gs2_client import ClientGS2, _BoardTilesColumn


def _client(level="house.nw", board_tile=0):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._current_level_name = level
    c.tiles = [board_tile] * 4096
    c._tiles_level_name = level
    c.levels[level] = c.tiles
    return c


def _gmap_client():
    """A 2x1 gmap has za.nw (segment 0,0, uniform tile 1) and zb.nw
    (segment 1,0, uniform tile 2). The player stands in za.nw."""
    c = Client("localhost", 14900)
    c._authenticated = True
    c.gmap_width = 2
    c.gmap_height = 1
    c.gmap_grid = {(0, 0): "za.nw", (1, 0): "zb.nw"}
    c._current_level_name = "za.nw"
    c.tiles = [1] * 4096
    c._tiles_level_name = "za.nw"
    c.levels["za.nw"] = c.tiles
    c.levels["zb.nw"] = [2] * 4096
    return c


def _record_modifies(c):
    infos = []
    c.on_board_modify = infos.append
    return infos


# =============================================================================
# 1. default_movement ownership: player/session-scoped, NOT level-scoped
# =============================================================================

def _run_weapon(gs1, src, event="timeout"):
    gs1.load_weapon("probe", "if (%s) { %s }" % (event, src))
    gs1.trigger_event(event, "weapon_probe")


def test_disabledefmovement_survives_a_level_change():
    gs1 = ClientGS1(_client())
    assert gs1.default_movement is True  # session start (initPlayerVars)
    _run_weapon(gs1, "disabledefmovement;")
    assert gs1.default_movement is False
    gs1.clear()  # level change: reference client does NOT reset the flag
    assert gs1.default_movement is False
    gs1.clear()  # nor on any later one
    assert gs1.default_movement is False


def test_enabledefmovement_is_the_only_script_path_back():
    gs1 = ClientGS1(_client())
    _run_weapon(gs1, "disabledefmovement;")
    gs1.clear()
    _run_weapon(gs1, "enabledefmovement;")
    assert gs1.default_movement is True
    # and the bomber shape: arena weapon disables again after the warp
    _run_weapon(gs1, "disabledefmovement;")
    assert gs1.default_movement is False


def test_fresh_session_starts_with_default_movement():
    # Our resetAttributes/loadStartLevel analog is a fresh ClientGS1 per
    # server connection (pygame_game.py builds a new GameClient per switch).
    gs1 = ClientGS1(_client())
    _run_weapon(gs1, "disabledefmovement;")
    assert ClientGS1(_client()).default_movement is True


# =============================================================================
# 2a. board helpers: frames
# =============================================================================

def test_world_dims_follow_the_frame():
    assert board_world_dims(_client()) == (64, 64)
    assert board_world_dims(_gmap_client()) == (128, 64)
    # on a gmap but inside a house (standalone level): local frame again
    c = _gmap_client()
    c._current_level_name = "house.nw"
    assert board_world_dims(c) == (64, 64)


def test_read_local_frame_in_level():
    c = _client(board_tile=7)
    assert board_tile_read(c, 10, 5) == 7.0
    assert board_tile_read(c, 64, 5) is None   # off-board
    assert board_tile_read(c, -1, 5) is None


def test_read_world_frame_on_gmap():
    c = _gmap_client()
    assert board_tile_read(c, 10, 5) == 1.0     # segment (0,0)
    assert board_tile_read(c, 70, 5) == 2.0     # segment (1,0), world x 70
    assert board_tile_read(c, 128, 5) is None   # outside the 2x1 world


def test_write_local_frame_patches_board_and_notifies_renderer():
    c = _client(board_tile=7)
    infos = _record_modifies(c)
    assert board_tile_write(c, 10, 5, 684) is True
    assert c.tiles[5 * 64 + 10] == 684
    assert c.levels["house.nw"][5 * 64 + 10] == 684
    assert infos == [{"layer": 0, "x": 10, "y": 5, "width": 1, "height": 1,
                      "tiles": [684]}]


def test_write_world_frame_hits_the_owning_segment():
    c = _gmap_client()
    infos = _record_modifies(c)
    assert board_tile_write(c, 70, 5, 684) is True
    assert c.levels["zb.nw"][5 * 64 + 6] == 684   # local (6, 5) of zb
    assert c.tiles[5 * 64 + 6] == 1               # za untouched
    assert infos[-1]["map_x"] == 1 and infos[-1]["map_y"] == 0
    assert infos[-1]["x"] == 6 and infos[-1]["y"] == 5
    # off-world / grid-hole writes are dropped, not misapplied
    assert board_tile_write(c, 128, 5, 684) is False
    assert board_tile_write(c, 10, 70, 684) is False


# =============================================================================
# 2b. updateboard: region redraw from board data
# =============================================================================

def test_updateboard_reblits_region_from_board():
    c = _client(board_tile=7)
    infos = _record_modifies(c)
    c.tiles[4 * 64 + 8] = 99  # an edit made behind the callback's back
    board_update_region(c, 8, 4, 2, 3)
    assert len(infos) == 1
    info = infos[0]
    assert (info["x"], info["y"], info["width"], info["height"]) == (8, 4, 2, 3)
    assert info["tiles"] == [99, 7, 7, 7, 7, 7]  # row-major from the board
    assert "map_x" not in info


def test_updateboard_clamps_at_zero_like_the_oracle():
    # fn_updateboard: std::max(0.0, arg) per argument (GS1Commands.cpp:3568+)
    c = _client(board_tile=7)
    infos = _record_modifies(c)
    board_update_region(c, -3, -2, 4, 4)
    assert (infos[0]["x"], infos[0]["y"]) == (0, 0)
    assert (infos[0]["width"], infos[0]["height"]) == (4, 4)
    infos.clear()
    board_update_region(c, 10, 10, -5, 3)   # w clamps to 0 -> empty region
    assert infos == []


def test_updateboard_spans_gmap_segments():
    c = _gmap_client()
    infos = _record_modifies(c)
    board_update_region(c, 62, 0, 4, 1)   # world x 62..65: za 62-63, zb 0-1
    assert len(infos) == 2
    by_map = {i["map_x"]: i for i in infos}
    assert by_map[0]["x"] == 62 and by_map[0]["width"] == 2
    assert by_map[0]["tiles"] == [1, 1]
    assert by_map[1]["x"] == 0 and by_map[1]["width"] == 2
    assert by_map[1]["tiles"] == [2, 2]


# =============================================================================
# 2c. GS1 script surface: tiles[x,y] read/write + updateboard command
# =============================================================================

def test_gs1_script_reads_writes_and_publishes_tiles():
    c = _client(board_tile=7)
    infos = _record_modifies(c)
    gs1 = ClientGS1(c)
    _run_weapon(gs1,
                "this.before = tiles[10,5];"
                "tiles[10,5] = 684;"
                "this.after = tiles[10,5];"
                "updateboard 8,4,4,4;")
    this = gs1._progs["weapon_probe"]["scopes"]["this"]
    assert this["before"] == 7.0
    assert this["after"] == 684.0            # read-your-write
    assert c.tiles[5 * 64 + 10] == 684
    # one 1x1 write patch + one 4x4 updateboard re-blit
    assert [(i["width"], i["height"]) for i in infos] == [(1, 1), (4, 4)]
    assert infos[1]["tiles"][0 * 4 + 2] == 7      # (8..11, 4..7) from board
    assert infos[1]["tiles"][1 * 4 + 2] == 684    # includes the new tile at (10,5)


def test_gs1_tiles_are_world_frame_on_gmap():
    c = _gmap_client()
    gs1 = ClientGS1(c)
    _run_weapon(gs1, "this.t = tiles[70,5]; tiles[70,5] = 99;")
    assert gs1._progs["weapon_probe"]["scopes"]["this"]["t"] == 2.0
    assert c.levels["zb.nw"][5 * 64 + 6] == 99


# =============================================================================
# 2d. GS2 tiles[] view: live, gmap-aware, VM-shaped
# =============================================================================

def _gs2(c):
    gs1 = ClientGS1(c)
    return ClientGS2(c, gs1=gs1)


def test_gs2_view_is_vm_compatible_and_live():
    # The VM's array ops gate on isinstance(list) and use len() bounds
    # (reborn_protocol/gs2/vm.py _op_array/_op_array_assign/_op_array_multidim*):
    # the view must satisfy exactly that surface.
    c = _client(board_tile=7)
    rt2 = _gs2(c)
    view = rt2.tiles_view()
    assert isinstance(view, list) and len(view) == 64
    col = view[10]
    assert isinstance(col, list) and len(col) == 64
    assert col[5] == 7.0
    c.tiles[5 * 64 + 10] = 99            # live: no snapshot to go stale
    assert view[10][5] == 99.0
    assert col[0:2] == [7.0, 7.0]        # slice form (subarray op)
    assert list(col)[5] == 99.0          # iteration


def test_gs2_view_write_hits_board_and_renderer():
    c = _client(board_tile=7)
    infos = _record_modifies(c)
    rt2 = _gs2(c)
    view = rt2.tiles_view()
    view[10][5] = 684        # the _op_array_assign path: arr[i] = value
    assert c.tiles[5 * 64 + 10] == 684
    assert infos and infos[0]["x"] == 10 and infos[0]["y"] == 5
    # out-of-board writes are dropped silently (old behavior: silent no-op)
    view[10][70] = 1
    assert len(infos) == 1


def test_gs2_view_is_world_frame_on_gmap():
    c = _gmap_client()
    rt2 = _gs2(c)
    view = rt2.tiles_view()
    assert len(view) == 128 and len(view[0]) == 64
    assert view[70][5] == 2.0            # LTTP-style world index
    view[70][5] = 99
    assert c.levels["zb.nw"][5 * 64 + 6] == 99
    # VM bounds: _op_array only builds an ElemRef for 0 <= i < len(arr), so
    # an off-world x (>=128) answers None in the VM rather than raising here.
    assert len(view) == 128


def test_gs2_view_rebuilds_when_the_frame_changes():
    c = _gmap_client()
    rt2 = _gs2(c)
    assert len(rt2.tiles_view()) == 128
    # door into a house: standalone level -> local 64x64 frame
    c._current_level_name = "house.nw"
    c.tiles = [5] * 4096
    c._tiles_level_name = "house.nw"
    c.levels["house.nw"] = c.tiles
    view = rt2.tiles_view()
    assert len(view) == 64
    assert view[10][5] == 5.0
    view[10][5] = 42
    assert c.tiles[5 * 64 + 10] == 42    # local write, not world


def test_gs2_column_multidim_shapes():
    # tiles[x, y] (one OP_ARRAY_MULTIDIM) reads arr[i] then row[j], and the
    # assign form checks isinstance(arr[i], list) before row[j] = v.
    c = _client(board_tile=7)
    rt2 = _gs2(c)
    view = rt2.tiles_view()
    row = view[10]
    assert isinstance(row, list)
    assert row[5] == 7.0
    row[5] = 684.0
    assert c.tiles[5 * 64 + 10] == 684


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
