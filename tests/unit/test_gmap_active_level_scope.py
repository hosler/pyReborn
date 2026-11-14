"""The two level targets of the reference client.

PLO_LEVELNAME sets the level scope that items, chests, signs, links, boards,
board changes, baddies and horses use (TClient.cpp:3224-3241); a ``.gmap``
name there stands for the player's own segment. PLO_SETACTIVELEVEL sets only
the NPC owner (TClient.cpp:3777-3784). On a gmap the dynamic block ends with
PLO_SETACTIVELEVEL <map>.gmap (GServer-v2 server/src/player/PlayerClient.cpp:1555),
and a live packet for a player on another level is wrapped in
SETACTIVELEVEL <other> ... SETACTIVELEVEL <own> (server/src/Server.cpp:2400-2412).
None of that may file level data under the map name or the other level.
"""
from unittest.mock import Mock

from pyreborn import Client
from pyreborn.packet_codec.gameplay import build_baddy_props
from pyreborn.packets import PacketID

SEGMENT = "B.nw"
OTHER = "A.nw"
MAP = "world.gmap"


def _g(*values):
    return bytes(32 + v for v in values)


def _client_on_map():
    client = Client("localhost", 14900)
    client.gmap_name = MAP
    client.gmap_width, client.gmap_height = 2, 1
    client.gmap_grid = {(0, 0): OTHER, (1, 0): SEGMENT}
    client._current_level_name = SEGMENT
    client.player.x, client.player.y = 74.0, 10.0
    client.player.level = MAP
    client._requested_gmap = MAP
    # the entry stream: LEVELNAME B.nw ... LEVELNAME world.gmap
    client._level_scope = MAP
    client._level_scope_segment = SEGMENT
    # the end of the dynamic block, as the reference server frames it
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, MAP.encode())
    assert client._npc_level == MAP
    assert client._level_scope == MAP
    return client


def test_map_active_level_still_owns_new_npcs():
    client = _client_on_map()
    assert client._npc_level == MAP
    assert client._level_scope_name() == SEGMENT


def test_item_add_and_del_use_the_players_segment():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    assert set(client.items) == {SEGMENT}
    assert list(client.items[SEGMENT]) == [(10.0, 11.0)]
    assert (SEGMENT, (10.0, 11.0)) in client.item_stamps
    client._handle_packet(PacketID.PLO_ITEMDEL, _g(20, 22))
    assert client.items[SEGMENT] == {}


def test_chest_sign_and_link_use_the_players_segment():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_LEVELCHEST, _g(0, 5, 6))
    client._handle_packet(PacketID.PLO_LEVELSIGN, _g(3, 4) + b"x")
    client._handle_packet(PacketID.PLO_LEVELLINK, b"door.nw 1 2 3 4 5 6")
    assert set(client.chests) == {SEGMENT}
    assert set(client.signs) == {SEGMENT}
    assert set(client.links) == {SEGMENT}


def test_horse_and_baddy_use_the_players_segment():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_HORSEADD, _g(8, 10, 0) + b"horse.png")
    assert set(client.horses) == {SEGMENT}
    client._handle_packet(PacketID.PLO_HORSEDEL, _g(8, 10))
    assert client.horses[SEGMENT] == {}
    client._handle_packet(PacketID.PLO_BADDYPROPS, build_baddy_props(5, {5: 2}))
    assert set(client.baddies) == {SEGMENT}


def test_bomb_add_and_del_use_the_players_segment():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_BOMBADD, bytes((32, 32, 32 + 12, 32 + 44, 33, 32 + 60)))
    assert [r['level'] for r in client._bomb_records()] == [SEGMENT]
    client._handle_packet(PacketID.PLO_BOMBDEL, _g(12, 44))
    assert list(client._bomb_records()) == []


def test_board_modify_uses_the_players_segment():
    """Regression guard: it passes without the two-target fix too, because the
    board delta already resolved the player's segment by position."""
    client = _client_on_map()
    client.levels[SEGMENT] = [0] * 4096
    client.levels[MAP] = [0] * 4096
    client._handle_packet(PacketID.PLO_BOARDMODIFY, _g(1, 1, 1, 1, 0, 5))
    assert client.levels[SEGMENT][64 + 1] == 5
    assert client.levels[MAP][64 + 1] == 0


def test_board_modify2_falls_back_to_the_players_segment_not_the_map():
    client = _client_on_map()
    client.gmap_grid = {}
    client.levels[SEGMENT] = [0] * 4096
    client.levels[MAP] = [0] * 4096
    client._handle_packet(PacketID.PLO_BOARDMODIFY2, _g(0, 0, 1, 1, 1, 1, 0, 6))
    assert client.levels[MAP][64 + 1] == 0
    assert client.levels[SEGMENT][64 + 1] == 6


def test_plain_level_pending_name_is_unchanged():
    client = Client("localhost", 14900)
    client._current_level_name = "a.nw"
    client._level_scope = "b.nw"
    assert client._level_scope_name() == "b.nw"


def test_adjacent_preload_data_lands_in_the_neighbour_and_scope_returns():
    client = _client_on_map()
    client._adjacent_level_requests.add(OTHER)
    client._handle_packet(PacketID.PLO_LEVELNAME, OTHER.encode())
    assert client._level_scope == OTHER
    client._handle_packet(PacketID.PLO_LEVELCHEST, _g(0, 5, 6))
    client._handle_packet(PacketID.PLO_LEVELSIGN, _g(3, 4) + b"x")
    client._handle_packet(PacketID.PLO_LEVELLINK, b"door.nw 1 2 3 4 5 6")
    assert set(client.chests) == {OTHER} and (5, 6) in client.chests[OTHER]
    assert set(client.signs) == {OTHER}
    assert set(client.links) == {OTHER}
    # the closing PLO_LEVELNAME of the block names the map: scope is B again
    client._handle_packet(PacketID.PLO_LEVELNAME, MAP.encode())
    assert client._level_scope_name() == SEGMENT
    assert client._current_level_name == SEGMENT
    # a preload never touches the NPC owner
    assert client._npc_level == MAP


def test_a_neighbours_items_are_dropped_like_the_reference():
    client = _client_on_map()
    client._adjacent_level_requests.add(OTHER)
    client._handle_packet(PacketID.PLO_LEVELNAME, OTHER.encode())
    client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    client.make_explosion = Mock()
    client._handle_packet(PacketID.PLO_EXPLOSION, bytes((32, 32, 33, 52, 52, 35)))
    assert client.items == {}
    client.make_explosion.assert_not_called()
    # back in the player's own level the same packet is taken
    client._handle_packet(PacketID.PLO_LEVELNAME, MAP.encode())
    client._handle_packet(PacketID.PLO_EXPLOSION, bytes((32, 32, 33, 52, 52, 35)))
    client.make_explosion.assert_called_once()


def test_a_live_packet_for_another_level_does_not_move_the_item_scope():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, OTHER.encode())
    client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, SEGMENT.encode())
    assert client._npc_level == SEGMENT
    assert set(client.items) == {SEGMENT}


def test_a_plain_level_scope_follows_level_name_not_set_active_level():
    client = Client("localhost", 14900)
    client._current_level_name = "own.nw"
    client._handle_packet(PacketID.PLO_LEVELNAME, b"own.nw")
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, b"other.nw")
    client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    client._handle_packet(PacketID.PLO_SETACTIVELEVEL, b"own.nw")
    assert set(client.items) == {"own.nw"}
    assert client._npc_level == "own.nw"


def test_the_current_map_name_resolves_to_a_segment_without_a_grid():
    client = Client("localhost", 14900)
    client.gmap_name = MAP
    client._current_level_name = MAP
    client._level_scope = MAP
    client._level_scope_segment = SEGMENT
    assert client._level_scope_name() == SEGMENT
    assert client.own_level_name() == SEGMENT
    client._level_scope_segment = ""
    assert client._level_scope_name() == ""


def test_an_unplaced_player_does_not_pick_cell_zero_zero():
    client = _client_on_map()
    client._level_scope = MAP
    client._level_scope_segment = SEGMENT
    client.player.x = client.player.y = 0.0
    assert client._level_scope_name() == SEGMENT
    client.player.x, client.player.y = 3.0, 3.0
    assert client._level_scope_name() == OTHER


def test_another_map_name_leaves_the_scope_unchanged():
    client = _client_on_map()
    client.gmap_name = MAP
    client._level_scope = SEGMENT
    client._handle_packet(PacketID.PLO_LEVELNAME, b"elsewhere.gmap")
    assert client._level_scope == SEGMENT
    assert client._npc_level == MAP


def _gmap_entry_client():
    """A client that has the map file but has not yet entered it."""
    client = Client("localhost", 14900)
    client.gmap_name = MAP
    client.gmap_width, client.gmap_height = 2, 1
    client.gmap_grid = {(0, 0): OTHER, (1, 0): SEGMENT}
    client._requested_gmap = MAP
    return client


def test_the_gmap_entry_stream_in_reference_order_files_under_the_segment():
    """PlayerClient.cpp:1459-1555: warp, LEVELNAME sub.nw, board, links, chests,
    signs, LEVELMODTIME, LEVELNAME map.gmap, dynamic data, SETACTIVELEVEL map."""
    client = _gmap_entry_client()
    send = client._handle_packet
    # PLO_PLAYERWARP2: x, y, z, map x, map y, level name
    send(PacketID.PLO_PLAYERWARP2, _g(10, 20, 0) + _g(1, 0) + MAP.encode())
    assert client._level_scope == MAP
    send(PacketID.PLO_LEVELNAME, SEGMENT.encode())
    assert client._level_scope == SEGMENT
    send(PacketID.PLO_BOARDPACKET, bytes(8192))
    send(PacketID.PLO_LEVELLINK, b"door.nw 1 2 3 4 5 6")
    send(PacketID.PLO_LEVELCHEST, _g(0, 5, 6))
    send(PacketID.PLO_LEVELSIGN, _g(3, 4) + b"x")
    send(PacketID.PLO_LEVELNAME, MAP.encode())
    assert client._level_scope == MAP
    send(PacketID.PLO_BADDYPROPS, build_baddy_props(5, {5: 2}))
    send(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    send(PacketID.PLO_SETACTIVELEVEL, MAP.encode())
    assert client._npc_level == MAP
    assert SEGMENT in client.levels and MAP not in client.levels
    for store in (client.links, client.chests, client.signs, client.baddies,
                  client.items):
        assert set(store) == {SEGMENT}


def _warp_without_level_name(version):
    client = Client("localhost", 14900, version=version)
    client._handle_packet(PacketID.PLO_LEVELNAME, b"first.nw")
    client._current_level_name = "first.nw"
    client.player.level = "first.nw"
    client._handle_packet(PacketID.PLO_PLAYERWARP, _g(20, 20) + b"second.nw")
    # A modern flow's LEVELNAME sets this; only the original flow lacks it.
    client._current_level_name = "second.nw"
    client.make_explosion = Mock()
    client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
    client._handle_packet(PacketID.PLO_EXPLOSION, bytes((32, 32, 33, 52, 52, 35)))
    return client


def test_an_original_flow_session_follows_its_warp_without_level_name():
    """The original-client flow (login type PLTYPE_CLIENT: 1.411, 2.17) sends
    PLO_LEVELNAME once (PlayerClientOriginal.cpp:158-160). The warp names the
    level, so items, explosions and the own level name follow it."""
    for version in ("1.411", "2.17"):
        client = _warp_without_level_name(version)
        assert client._current_level_name == "second.nw"
        assert client._level_scope == "second.nw"
        assert client._npc_level == "second.nw"
        assert set(client.items) == {"second.nw"}
        client.make_explosion.assert_called_once()
        client._handle_packet(PacketID.PLO_BOARDPACKET, bytes(8192))
        assert "second.nw" in client.levels and "first.nw" not in client.levels
        assert client._tiles_level_name == "second.nw"


def test_a_modern_flow_session_keeps_the_reference_drop_after_a_warp():
    """Every other version is served by PlayerClient, which names every level.
    A warp alone leaves the scope on the first level and binds only the NPC
    target (TPlayer.cpp:941-946), so a later item or explosion is dropped
    (TClient.cpp:3595)."""
    for version in ("2.21", "2.22", "6.037"):
        client = _warp_without_level_name(version)
        assert client._level_scope == "first.nw"
        assert client._npc_level == "second.nw"
        assert client.items == {}
        client.make_explosion.assert_not_called()
        # the level name that does follow is applied
        client._handle_packet(PacketID.PLO_LEVELNAME, b"second.nw")
        client._handle_packet(PacketID.PLO_ITEMADD, _g(20, 22, 1))
        assert set(client.items) == {"second.nw"}


def test_a_warp_naming_the_current_map_moves_the_scope_to_the_map():
    client = _client_on_map()
    client._level_scope = SEGMENT
    client._handle_packet(PacketID.PLO_PLAYERWARP, _g(20, 20) + MAP.encode())
    assert client._level_scope == MAP
    client._level_scope = SEGMENT
    client._handle_packet(PacketID.PLO_PLAYERWARP2,
                          _g(10, 20, 0) + _g(1, 0) + MAP.encode())
    assert client._level_scope == MAP


def test_a_warp_naming_an_unloaded_map_leaves_the_scope():
    client = Client("localhost", 14900)
    client._level_scope = "own.nw"
    client._handle_packet(PacketID.PLO_PLAYERWARP, _g(20, 20) + b"other.gmap")
    assert client._level_scope == "own.nw"


def test_a_level_name_for_another_map_leaves_the_scope_through_the_handlers():
    client = _client_on_map()
    client._handle_packet(PacketID.PLO_LEVELNAME, SEGMENT.encode())
    client._handle_packet(PacketID.PLO_LEVELNAME, b"elsewhere.gmap")
    assert client._level_scope == SEGMENT
    assert client._level_scope_name() == SEGMENT
