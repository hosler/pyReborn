"""Where a server NPC sits on a gmap: its cell and its world position.

The reference client's rule (FourPlay quattroplay/src/):

* PLO_SETACTIVELEVEL names the level a new NPC joins
  (TClient.cpp:3777-3784, :2894-2922). A ``.gmap`` name makes the map the
  owner and the NPC keeps its own cell, starting at (0, 0)
  (TServerNPC.cpp:316-319, TLevelObject.cpp:28-31). A segment name copies
  that segment's cell (TServerNPC.cpp:321-324).
* NPC props 41/42 (GMAPLEVELX/Y) set the cell one axis at a time and 75/76
  (X2/Y2) the local position (TServerNPC.cpp:1271-1282, :1347-1362).
* The world position is ``(mapX << 6) + local``, whatever the local value
  (TServerNPC.cpp:330).

The packets are hand-built in the reference server's layout: PLO_NPCPROPS is
``{GINT3 id}`` then ``{GCHAR prop}{value}`` in ascending prop order, each
value encoded by reborn_protocol.props.encode_value from the NPC_PROPS table,
which mirrors GServer-v2 server/include/object/NPC.h (GMAPLEVELX/Y are
GBYTE1 at :668-669, X2/Y2 pixel coordinates at :702-703). PLO_SETACTIVELEVEL
is the raw level name (GServer-v2 server/src/level/Level.cpp:1455-1459) and
PLO_NPCMOVED ``{GINT3 id}{GCHAR x/8}{GCHAR y/8}{level}``
(GServer-v2 server/src/object/NPC.cpp:203-211).

The gmap is 3x3, ``chicken.gmap``, with segment (x, y) named ``s<x><y>.nw``.
"""

import pytest

from reborn_protocol.props import NPC_PROPS, encode_value

from pyreborn import Client
from pyreborn.packets import PacketID

GMAP = "chicken.gmap"
NPC = 12345           # a server-global id, as the reference server allocates

_BY_NAME = {d.name: d for d in NPC_PROPS.values()}


def _gint3(v):
    return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32,
                  (v & 0x7F) + 32])


def npc_props(npc_id, **props):
    """PLO_NPCPROPS body; keyword names are NPC_PROPS names (X2, GMAPLEVELX)."""
    pairs = sorted(((_BY_NAME[name], value) for name, value in props.items()),
                   key=lambda pair: pair[0].id)
    return _gint3(npc_id) + b"".join(
        bytes([desc.id + 32]) + encode_value(desc, value)
        for desc, value in pairs)


def seg(x, y):
    return f"s{x}{y}.nw"


def make_client(grid=True):
    c = Client("localhost", 14900)
    if grid:
        c.gmap_width, c.gmap_height = 3, 3
        for y in range(3):
            for x in range(3):
                c.gmap_grid[(x, y)] = seg(x, y)
        c._current_level_name = seg(1, 1)
    return c


def active(c, name):
    c._handle_packet(PacketID.PLO_SETACTIVELEVEL, name.encode())


def props(c, npc_id=NPC, **kw):
    c._handle_packet(PacketID.PLO_NPCPROPS, npc_props(npc_id, **kw))
    return c.npcs[npc_id]


def world(npc):
    return npc['world_x'], npc['world_y']


# -- the reference form: gmap-named active level, local X2/Y2, GMAPLEVELX/Y --

def test_npc_created_in_a_far_cell():
    """A new NPC under SETACTIVELEVEL <gmap> takes its cell from 41/42.
    Mutation: drop the GMAPLEVELX/Y stamping in _npc_level_and_cell (return
    the base cell) and it lands in (0, 0)."""
    c = make_client()
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=2, GMAPLEVELY=2, X2=10.0, Y2=20.5)
    assert npc['_level'] == seg(2, 2)
    assert world(npc) == (138.0, 148.5)


def test_new_npc_without_cell_props_is_in_cell_zero():
    """The reference server leaves GMAPLEVELX/Y out for cell (0, 0)
    (GServer-v2 NPC.cpp:146-150), and a map-owned NPC starts there.
    Mutation: drop the ``base = (0, 0)`` for a .gmap owner and the NPC is
    filed under the .gmap name, or the player's own segment."""
    c = make_client()
    active(c, GMAP)
    npc = props(c, X2=5.0, Y2=6.0)
    assert npc['_level'] == seg(0, 0)
    assert world(npc) == (5.0, 6.0)
    assert not c.npcs[NPC]['_level'].endswith('.gmap')


def test_props_with_only_gmaplevelx():
    """A seam crossing on x sends GMAPLEVELX alone (GServer-v2
    NPC.cpp:458-467). The y cell stays. Mutation: the old "both axes or
    nothing" rule (ignore a lone axis) leaves _level the .gmap name and the
    NPC frozen at world x 126."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=62.0, Y2=30.0)
    npc = props(c, GMAPLEVELX=2, X2=0.5)
    assert npc['_level'] == seg(2, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)
    assert world(npc) == (128.5, 94.0)


def test_props_with_only_gmaplevely():
    """The y twin of the test above. Mutation: as above."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=30.0, Y2=63.5)
    npc = props(c, GMAPLEVELY=2, Y2=0.0)
    assert npc['_level'] == seg(1, 2)
    assert world(npc) == (94.0, 128.0)


def test_a_cell_change_alone_moves_the_npc():
    """World is cell * 64 + local even when the packet carries no X2.
    Mutation: place only the axes present in the packet (the old per-axis
    world update) and world x stays 94."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=30.0, Y2=30.0)
    npc = props(c, GMAPLEVELX=0)
    assert world(npc) == (30.0, 94.0)


def test_npc_walks_across_seams_one_axis_at_a_time():
    """A walk east then south across two seams, in the packets the
    reference server sends: X2/Y2 every step, the changed GMAPLEVEL axis on a
    crossing. World advances in half tiles throughout and the level follows
    the cell. Mutation: the old lone-axis rule freezes it at the first seam."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=63.0, Y2=63.0)
    steps = [
        (dict(X2=63.5), (127.5, 127.0), seg(1, 1)),
        (dict(GMAPLEVELX=2, X2=0.0), (128.0, 127.0), seg(2, 1)),
        (dict(X2=0.5), (128.5, 127.0), seg(2, 1)),
        (dict(Y2=63.5), (128.5, 127.5), seg(2, 1)),
        (dict(GMAPLEVELY=2, Y2=0.0), (128.5, 128.0), seg(2, 2)),
        (dict(Y2=0.5), (128.5, 128.5), seg(2, 2)),
    ]
    for kw, expect_world, expect_level in steps:
        npc = props(c, **kw)
        assert world(npc) == expect_world, kw
        assert npc['_level'] == expect_level, kw


@pytest.mark.parametrize("x2, expect", [
    (0.0, 64.0), (0.0625, 64.0625), (63.0, 127.0), (63.9375, 127.9375)])
def test_segment_local_x2_near_both_edges(x2, expect):
    """Values at the edges of 0..63 are local to cell (1, 1). Mutation: a
    world_from_wire that treats 63.9375 as world (a ``>= 63`` bound) fails
    the last rows."""
    c = make_client()
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=x2, Y2=x2)
    assert world(npc) == (expect, expect)


def test_3x3_resend_of_a_known_npc_merges():
    """The reference server re-sends every NPC of the six overlapping cells
    after a hop (spec item 3); the reference client merges a known id
    (TClient.cpp:2950-2955). One record, client-side state kept, no render
    snap. Mutation: store a re-send as a new record
    (``client.npcs[npc_id] = props``) and the showimg layers and the epoch
    are lost."""
    c = make_client()
    active(c, GMAP)
    full = dict(IMAGE="pics1.png", GMAPLEVELX=2, GMAPLEVELY=1, X2=10.0, Y2=12.0)
    npc = props(c, **full)
    npc['imgs'] = {200: {'image': 'light.png', 'x': 1.0, 'y': 1.0}}
    epoch = npc['_pos_epoch']
    active(c, GMAP)
    again = props(c, **full)
    assert len(c.npcs) == 1 and again is npc
    assert again['imgs'] == {200: {'image': 'light.png', 'x': 1.0, 'y': 1.0}}
    assert again['_pos_epoch'] == epoch
    assert again['_level'] == seg(2, 1)
    assert world(again) == (138.0, 76.0)


def test_npcs_before_the_grid_are_placed_when_it_loads():
    """Under the reference form the NPC block can arrive before the .gmap
    file. The cell is kept and _update_npc_world_coords places the NPC in
    its segment once the grid exists. Mutation: in
    handle_npc_props, store the cell only when it is in the grid (the old
    ``(gx, gy) in client.gmap_grid`` test) and the NPC is placed in the
    player's segment instead."""
    c = make_client(grid=False)
    c._current_level_name = GMAP
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=2, X2=3.0, Y2=4.0)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 0)
    for y in range(3):
        for x in range(3):
            c.gmap_grid[(x, y)] = seg(x, y)
    c.gmap_width = c.gmap_height = 3
    c._update_npc_world_coords()
    assert npc['_level'] == seg(2, 0)
    assert world(npc) == (131.0, 4.0)
    c._update_npc_world_coords()
    assert world(npc) == (131.0, 4.0)


# -- a server that frames by segment: segment-named active level, segment-owned
# NPCs. pygserver no longer sends this (it names the gmap before every NPC on
# a gmap, level_entry.py), so these pin the client's reading of that framing.

def test_segment_owned_npc_copies_the_segment_cell():
    """SETACTIVELEVEL names a segment and no GMAPLEVELX/Y is sent: the NPC
    copies that segment's cell (TServerNPC.cpp:321-324). Mutation: treat a
    segment owner like the map (base (0, 0)) and it draws 64 tiles up."""
    c = make_client()
    active(c, seg(0, 1))
    npc = props(c, X2=20.0, Y2=30.0)
    assert npc['_level'] == seg(0, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (0, 1)
    assert world(npc) == (20.0, 94.0)


@pytest.mark.parametrize("x2, y2, expect", [
    (-1.5, 30.0, (62.5, 94.0)),       # straddling the west seam
    (65.0, 30.0, (129.0, 94.0)),      # straddling the east seam
    (30.0, -0.5, (94.0, 63.5)),
])
def test_local_value_outside_the_board_is_not_world(x2, y2, expect):
    """pygserver sends a segment-owned NPC straddling a seam with a local
    value outside 0..63. The old heuristic read it as world and drew it near
    (0, 0) or one segment off. Mutation: restore the pass-through in
    world_from_wire and every row fails."""
    c = make_client()
    active(c, seg(1, 1))
    npc = props(c, X2=x2, Y2=y2)
    assert world(npc) == expect


def test_live_update_after_the_npc_moved_segments_keeps_its_cell():
    """pygserver owns a gmap's NPCs by the gmap, so its NPC that NPCMOVED took
    to the next segment keeps sending props under SETACTIVELEVEL <gmap>: the
    NPC is added to the map, which keeps its own cell
    (TServerNPC.cpp:289-325). Mutation: give a known NPC the cell of the
    segment it was first seen in and it lands in s11's cell."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=63.0, Y2=30.0)
    moved = _gint3(NPC) + bytes([int(0.0 * 2) + 32, int(30.0 * 2) + 32]) \
        + seg(2, 1).encode()
    c._handle_packet(PacketID.PLO_NPCMOVED, moved)
    npc = c.npcs[NPC]
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)
    npc = props(c, X2=0.5)
    assert npc['_level'] == seg(2, 1)
    assert world(npc) == (128.5, 94.0)


def _walked_off(c, npc_id=NPC):
    """An NPC first seen in s11 that NPCMOVED took to s21."""
    props(c, npc_id=npc_id, GMAPLEVELX=1, GMAPLEVELY=1, X2=63.0, Y2=30.0)
    moved = _gint3(npc_id) + bytes([32, int(30.0 * 2) + 32]) \
        + seg(2, 1).encode()
    c._handle_packet(PacketID.PLO_NPCMOVED, moved)
    assert c.npcs[npc_id]['_level'] == seg(2, 1)


def test_known_global_npc_joins_the_active_plain_level_and_copies_its_cell():
    """TClient.cpp:2950-2951: a known NPC with an id of 1000 or more is added
    to the active NPC level on every props packet; added to a plain level it
    copies that level's cell (TServerNPC.cpp:289-325). Mutation: drop the
    ``npc_id >= 1000`` branch of _npc_level_and_cell and it stays in s21."""
    c = make_client()
    active(c, GMAP)
    _walked_off(c)
    active(c, seg(1, 1))
    npc = props(c, X2=0.5)
    assert npc['_level'] == seg(1, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (1, 1)
    assert world(npc) == (64.5, 94.0)


def test_known_global_npc_under_the_gmap_keeps_its_cell():
    c = make_client()
    active(c, GMAP)
    _walked_off(c)
    npc = props(c, X2=0.5)
    assert npc['_level'] == seg(2, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)


def test_known_global_npc_already_in_the_active_level_is_unchanged():
    c = make_client()
    active(c, seg(2, 1))
    props(c, X2=10.0, Y2=10.0)
    npc = props(c, X2=11.0)
    assert npc['_level'] == seg(2, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)
    assert world(npc) == (139.0, 74.0)


def test_known_npc_below_1000_is_not_moved_by_the_active_level():
    c = make_client()
    active(c, GMAP)
    _walked_off(c, npc_id=999)
    active(c, seg(1, 1))
    npc = props(c, npc_id=999, X2=0.5)
    assert npc['_level'] == seg(2, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)


def test_known_global_npc_joining_a_level_outside_the_grid_drops_its_cell():
    c = make_client()
    active(c, GMAP)
    _walked_off(c)
    active(c, "house.nw")
    npc = props(c, X2=5.0, Y2=6.0)
    assert npc['_level'] == "house.nw"
    assert 'gmaplevelx' not in npc and 'gmaplevely' not in npc


def test_known_global_npc_without_an_active_level_is_not_moved():
    """The reference skips the join while the NPC target is null."""
    c = make_client()
    active(c, GMAP)
    _walked_off(c)
    c._npc_level = ""
    npc = props(c, X2=0.5)
    assert npc['_level'] == seg(2, 1)


def test_npc_move_queue_starts_from_the_npc_cell():
    """PLO_MOVE2 positions are local to the NPC's cell. Mutation: take the
    origin from the level name (level_origin(_level)) and an NPC whose
    level is not a segment yet starts the move in cell (0, 0)."""
    from pyreborn.npc_movement import queue_moves
    c = make_client()
    c.npcs[NPC] = {'id': NPC, '_level': GMAP, 'gmaplevelx': 2,
                   'gmaplevely': 2, 'x': 10.0, 'y': 10.0}
    queue_moves(c, {'npc_id': NPC, 'records': [
        {'dx': 1.0, 'dy': 0.0, 'x': 10.0, 'y': 10.0, 'duration_ms': 500,
         'options': 1}]})
    assert world(c.npcs[NPC]) == (138.0, 138.0)


# -- end to end against the in-process pygserver (its current form) ----------

def test_pygserver_gmap_npc_lands_in_its_segment_and_draws_there(
        make_game, monkeypatch):
    """pygserver frames a gmap's NPC block with SETACTIVELEVEL <segment> and
    sends no GMAPLEVELX/Y. The player stands in fixture_d.nw, cell (1, 1);
    its NPC at local (24, 24) belongs to that segment at world (88, 88), and
    the renderer converts exactly that world point. pygserver then sends the
    NPC straddling the west seam at local x -1.5 (its own props builder),
    which is world 62.5. Mutation: restore the "outside 0..63 is world"
    pass-through in world_from_wire and the straddle reads world -1.5."""
    from offline_game import GMAP_SEGMENTS
    spawn = GMAP_SEGMENTS[3]
    game = make_game(gmap=True, gmap_segment=(1, 1), player_xy=(30.0, 30.0),
                     npcs=[{"id": 101, "x": 24.0, "y": 24.0,
                            "image": "pics1.png",
                            "imagepart": (0, 0, 32, 32)}])
    npc = game.client.npcs[101]
    assert npc['_level'] == spawn
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (1, 1)
    assert world(npc) == (88.0, 88.0)

    calls = []
    real = game.camera.world_to_screen

    def record(wx, wy):
        calls.append((wx, wy))
        return real(wx, wy)
    monkeypatch.setattr(game.camera, 'world_to_screen', record)
    game.frames(3)
    assert (88.0, 88.0) in calls

    async def straddle(w):
        server_npc = w.server.npc_manager.get_npc(101)
        server_npc.x = -1.5
        await w.me.send_raw(server_npc.build_props_packet(include_script=False))
    game.server.run(straddle)
    npc = game.client.npcs[101]
    assert npc['_level'] == spawn
    assert world(npc) == (62.5, 88.0)
    calls.clear()
    game.frames(12)
    assert calls and (62.5, 88.0) in calls


def test_npc_cell_outside_a_loaded_grid_never_keeps_the_gmap_name():
    """With no grid yet, an NPC the server puts in a gmap cell falls back to
    the player's own level, never the .gmap name (the map owns no board).
    Mutation: disable the ``.gmap`` fallback in _npc_level_and_cell and the
    NPC's level is the .gmap name."""
    c = make_client(grid=False)
    c._current_level_name = 'a.nw'
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=2, X2=3.0, Y2=4.0)
    assert npc['_level'] == 'a.nw'
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 0)


# -- NPC level changes and the per-level cache (reference-server sequences) --

def moved(c, x, y, level, npc_id=NPC):
    c._handle_packet(PacketID.PLO_NPCMOVED,
                     _gint3(npc_id) + bytes([int(x * 2) + 32, int(y * 2) + 32])
                     + level.encode())


def cache_ids(c):
    return {k: sorted(v) for k, v in c._npc_cache.items() if v}


def test_map_owned_npc_without_a_cell_rejoins_the_map_at_cell_zero():
    """A database NPC never stamped with a cell walks into a plain level and
    back: NPCMOVED to the .gmap name, then NPCPROPS with no GMAPLEVEL prop
    and no SETACTIVELEVEL. It must take cell (0, 0) and follow X2, not freeze
    on the .gmap name. Mutation: in _npc_level_and_cell's known-NPC branch,
    drop the ``(0, 0)`` base for a map-named owner with no cell."""
    c = make_client()
    active(c, GMAP)
    props(c, X2=20.0, Y2=20.0)
    moved(c, 5.0, 5.0, 'house.nw')
    assert 'gmaplevelx' not in c.npcs[NPC]
    moved(c, 30.0, 30.0, GMAP)
    npc = props(c, X2=30.0, Y2=30.0)
    assert npc['_level'] == seg(0, 0)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (0, 0)
    props(c, X2=40.0)
    assert world(npc) == (40.0, 30.0)


def test_npc_moved_to_a_plain_level_drops_its_cell():
    """An NPC in cell (1, 1) that NPCMOVED takes into a plain level is drawn
    at its local position, with no cell. Mutation: drop the plain-level cell
    reset in handle_npc_moved and the NPC stays 64 tiles off."""
    c = make_client()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    moved(c, 6.0, 7.0, 'house.nw')
    npc = c.npcs[NPC]
    assert 'gmaplevelx' not in npc and 'gmaplevely' not in npc
    assert world(npc) == (6.0, 7.0)


def _two_cell_world():
    c = make_client()
    active(c, GMAP)
    props(c, npc_id=777, GMAPLEVELX=1, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    props(c, GMAPLEVELX=2, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    c._reset_level_state(cache_npcs=True)
    c._restore_cached_npcs(seg(1, 1))
    return c


def test_seam_crossed_npc_is_cached_in_one_bucket_only():
    """An NPC that crossed a seam is re-filed under the new segment; the
    older copy must not survive in the old bucket and win a restore.
    Mutation: remove the other-bucket purge when caching in
    _reset_level_state and the restore returns it in s21 at x 133."""
    c = _two_cell_world()
    props(c, GMAPLEVELX=1, X2=63.5)
    assert c.npcs[NPC]['_level'] == seg(1, 1)
    c._reset_level_state(cache_npcs=True)
    assert cache_ids(c) == {seg(1, 1): [777, NPC]}
    c._restore_cached_npcs(seg(1, 1))
    assert c.npcs[NPC]['_level'] == seg(1, 1)
    assert c.npcs[NPC]['world_x'] == 127.5


def test_deleted_npc_does_not_come_back_on_reentry():
    """NPCDEL removes the id from every bucket, so a warp out and back does
    not restore it. Mutation: make handle_npc_del purge only the bucket of
    the NPC's own level."""
    c = _two_cell_world()
    props(c, GMAPLEVELX=1, X2=63.5)     # the s21 cache copy is now stale
    c._handle_packet(PacketID.PLO_NPCDEL, _gint3(NPC))
    assert NPC not in c.npcs and NPC not in sum(cache_ids(c).values(), [])
    c._reset_level_state(cache_npcs=True)
    c._restore_cached_npcs(seg(1, 1))
    assert NPC not in c.npcs


def test_npcdel2_naming_the_gmap_clears_every_segment_bucket():
    """The map owns its NPCs (TClient.cpp:5233-5250 deletes from the named
    level's roster), so NPCDEL2 naming the .gmap purges the segment buckets.
    Mutation: make handle_npc_del2 purge only the bucket of the named level."""
    c = _two_cell_world()
    c._reset_level_state(cache_npcs=True)
    assert NPC in sum(cache_ids(c).values(), [])
    name = GMAP.encode()
    c._handle_packet(PacketID.PLO_NPCDEL2,
                     bytes([len(name) + 32]) + name + _gint3(NPC))
    assert NPC not in sum(cache_ids(c).values(), [])
    assert 777 in c._npc_cache[seg(1, 1)]
    c._restore_cached_npcs(seg(1, 1))
    assert NPC not in c.npcs


def test_pygserver_npc_walking_across_a_seam_keeps_its_world_position(
        make_game):
    """A live walk in the offline gmap world. The NPC (id 1500, so the
    reference client's re-join rule applies to it, TClient.cpp:2950-2951)
    starts in the player's segment, cell (1, 1). pygserver rolls it into the
    west neighbour, cell (0, 1), as props only under the gmap's active level
    (npc.py relocate_npc / confine_position), and keeps updating it there.
    Mutation: apply the re-join with the player's segment as the target and
    the NPC reads cell (1, 1) again, 64 tiles east of where it is."""
    from offline_game import GMAP_SEGMENTS
    game = make_game(gmap=True, gmap_segment=(1, 1), player_xy=(30.0, 30.0),
                     npcs=[{"id": 1500, "x": 2.0, "y": 24.0,
                            "image": "pics1.png",
                            "imagepart": (0, 0, 32, 32)}])
    npc = game.client.npcs[1500]
    assert game.client._npc_level.endswith(".gmap")
    assert npc['_level'] == GMAP_SEGMENTS[3]
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (1, 1)
    assert world(npc) == (66.0, 88.0)

    async def cross(w):
        server_npc = w.server.npc_manager.get_npc(1500)
        server_npc.x = -1.5
        await w.server.npc_manager.confine_position(server_npc)
    game.server.run(cross)
    npc = game.client.npcs[1500]
    assert npc['_level'] == GMAP_SEGMENTS[2]
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (0, 1)
    assert world(npc) == (62.5, 88.0)

    # the walk goes on in X2 alone: no cell prop is repeated
    game.client._handle_packet(PacketID.PLO_NPCPROPS,
                               npc_props(1500, X2=61.0))
    npc = game.client.npcs[1500]
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (0, 1)
    assert world(npc) == (61.0, 88.0)
