"""pyreborn.gmap_coords: the one gmap grid lookup and wire-to-world helper set.

Grids used below, in load_gmap's row-major insertion order:

* SQUARE  3x3, the chicken.gmap shape.
* WIDE    3x2 (non-square), with a duplicated name in two cells.
* SINGLE  1x1.
"""

import math

import pytest
from hypothesis import given, strategies as st

from reborn_protocol.coords import LEVEL_SIZE

from pyreborn.gmap_coords import (
    grid_index, grid_of, level_at, level_origin, local_from_world, origin_at,
    position_is_local, world_from_local, world_from_wire,
)


def _grid(width, names):
    return {(i % width, i // width): name for i, name in enumerate(names)}


SQUARE = _grid(3, [f"c{i}.nw" for i in range(9)])
WIDE = _grid(3, ["a.nw", "dup.nw", "b.nw", "c.nw", "dup.nw", "Mixed.nw"])
SINGLE = _grid(1, ["only.nw"])
INTERIOR = "house.nw"       # a door target that is in no grid


@pytest.mark.parametrize("grid, level, expected", [
    (SQUARE, "c0.nw", (0, 0)),
    (SQUARE, "c4.nw", (1, 1)),
    (SQUARE, "c8.nw", (2, 2)),             # outer rim, far corner
    (SQUARE, "c2.nw", (2, 0)),             # outer rim, right edge
    (WIDE, "Mixed.nw", (2, 1)),            # non-square, last cell
    (WIDE, "dup.nw", (1, 0)),              # duplicate: first cell, row-major
    (WIDE, "mixed.nw", (2, 1)),            # case-insensitive by default
    (SINGLE, "only.nw", (0, 0)),
    (SQUARE, INTERIOR, None),              # gmap loaded, interior level
    (SQUARE, "", None),
    (SQUARE, None, None),
    ({}, "c0.nw", None),                   # no gmap loaded
    (None, "c0.nw", None),
])
def test_grid_of(grid, level, expected):
    assert grid_of(grid, level) == expected


def test_grid_of_exact_when_asked():
    assert grid_of(WIDE, "mixed.nw", casefold=False) is None


@pytest.mark.parametrize("grid, level, expected", [
    (WIDE, "mixed.nw", (2, 1)),
    (WIDE, "MIXED.NW", (2, 1)),
    (WIDE, "DUP.nw", (1, 0)),
    (WIDE, INTERIOR, None),
    ({}, "a.nw", None),
])
def test_grid_of_casefold(grid, level, expected):
    assert grid_of(grid, level, casefold=True) == expected


@pytest.mark.parametrize("grid, casefold, expected", [
    (WIDE, False, {"a.nw": (0, 0), "dup.nw": (1, 0), "b.nw": (2, 0),
                   "c.nw": (0, 1), "Mixed.nw": (2, 1)}),
    (WIDE, True, {"a.nw": (0, 0), "dup.nw": (1, 0), "b.nw": (2, 0),
                  "c.nw": (0, 1), "mixed.nw": (2, 1)}),
    (SINGLE, False, {"only.nw": (0, 0)}),
    ({}, False, {}),
    (None, False, {}),
])
def test_grid_index_first_cell_wins(grid, casefold, expected):
    index = grid_index(grid, casefold=casefold)
    assert index == expected
    for name in (grid or {}).values():
        key = name.casefold() if casefold else name
        assert index[key] == grid_of(grid, name, casefold=casefold)


@pytest.mark.parametrize("grid, x, y, expected", [
    (SQUARE, 0.0, 0.0, "c0.nw"),
    (SQUARE, 63.9375, 63.9375, "c0.nw"),
    (SQUARE, 64.0, 0.0, "c1.nw"),          # seam: the right side owns 64
    (SQUARE, 191.9375, 191.9375, "c8.nw"),  # outer rim
    (SQUARE, 192.0, 10.0, None),           # one past the rim
    (SQUARE, -0.0625, 10.0, None),         # floor, not truncation
    (SQUARE, 10.0, -64.0, None),
    (WIDE, 130.0, 70.0, "Mixed.nw"),
    (WIDE, 10.0, 130.0, None),             # below a non-square grid
    (SINGLE, 63.5, 0.0, "only.nw"),
    (SINGLE, 64.0, 0.0, None),
    ({}, 10.0, 10.0, None),
    (None, 10.0, 10.0, None),
])
def test_level_at(grid, x, y, expected):
    assert level_at(grid, x, y) == expected


@pytest.mark.parametrize("grid, level, expected", [
    (SQUARE, "c4.nw", (64, 64)),
    (SQUARE, "c8.nw", (128, 128)),
    (WIDE, "Mixed.nw", (128, 64)),
    (WIDE, "dup.nw", (64, 0)),
    (SINGLE, "only.nw", (0, 0)),
    (SQUARE, INTERIOR, (0, 0)),
    ({}, "c4.nw", (0, 0)),
    (None, "c4.nw", (0, 0)),
])
def test_level_origin(grid, level, expected):
    assert level_origin(grid, level) == expected


@pytest.mark.parametrize("x, y, expected", [
    (0.0, 0.0, (0, 0)),
    (63.9375, 64.0, (0, 64)),
    (-0.0625, -64.0, (-64, -64)),
    (-64.0625, 130.5, (-128, 128)),
])
def test_origin_at_floors(x, y, expected):
    assert origin_at(x, y) == expected


@pytest.mark.parametrize("grid, level, local, world", [
    (SQUARE, "c4.nw", (10.5, 20.0), (74.5, 84.0)),
    (SQUARE, "c4.nw", (70.25, -1.5), (134.25, 62.5)),   # past an edge, unwrapped
    (SQUARE, "c8.nw", (63.9375, 63.9375), (191.9375, 191.9375)),
    (WIDE, "Mixed.nw", (0.0, 0.0), (128.0, 64.0)),
    (SINGLE, "only.nw", (-3.0, 66.0), (-3.0, 66.0)),
    (SQUARE, INTERIOR, (30.0, 30.0), (30.0, 30.0)),     # interior: own frame
    ({}, "c4.nw", (30.0, 30.0), (30.0, 30.0)),
    (None, "c4.nw", (30.0, 30.0), (30.0, 30.0)),
])
def test_world_from_local_and_back(grid, level, local, world):
    assert world_from_local(grid, level, *local) == world
    assert local_from_world(grid, level, *world) == local


@pytest.mark.parametrize("raw, origin, expected", [
    (10.0, 64, 74.0),          # local: origin added
    (0.0, 128, 128.0),
    (63.9375, 64, 127.9375),
    (64.0, 64, 128.0),         # just past the east edge: still local
    (70.25, 64, 134.25),
    (-0.5, 64, 63.5),          # just past the west edge: still local
    (10.0, 0, 10.0),           # cell (0, 0)
])
def test_world_from_wire(raw, origin, expected):
    """NPC X2/Y2 are always local (NPC.h:702-703); the client adds the cell
    origin whatever the value (TServerNPC.cpp:330). Mutation: restore the
    "outside 0..63 is world" pass-through and the edge rows fail."""
    assert world_from_wire(raw, origin) == expected


@pytest.mark.parametrize("x, y, expected", [
    (30.0, 30.0, True),
    (-1.5, 63.5, True),
    (64.0, 10.0, False),
    (10.0, 64.0, False),
    (130.0, 70.0, False),
])
def test_position_is_local(x, y, expected):
    assert position_is_local(x, y) is expected


# -- properties ---------------------------------------------------------------

# Wire positions are multiples of 1/16 tile. LEVELWARP bounds them to
# [-16, 111.5] (client_warp.WARP_COORD_MIN/MAX); keep a margin either side.
_wire = st.integers(min_value=-32 * 16, max_value=128 * 16).map(lambda p: p / 16)
_local_on_board = st.integers(min_value=0, max_value=64 * 16 - 1).map(lambda p: p / 16)
_grids = st.sampled_from([SQUARE, WIDE, SINGLE])


@given(_grids, st.data(), _wire, _wire)
def test_local_world_local_round_trip(grid, data, x, y):
    level = data.draw(st.sampled_from(sorted(set(grid.values()))))
    world = world_from_local(grid, level, x, y)
    assert local_from_world(grid, level, *world) == (x, y)


@given(_grids, st.data(), _local_on_board, _local_on_board)
def test_world_of_an_on_board_local_lands_in_its_level(grid, data, x, y):
    level = data.draw(st.sampled_from(sorted(set(grid.values()))))
    world = world_from_local(grid, level, x, y)
    # A duplicated name resolves to its first cell, so it maps back to the
    # same name (whichever of its cells the position is in).
    assert level_at(grid, *world) == level
    assert origin_at(*world) == level_origin(grid, level)


@given(st.integers(min_value=0, max_value=20), _wire)
def test_world_from_wire_is_local_plus_origin(cell, raw):
    """Every wire value, on the board or past its edge, is local: world
    minus the origin gives the wire value back."""
    origin = cell * LEVEL_SIZE
    assert world_from_wire(raw, origin) - origin == raw


@given(_wire, _wire)
def test_origin_at_matches_floor(x, y):
    assert origin_at(x, y) == (math.floor(x / 64) * 64, math.floor(y / 64) * 64)


# -- call-site frame gating on a real Client ------------------------------------

def _client(current, x, y, grid=SQUARE):
    from pyreborn import Client
    c = Client("localhost", 14900)
    c.gmap_grid.update(grid)
    c.gmap_width, c.gmap_height = 3, 3
    c.gmap_name = "world.gmap"
    c._current_level_name = current
    c.player.x, c.player.y = x, y
    return c


def test_segment_player_resolves_through_the_grid():
    c = _client("c4.nw", 100.0, 70.0)
    assert c.in_gmap_segment
    assert c.get_current_level_from_position() == "c4.nw"
    assert c._level_world_origin("c8.nw") == (128, 128)
    assert c.get_adjacent_levels("c0.nw") == ["c3.nw", "c1.nw", "c4.nw"]


def test_interior_with_a_loaded_grid_stays_in_its_own_frame():
    # The optimistic warp into a door target flips the current level before
    # the server's PLO_LEVELNAME clears the grid (_exit_gmap). In that window
    # is_gmap is True but the player's coordinates are the interior's own.
    c = _client(INTERIOR, 30.0, 30.0)
    assert c.is_gmap and not c.in_gmap_segment
    assert c.get_current_level_from_position() == INTERIOR
    assert c._level_world_origin("c8.nw") == (0, 0)
    assert c.get_adjacent_levels(INTERIOR) == []


def test_no_gmap_loaded():
    from pyreborn import Client
    c = Client("localhost", 14900)
    c._current_level_name = "plain.nw"
    c.player.x, c.player.y = 30.0, 30.0
    assert not c.is_gmap and not c.in_gmap_segment
    assert c.get_current_level_from_position() == "plain.nw"
    assert c._level_world_origin("plain.nw") == (0, 0)


def test_update_npc_world_coords_places_local_values():
    """Every wire value is local to its cell, including one past the
    segment edge, and a re-run does not add the origin again."""
    c = _client("c4.nw", 100.0, 70.0)
    c.npcs = {
        1: {'_level': "c4.nw", 'x': 10.0, 'y': 20.0},            # local
        2: {'_level': "c4.nw", 'x': 70.0, 'y': -1.5},            # past the edges
        3: {'gmaplevelx': 2, 'gmaplevely': 1, 'x': 1.0, 'y': 2.0},
        4: {'_level': INTERIOR, 'x': 5.0, 'y': 5.0},             # not a segment
    }
    c._update_npc_world_coords()
    assert (c.npcs[1]['world_x'], c.npcs[1]['world_y']) == (74.0, 84.0)
    assert (c.npcs[2]['world_x'], c.npcs[2]['world_y']) == (134.0, 62.5)
    assert (c.npcs[3]['world_x'], c.npcs[3]['world_y']) == (129.0, 66.0)
    assert c.npcs[3]['_level'] == "c5.nw"
    assert 'world_x' not in c.npcs[4]
    # A second run (grid reloaded) must not double the offset.
    c._update_npc_world_coords()
    assert (c.npcs[1]['world_x'], c.npcs[1]['world_y']) == (74.0, 84.0)
