"""The liftable-object table, transcribed from the reference client.

Every row here is checkable against
Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp, so a typo in a tile id is
a test failure rather than an object that silently stops being liftable. The
rules under test are the ones the old hand-tagged tile-type overlay got wrong:

  * glove power is an INDEX CEILING into the table, not a per-object cost;
  * all four tiles must match, at any of the four alignments;
  * lifting writes the row's own replacement tiles.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from pyreborn.liftobjects import (
    BUSH_OBJECTS, BUSH_REPLACE, LIFT_OBJECTS, LIFT_REPLACE, LIFT_SPRITES,
    is_lift_tile, match_bush, match_lift_object, max_lift_index,
)


def _board(pattern, ox=10, oy=10, fill=77):
    """A reader over a 64x64 board holding one object at (ox, oy).

    The table is column-major: (0,0), (0,1), (1,0), (1,1).
    """
    tiles = {}
    for i, (dx, dy) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        tiles[(ox + dx, oy + dy)] = pattern[i]
    return lambda x, y: tiles.get((x, y), fill)


def test_the_tables_line_up():
    assert len(LIFT_OBJECTS) == len(LIFT_REPLACE) == len(LIFT_SPRITES) == 5
    assert len(BUSH_OBJECTS) == len(BUSH_REPLACE) == 2
    assert all(len(row) == 4 for row in LIFT_OBJECTS + LIFT_REPLACE)
    assert all(0 <= tile < 4096 for row in LIFT_OBJECTS for tile in row)
    assert all(0 <= tile < 4096 for row in LIFT_REPLACE for tile in row)


def test_glove_power_is_an_index_ceiling():
    """`for (i = 0; i <= getGlovePower() + 1; ++i)` (TPlayer.cpp:1945).

    So a bare hand already reaches row 1, and the ceiling clamps to the table
    rather than running off the end for a high glove.
    """
    assert max_lift_index(0) == 1
    assert max_lift_index(1) == 2
    assert max_lift_index(3) == 4
    assert max_lift_index(99) == len(LIFT_OBJECTS) - 1
    assert max_lift_index(-5) == 0


def test_every_row_matches_at_every_alignment():
    for index, pattern in enumerate(LIFT_OBJECTS):
        read = _board(pattern)
        for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1)):
            match = match_lift_object(read, 10 + dx, 10 + dy, glove_power=3)
            assert match is not None, f"row {index} missed at {(dx, dy)}"
            assert match.index == index
            assert (match.origin_x, match.origin_y) == (10, 10)
            assert match.replacement == LIFT_REPLACE[index]
            assert match.carry_sprite == LIFT_SPRITES[index]


def test_three_of_four_tiles_is_not_an_object():
    read_full = _board(LIFT_OBJECTS[0])
    assert match_lift_object(read_full, 10, 10, 3) is not None

    broken = dict()
    for i, (dx, dy) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        broken[(10 + dx, 10 + dy)] = LIFT_OBJECTS[0][i]
    del broken[(11, 11)]
    assert match_lift_object(lambda x, y: broken.get((x, y), 77),
                             10, 10, 3) is None


def test_a_row_above_the_ceiling_never_matches():
    read = _board(LIFT_OBJECTS[4])
    assert match_lift_object(read, 10, 10, glove_power=2) is None
    assert match_lift_object(read, 10, 10, glove_power=3) is not None


def test_quadrants_pair_each_tile_with_its_replacement():
    match = match_lift_object(_board(LIFT_OBJECTS[2]), 10, 10, 3)
    assert match is not None
    quadrants = match.quadrants()
    assert [(x, y) for x, y, _, _ in quadrants] == [
        (10, 10), (10, 11), (11, 10), (11, 11)]
    assert [current for _, _, current, _ in quadrants] == list(LIFT_OBJECTS[2])
    assert [new for _, _, _, new in quadrants] == list(LIFT_REPLACE[2])


def test_the_bush_table_is_its_own_set():
    """A sword cuts `bushobj`; a hand lifts `liftobj`. They overlap in one row.

    Row 1 of the bush table has no lift entry at all, so a client that treats
    "cuttable" and "liftable" as one set either lifts something the reference
    cannot, or refuses to cut something it can.
    """
    assert BUSH_OBJECTS[0] == LIFT_OBJECTS[0]
    assert BUSH_OBJECTS[1] not in LIFT_OBJECTS

    read = _board(BUSH_OBJECTS[1])
    assert match_bush(read, 10, 10) == (1, 10, 10)
    assert match_lift_object(read, 10, 10, glove_power=3) is None


def test_is_lift_tile_is_only_a_prefilter():
    assert is_lift_tile(LIFT_OBJECTS[0][0], glove_power=0) is True
    assert is_lift_tile(LIFT_OBJECTS[4][0], glove_power=0) is False
    assert is_lift_tile(LIFT_OBJECTS[4][0], glove_power=3) is True
    assert is_lift_tile(77) is False
