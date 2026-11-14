"""What goes on the wire when the player moves between levels of a gmap.

The reference client sends NO warp when it walks into a neighbouring level
inside the gmap it has loaded. It tests the target against the map's
level-name grid (FourPlay TClient.cpp:1354-1358, grid built from the .gmap
file, TServerLevel.cpp:2112-2132), enters the level locally, and its next
property packet carries the position in the new level's frame plus the
GMAPLEVELX / GMAPLEVELY that changed, in ascending id order
(TPlayer.cpp:7794-7811, :2457-2468). The server learns the hop from those
props (GServer-v2 PlayerProps.cpp:906-973). A warp is still sent for
everything that is not such a hop: entering a gmap from outside, leaving it,
a level that is no cell of the grid.
"""

from offline_game import GMAP_SEGMENTS, sent_player_props
from pyreborn.packets import PacketID

GMAPLEVELX, GMAPLEVELY = 43, 44
WARP_IDS = (int(PacketID.PLI_LEVELWARP), int(PacketID.PLI_LEVELWARPMOD))
A, B, C, D = GMAP_SEGMENTS           # cells (0,0) (1,0) (0,1) (1,1)


def _open(tx, ty):
    return 0


def _warp_ids(client, mark=0):
    return [pid for pid, _ in client._protocol.sent[mark:] if pid in WARP_IDS]


def _walk(client, steps, dx, dy):
    for _ in range(steps):
        assert client.move(dx, dy, step=0.5)


def test_walking_over_a_seam_sends_no_warp(make_client):
    """(a) The crossing step sends no PLI_LEVELWARP and no PLI_LEVELWARPMOD,
    even though the neighbour's board is held.

    Mutation: make `move` follow the props with `_send_level_warp` again (the
    old `enter_gmap_segment` body), or make `_is_gmap_hop` return False, and
    this fails."""
    client = make_client(gmap=True, player_xy=(62.5, 30.0), tiles=_open)
    assert B in client.levels                       # preloaded neighbour
    mark = len(client._protocol.sent)
    _walk(client, 4, 1, 0)                          # 62.5 -> 64.5
    assert client.current_level_name == B
    assert _warp_ids(client, mark) == []


def test_the_crossing_step_sends_one_props_packet_in_the_new_frame(make_client):
    """(b) One PLI_PLAYERPROPS, ascending ids, the position in the NEW
    level's frame (world 64.0 is local 0.0 of B), and only the axis that
    changed (GMAPLEVELX = 1).

    Mutation: send the step in the old frame (64.0), drop the GMAPLEVELX
    prop, or send both axes, and this fails."""
    client = make_client(gmap=True, player_xy=(63.5, 30.0), tiles=_open)
    client._use_pixel_props = True
    mark = len(client._protocol.sent)
    assert client.move(1, 0, step=0.5)
    packets = sent_player_props(client._protocol.sent[mark:])
    assert len(packets) == 1
    ids = [prop for prop, _ in packets[0]]
    assert ids == sorted(ids)
    props = dict(packets[0])
    assert props[GMAPLEVELX] == 1 and GMAPLEVELY not in props
    assert (props[78], props[79]) == (0.0, 30.0)


def test_a_diagonal_crossing_sends_both_axes(make_client):
    """Both changed axes in one packet, X before Y (the reference sends every
    changed prop in id order). Mutation: send only one axis and this fails."""
    client = make_client(gmap=True, player_xy=(63.5, 63.5), tiles=_open)
    client._use_pixel_props = True
    mark = len(client._protocol.sent)
    assert client.move(1, 1, step=0.5)
    (pairs,) = sent_player_props(client._protocol.sent[mark:])
    ids = [prop for prop, _ in pairs]
    assert ids == sorted(ids)
    props = dict(pairs)
    assert (props[GMAPLEVELX], props[GMAPLEVELY]) == (1, 1)
    assert (props[78], props[79]) == (0.0, 0.0)
    assert client.current_level_name == D
    assert _warp_ids(client, mark) == []


def test_the_server_follows_the_hop_from_the_props_alone(make_client):
    """pygserver re-homes the player from the props; no warp is needed."""
    client = make_client(gmap=True, player_xy=(62.5, 30.0), tiles=_open)
    mark = len(client._protocol.sent)
    _walk(client, 4, 1, 0)
    sent = client._protocol.sent[mark:]

    async def dispatch(world):
        for packet_id, data in sent:
            await world.me._dispatch_packet(packet_id, data)
    client.server.run(dispatch)
    assert client.server.me.level.name == B


def test_a_warp_out_of_the_gmap_is_still_a_warp(make_client):
    """(c) A door to a level that is no cell of the grid warps. Mutation:
    make `_is_gmap_hop` true for any level and this fails."""
    client = make_client(gmap=True, tiles=_open,
                         extra_levels={"elsewhere.nw": None})
    mark = len(client._protocol.sent)
    assert client.warp_to_level("elsewhere.nw", 10.0, 12.0)
    assert len(_warp_ids(client, mark)) == 1
    assert sent_player_props(client._protocol.sent[mark:]) == []


def test_entering_the_gmap_from_outside_is_a_warp(make_client):
    """Coming back in from a level that is not a cell: warp, no hop props."""
    client = make_client(gmap=True, tiles=_open,
                         extra_levels={"elsewhere.nw": None})
    assert client.warp_to_level("elsewhere.nw", 10.0, 12.0)
    mark = len(client._protocol.sent)
    assert client.warp_to_level(B, 5.0, 6.0)
    assert len(_warp_ids(client, mark)) == 1
    assert [g for pairs in sent_player_props(client._protocol.sent[mark:])
            for g in pairs if g[0] in (GMAPLEVELX, GMAPLEVELY)] == []


def test_a_door_to_a_gmap_cell_is_a_hop_too(make_client):
    """The reference decides by the grid for every caller of its link
    routine, so a door whose target is another cell of the loaded gmap sends
    props and no warp either."""
    client = make_client(gmap=True, tiles=_open)
    mark = len(client._protocol.sent)
    assert client.warp_to_level(D, 10.0, 12.0)
    assert _warp_ids(client, mark) == []
    props = dict(sent_player_props(client._protocol.sent[mark:])[0])
    assert (props[GMAPLEVELX], props[GMAPLEVELY]) == (1, 1)


def test_walking_the_game_over_the_seam_hops_without_a_warp(make_game,
                                                           monkeypatch):
    """The same through the game's own movement code, ticked."""
    import pygame

    class _Held(dict):
        def __missing__(self, key):
            return False
    keys = _Held({pygame.K_RIGHT: True})
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: keys)
    game = make_game(gmap=True, player_xy=(62.0, 30.0), tiles=_open)
    client = game.client
    mark = len(client._protocol.sent)
    game.ticks(6)
    assert client.current_level_name == B
    assert _warp_ids(client, mark) == []
    assert any(prop == GMAPLEVELX
               for pairs in sent_player_props(client._protocol.sent[mark:])
               for prop, _ in pairs)


# -- a hop needs the target held, and arrives like a walked hop -------------

def _hop_props(client, mark):
    return [dict(pairs) for pairs in sent_player_props(client._protocol.sent[mark:])]


def test_a_walked_seam_into_a_cell_not_held_is_a_warp(make_client):
    """(d) The reference falls back to a plain warp when the target level is
    not loaded locally (TClient.cpp:1323-1347: no held level, no cached file
    with a mod time -> sendLevelWarp). A hop to a held cell sends no warp.

    Mutation: drop the `to_level in self.levels` test from `_is_gmap_hop` and
    the not-held half fails; make it always warp and the held half fails."""
    held = make_client(gmap=True, player_xy=(63.5, 30.0), tiles=_open)
    assert B in held.levels
    mark = len(held._protocol.sent)
    assert held.move(1, 0, step=0.5)
    assert _warp_ids(held, mark) == []

    client = make_client(gmap=True, player_xy=(63.5, 30.0), tiles=_open)
    del client.levels[B]
    mark = len(client._protocol.sent)
    assert client.move(1, 0, step=0.5)
    assert _warp_ids(client, mark) == [int(PacketID.PLI_LEVELWARP)]
    assert client.current_level_name == B


def test_a_door_to_a_cell_not_held_is_a_warp(make_client):
    """(d) The same fallback for a door or script: warp_to_level to a cell
    the client does not hold sends the warp id, and a held cell does not."""
    held = make_client(gmap=True, tiles=_open)
    mark = len(held._protocol.sent)
    assert held.warp_to_level(D, 10.0, 12.0)
    assert _warp_ids(held, mark) == []

    client = make_client(gmap=True, tiles=_open)
    del client.levels[D]
    mark = len(client._protocol.sent)
    assert client.warp_to_level(D, 10.0, 12.0)
    assert _warp_ids(client, mark) == [int(PacketID.PLI_LEVELWARP)]
    assert client._warp_echo and client._warp_echo[0] == D


def test_a_door_hop_records_no_warp_echo(make_client):
    """(a) A hop sends no warp, so no echo is expected back; recording one
    would swallow the next genuine server reposition into that level.

    Mutation: change `if hop: ... else: self.note_client_warp(...)` in
    `warp_to_level` so it always records, and this fails."""
    client = make_client(gmap=True, tiles=_open)
    client._warp_echo = None
    assert client.warp_to_level(D, 10.0, 12.0)
    assert not client._warp_echo


def _spy_adjacent(client):
    calls = []
    real = client.request_adjacent_levels
    client.request_adjacent_levels = lambda *a, **k: (calls.append(1),
                                                      real(*a, **k))[1]
    return calls


def test_a_walked_hop_re_points_the_board_and_asks_for_neighbours(make_client):
    """(b)+(c) After the crossing step the active board is the new segment's
    and the segments next to it are requested.

    Mutation (b): drop the cached_board re-point in `_arrive_in_gmap_segment`
    and `_tiles_level_name` stays on the old level. Mutation (c): drop its
    `request_adjacent_levels()` call and the spy sees nothing."""
    client = make_client(gmap=True, player_xy=(63.5, 30.0), tiles=_open)
    assert client._tiles_level_name == A
    calls = _spy_adjacent(client)
    assert client.move(1, 0, step=0.5)
    assert client.current_level_name == B
    assert client._tiles_level_name == B
    assert client.tiles is client.levels[B]
    assert calls


def test_a_door_hop_arrives_like_a_walked_hop(make_client):
    """(b)+(c) for the door path: `warp_to_level` to a held cell ends in the
    same arrival (board re-pointed, neighbours requested)."""
    client = make_client(gmap=True, tiles=_open)
    calls = _spy_adjacent(client)
    assert client.warp_to_level(D, 10.0, 12.0)
    assert client._tiles_level_name == D
    assert client.tiles is client.levels[D]
    assert calls


def test_a_door_hop_keeps_ground_items_and_baddies(make_client):
    """(e) The reference's hop only enters the held level
    (TClient.cpp:1346-1357, TPlayer::enterServerLevel) and clears nothing,
    and the server no longer re-streams a level's items after a hop. A walked
    hop already kept them; the door hop used to drop them.

    Mutation: call `_reset_level_state()` for a hop in `warp_to_level` and
    this fails."""
    client = make_client(gmap=True, tiles=_open, items=[(14.0, 14.0, 0)])
    client.baddies[A] = {1: {"x": 20.0, "y": 20.0, "type": 1}}
    items = {k: dict(v) for k, v in client.items.items()}
    baddies = {k: dict(v) for k, v in client.baddies.items()}
    assert any(items.values()) and any(baddies.values())
    assert client.warp_to_level(D, 10.0, 12.0)
    assert client.items == items
    assert client.baddies == baddies


def test_the_hop_cell_is_the_first_grid_match_of_the_level_name(make_client):
    """A gmap listing one level in two cells reports the FIRST cell on a hop.
    The reference sends setMapX(serverLevel->mapX) (TPlayer.cpp:465-490,
    7794-7811) and a level's mapX is its first match in the map's name list
    (TServerLevel::updateMapPos, TServerLevel.cpp:930-960), not the cell the
    player's position falls in. Stepping from B into the second A (world x
    128) therefore sends GMAPLEVELX = 0, as the reference does.

    Mutation: derive the cell from the position and this fails."""
    client = make_client(gmap=True, tiles=_open)
    client.gmap_grid = {(0, 0): A, (1, 0): B, (2, 0): A}
    client._current_level_name = B
    client.player.x, client.player.y = 127.5, 30.0
    client._use_pixel_props = True
    mark = len(client._protocol.sent)
    assert client.move(1, 0, step=0.5)
    (props,) = _hop_props(client, mark)
    assert props[GMAPLEVELX] == 0
    assert _warp_ids(client, mark) == []
