"""Gmap level names are compared without regard to case.

The reference server lower-cases every name it puts in the map grid
(GServer-v2 server/src/level/Map.cpp:67-68, :154, :193, :337) and the
reference client lower-cases the name it looks up (FourPlay
quattroplay/src/unsorted.cpp:1014-1020, TClient.cpp:1281-1282, :1354). A
server may therefore announce a level in another case than the .gmap file
spells it.

Design: the grid and the per-level stores keep the spelling they were given
(the grid's goes back to the server in PLI_ADJACENTLEVEL, so it must not
change), and every comparison between them goes through
`pyreborn.gmap_coords.fold` (ASCII `lower()`). `_known_gmap_segments` holds
folded names.
"""

from offline_game import GMAP_SEGMENTS, sent_player_props
from pyreborn.gmap_coords import (
    fold, get_ci, grid_index, grid_of, has_level, in_grid, same_level,
)
from pyreborn.handlers.level import handle_level_name
from pyreborn.packets import PacketID

GMAPLEVELX = 43
WARP_IDS = (int(PacketID.PLI_LEVELWARP), int(PacketID.PLI_LEVELWARPMOD))
A, B, C, D = GMAP_SEGMENTS


def _open(tx, ty):
    return 0


def _warps(client, mark):
    return [pid for pid, _ in client._protocol.sent[mark:] if pid in WARP_IDS]


def test_helpers_ignore_case():
    """Mutation: make `fold` return the name unchanged -> every row fails."""
    grid = {(0, 0): "Foo.nw", (1, 0): "bar.nw"}
    assert grid_of(grid, "FOO.NW") == (0, 0)
    assert in_grid(grid, "BAR.nw") and not in_grid(grid, "baz.nw")
    assert same_level("A.nw", "a.NW") and not same_level("a.nw", "b.nw")
    assert get_ci({"Foo.nw": 7}, "FOO.nw") == 7 and has_level({"x": 1}, "X")
    index = grid_index(grid)
    assert index.get("FOO.nw") == (0, 0) and "Bar.NW" in index
    assert fold("A.Nw") == "a.nw"


def test_a_walked_seam_is_a_hop_when_the_grid_and_the_held_board_differ_in_case(
        make_client):
    """The grid spells the neighbour in upper case, the held board is keyed by
    the server's spelling: crossing still sends props and no warp.

    Mutation: use `to_level in self.levels` / `from_level != to_level` in
    `_is_gmap_hop` (exact compare) -> a warp is sent instead."""
    client = make_client(gmap=True, player_xy=(62.5, 30.0), tiles=_open)
    assert B in client.levels
    client.gmap_grid[(1, 0)] = B.upper()
    mark = len(client._protocol.sent)
    for _ in range(4):
        assert client.move(1, 0, step=0.5)
    assert client.current_level_name == B.upper()
    assert _warps(client, mark) == []
    assert any(prop == GMAPLEVELX for pairs in
               sent_player_props(client._protocol.sent[mark:])
               for prop, _ in pairs)


def test_a_current_level_in_another_case_is_still_a_gmap_segment(make_client):
    """Mutation: compare `self._current_level_name in self.gmap_grid.values()`
    exactly in `in_gmap_segment` -> False."""
    client = make_client(gmap=True, tiles=_open)
    client._current_level_name = A.upper()
    assert client.in_gmap_segment


def test_a_warp_to_a_segment_in_another_case_is_not_a_level_change(make_client):
    """warp_to_level into a segment spelled differently than the grid keeps the
    gmap convention (`player.level` stays the .gmap name).

    Mutation: test `level_name not in self.gmap_grid.values()` in
    `warp_to_level` -> player.level becomes the segment's name."""
    client = make_client(gmap=True, tiles=_open)
    before = client.player.level
    assert client.warp_to_level(B.upper(), 5.0, 6.0)
    assert client.player.level == before


def test_an_adjacent_preload_answered_in_another_case_is_still_a_preload(
        make_client):
    """The request carries the grid's spelling; the server's PLO_LEVELNAME may
    differ in case. It must still be taken as the answer to the request.

    Mutation: use `level_name in client._adjacent_level_requests` in
    `handle_level_name` -> the answer is a level change and the request stays."""
    client = make_client(gmap=True, tiles=_open)
    client._adjacent_level_requests.add("Fixture_Far.nw")
    handle_level_name(client, b"fixture_far.nw")
    assert client._adjacent_level_requests == set()
    assert client._pending_board_level_name == "fixture_far.nw"


def test_the_adjacent_request_keeps_the_spelling_the_grid_gave(make_client):
    """What is sent TO the server is the grid's own spelling, never a folded
    one; only comparisons fold.

    Mutation: lower-case the name in `request_level` -> the bytes differ."""
    client = make_client(gmap=True, tiles=_open)
    client.gmap_grid[(1, 0)] = "Fixture_B.NW"
    client.levels.pop(B, None)
    client._adjacent_level_requests.clear()
    mark = len(client._protocol.sent)
    assert client.request_level("Fixture_B.NW")
    sent = [d for pid, d in client._protocol.sent[mark:]
            if pid == int(PacketID.PLI_ADJACENTLEVEL)]
    assert len(sent) == 1 and sent[0].endswith(b"Fixture_B.NW")


def test_a_held_board_in_another_case_is_not_requested_again(make_client):
    """Mutation: test `level_name not in self.levels` in
    `request_adjacent_levels` -> the held neighbour is requested again."""
    client = make_client(gmap=True, tiles=_open)
    client._adjacent_level_requests.clear()
    client.gmap_grid[(1, 0)] = B.upper()
    assert B in client.levels
    mark = len(client._protocol.sent)
    client.request_adjacent_levels()
    sent = [d for pid, d in client._protocol.sent[mark:]
            if pid == int(PacketID.PLI_ADJACENTLEVEL)]
    assert not any(d.endswith(B.upper().encode()) for d in sent)


def test_known_segments_are_folded(make_client):
    """Mutation: store the raw names in `load_gmap` -> an upper-case probe of
    the folded set misses."""
    client = make_client(gmap=True, tiles=_open)
    assert fold(B.upper()) in client._known_gmap_segments
