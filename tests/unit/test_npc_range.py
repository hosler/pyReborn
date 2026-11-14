"""The 3x3 an NPC stays visible in on a gmap, and the NPC re-join rule.

The reference server sends no NPC delete when a cell leaves the 3x3 around
the player. The reference client keeps the NPC and hides it: a map-owned
NPC is visible iff |player.map - npc.map| <= 1 on both axes
(FourPlay quattroplay/src/TServerNPC.cpp:425-427, TPlayer.cpp:374-387). The
copy stays in `client.npcs` and shows again when the player walks back.
Hidden NPCs are not drawn and their script stops; blocking and touch are
gated by the script's own `visible` only (TServerNPC.cpp:2095).

Packets are hand-built in the reference server's layout (see
test_npc_gmap_frame.py): PLO_NPCPROPS is ``{GINT3 id}`` then ``{GCHAR
prop}{value}`` in ascending prop order, PLO_SETACTIVELEVEL the raw level
name, PLO_NPCMOVED ``{GINT3 id}{GCHAR x/8}{GCHAR y/8}{level}``.
"""

import pygame
from reborn_protocol.props import NPC_PROPS, encode_value

from pyreborn import Client
from pyreborn.game.frame_context import FrameContext
from pyreborn.packets import PacketID
from offline_game import region_differs

GMAP = "chicken.gmap"
NPC = 1500
_BY_NAME = {d.name: d for d in NPC_PROPS.values()}


def _gint3(v):
    return bytes([((v >> 14) & 0x7F) + 32, ((v >> 7) & 0x7F) + 32,
                  (v & 0x7F) + 32])


def npc_props(npc_id, **props):
    pairs = sorted(((_BY_NAME[name], value) for name, value in props.items()),
                   key=lambda pair: pair[0].id)
    return _gint3(npc_id) + b"".join(
        bytes([desc.id + 32]) + encode_value(desc, value)
        for desc, value in pairs)


def seg(x, y):
    return f"r{x}{y}.nw"


def wide_client():
    """A 5x1 grid, the player in cell (0, 0)."""
    c = Client("localhost", 14900)
    c.gmap_width, c.gmap_height = 5, 1
    for x in range(5):
        c.gmap_grid[(x, 0)] = seg(x, 0)
    c._current_level_name = seg(0, 0)
    return c


def active(c, name):
    c._handle_packet(PacketID.PLO_SETACTIVELEVEL, name.encode())


def props(c, npc_id=NPC, **kw):
    c._handle_packet(PacketID.PLO_NPCPROPS, npc_props(npc_id, **kw))
    return c.npcs[npc_id]


def visible(c, npc):
    return c.npc_range_filter()(npc)


def test_range_follows_the_players_cell_and_the_copy_is_kept():
    c = wide_client()
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=3, GMAPLEVELY=0, X2=10.0, Y2=10.0)
    assert npc['_map_owned']
    assert not visible(c, npc)                  # 3 cells away
    c._current_level_name = seg(1, 0)
    assert not visible(c, npc)                  # 2 cells away
    c._current_level_name = seg(2, 0)
    assert visible(c, npc)                      # 1 cell away
    c._current_level_name = seg(4, 0)
    assert visible(c, npc)
    c._current_level_name = seg(0, 0)
    assert c.npcs[NPC] is npc                   # kept all along
    assert not visible(c, npc)


def test_a_diagonal_neighbour_stays_visible():
    c = Client("localhost", 14900)
    c.gmap_width = c.gmap_height = 3
    for y in range(3):
        for x in range(3):
            c.gmap_grid[(x, y)] = seg(x, y)
    c._current_level_name = seg(1, 1)
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=2, GMAPLEVELY=2, X2=5.0, Y2=5.0)
    assert visible(c, npc)


def test_a_segment_owned_npc_is_never_hidden():
    """TServerNPC.cpp:420-422: the check returns early for an NPC whose
    level is not the player's map."""
    c = wide_client()
    active(c, seg(4, 0))
    npc = props(c, X2=5.0, Y2=5.0)
    assert not npc['_map_owned']
    assert visible(c, npc)


def test_a_plain_level_is_unchanged():
    c = Client("localhost", 14900)
    c._current_level_name = "house.nw"
    active(c, "house.nw")
    npc = props(c, X2=5.0, Y2=5.0)
    assert not npc['_map_owned']
    assert visible(c, npc)


def test_an_npc_with_no_known_player_cell_is_visible():
    c = wide_client()
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=4, GMAPLEVELY=0, X2=5.0, Y2=5.0)
    c._current_level_name = "interior.nw"       # no cell: a plain level
    assert visible(c, npc)


def test_render_collects_only_the_range_and_shows_it_again(make_game,
                                                           monkeypatch):
    """The game layer reads the library's filter. An NPC three cells away is
    not collected after a walk, and is collected again, with no new packet,
    when the player walks back. Blocking is the NPC's world position: the
    hidden NPC is far from the player's tile in both models."""
    game = make_game(gmap=True, gmap_segment=(0, 0), player_xy=(30.0, 30.0))
    c = game.client
    for x in range(2, 5):
        c.gmap_grid[(x, 0)] = seg(x, 0)
    c.gmap_width = 5
    c._handle_packet(PacketID.PLO_SETACTIVELEVEL, GMAP.encode())
    props(c, GMAPLEVELX=3, GMAPLEVELY=0, X2=10.0, Y2=10.0)
    monkeypatch.setattr(game, '_entity_on_screen', lambda *a, **k: True)

    def collected():
        out = []
        game._collect_npcs(out, FrameContext(screen_size=(320, 240)))
        return [e.key for e in out if e.kind == 'npc']

    assert NPC not in collected()               # 3 cells from cell (0, 0)
    assert not game.gs1.npc_blocks_at(c.x, c.y)
    c._current_level_name = seg(2, 0)           # the walk: 1 cell away
    assert NPC in collected()
    c._current_level_name = seg(0, 0)           # and back
    assert NPC not in collected()
    c._current_level_name = seg(3, 0)
    assert NPC in collected()
    assert NPC in c.npcs


def test_gs1_timer_of_a_hidden_npc_waits_and_resumes(make_game):
    game = make_game(gmap=True, gmap_segment=(0, 0), player_xy=(30.0, 30.0))
    c = game.client
    for x in range(2, 5):
        c.gmap_grid[(x, 0)] = seg(x, 0)
    c.gmap_width = 5
    c._handle_packet(PacketID.PLO_SETACTIVELEVEL, GMAP.encode())
    npc = props(c, GMAPLEVELX=4, GMAPLEVELY=0, X2=10.0, Y2=10.0)
    npc['_timeout'] = 1.0
    game.gs1.process_timeouts(0.25)
    assert npc['_timeout'] == 1.0               # stopped while hidden
    c._current_level_name = seg(3, 0)
    game.gs1.process_timeouts(0.25)
    assert npc['_timeout'] < 1.0                # runs again once shown


def test_a_hidden_npcs_gui_layer_is_not_drawn_and_returns_in_range(make_game):
    """The reference destroys a hidden NPC's images (TServerNPC.cpp:842-846),
    so its vis >= 4 layer vanishes from the GUI band too. The probe is the
    same world without the NPC."""
    script = ("if (created) {\n showimg 1,pics1.png,600,500;\n"
              " changeimgpart 1,0,0,32,32;\n changeimgvis 1,4;\n}\n")
    knobs = dict(gmap=True, gmap_segment=(0, 0), player_xy=(30.0, 30.0))
    subject = make_game(npcs=[{"id": 123, "x": 44, "y": 30, "image": "-",
                               "script": script}], **knobs)
    baseline = make_game(**knobs)
    for g in (subject, baseline):
        for x in range(2, 5):
            g.client.gmap_grid[(x, 0)] = seg(x, 0)
        g.client.gmap_width = 5
    npc = subject.client.npcs[123]
    assert npc['_map_owned'] and npc['imgs']
    region = pygame.Rect(600, 500, 32, 32)

    def drawn():
        subject.frames(3)
        baseline.frames(3)
        return region_differs(subject, baseline, screen=region)

    npc['gmaplevelx'], npc['gmaplevely'] = 1, 0
    assert drawn()                              # one cell away: shown
    npc['gmaplevelx'] = 3
    assert not drawn()                          # three cells away: hidden
    npc['gmaplevelx'] = 1
    assert drawn()                              # back in range: drawn again


# -- re-join rule ------------------------------------------------------------

def _gmap_client_3x3():
    c = Client("localhost", 14900)
    c.gmap_width = c.gmap_height = 3
    for y in range(3):
        for x in range(3):
            c.gmap_grid[(x, y)] = seg(x, y)
    c._current_level_name = seg(1, 1)
    return c


def _moved(c, x, y, level):
    c._handle_packet(PacketID.PLO_NPCMOVED,
                     _gint3(NPC) + bytes([int(x * 2) + 32, int(y * 2) + 32])
                     + level.encode())


def test_known_npc_in_a_plain_level_moves_into_the_map_with_its_own_cell():
    """TServerNPC.cpp:289-325, map branch: the NPC keeps its own mapX/mapY.
    One that sat in a segment owned by the segment keeps that segment's cell
    and its world position follows."""
    c = _gmap_client_3x3()
    active(c, seg(2, 1))
    props(c, X2=10.0, Y2=12.0)
    assert not c.npcs[NPC]['_map_owned']
    assert (c.npcs[NPC]['gmaplevelx'], c.npcs[NPC]['gmaplevely']) == (2, 1)
    active(c, GMAP)
    npc = props(c, X2=11.0)
    assert npc['_map_owned']
    assert npc['_level'] == seg(2, 1)
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (2, 1)
    assert (npc['world_x'], npc['world_y']) == (139.0, 76.0)


def test_known_npc_in_a_level_off_the_grid_enters_the_map_at_cell_zero():
    """An NPC in a plain level that is no cell has mapX = mapY = 0, so its
    local position becomes its world position in the map."""
    c = _gmap_client_3x3()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    _moved(c, 6.0, 7.0, "house.nw")
    assert not c.npcs[NPC]['_map_owned']
    active(c, GMAP)
    npc = props(c, X2=20.0)
    assert npc['_map_owned']
    assert (npc['gmaplevelx'], npc['gmaplevely']) == (0, 0)
    assert npc['_level'] == seg(0, 0)
    assert (npc['world_x'], npc['world_y']) == (20.0, 7.0)


def test_rejoin_onto_a_plain_level_off_the_grid_follows_local_position():
    """The NPC's cell is dropped and its world position is its local one,
    not the stale value of the cell it left."""
    c = _gmap_client_3x3()
    active(c, GMAP)
    npc = props(c, GMAPLEVELX=2, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    assert (npc['world_x'], npc['world_y']) == (133.0, 69.0)
    active(c, "house.nw")
    npc = props(c, X2=8.0, Y2=9.0)
    assert 'gmaplevelx' not in npc
    assert not npc['_map_owned']
    assert (npc['world_x'], npc['world_y']) == (8.0, 9.0)


def test_npc_moved_to_a_map_name_is_map_owned_and_to_a_level_is_not():
    c = _gmap_client_3x3()
    active(c, GMAP)
    props(c, GMAPLEVELX=1, GMAPLEVELY=1, X2=5.0, Y2=5.0)
    _moved(c, 6.0, 7.0, "house.nw")
    assert not c.npcs[NPC]['_map_owned']
    _moved(c, 6.0, 7.0, GMAP)
    assert c.npcs[NPC]['_map_owned']


def test_level_name_does_not_move_the_npc_owner_before_set_active_level():
    """TPlayer.cpp:941-946: the level load sets the NPC owner only when the
    level scope does not name the loaded level, and PLO_LEVELNAME names it.
    Until the first PLO_SETACTIVELEVEL the owner is the previous one."""
    c = Client("localhost", 14900)
    active(c, "old.nw")
    c._handle_packet(PacketID.PLO_LEVELNAME, b"new.nw")
    assert c._npc_level == "old.nw"
    active(c, "new.nw")
    assert c._npc_level == "new.nw"
