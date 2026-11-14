"""render_smoke's board-modify check must leave the server's board as it found
it.

tier1b paints one tile next to testbot1 over the wire. A 1x1 board change
never respawns on the server (GServer-v2 Level.cpp:1665-1666, and pygserver's
Level.alter_board follows it), so a tile left behind stays in the server's
copy of the shared fixture level until that server stops. On 2026-11-13 the
painted tile 5 (blocking) sat at (31, 33), south of the spawn, and every later
base run on that server failed collision_detection and chest_interaction.
"""
from game_tester import render_smoke
from pyreborn.packets import PacketID, build_board_modify

_T1B = dict(render_smoke._CHECKS)["tier1b_board_modify_patches_segment_surface_in_place"]
_PEER_ID = 5


class _PeerClient:
    """tier1b's second client (c2): an in-process pygserver peer on our level.
    Its edits go through the server's real PLI_BOARDMODIFY handler, which
    relays them to our client, as the live check's second login does."""

    def __init__(self, game, level_name):
        self.game = game
        self.level_name = level_name

    def get_tile(self, x, y):
        return self.game.server.level(self.level_name).get_tile(x, y)

    def modify_board(self, x, y, width, height, tiles):
        data = build_board_modify(x, y, width, height, tiles)

        async def _edit(world):
            await world.peers[_PEER_ID]._dispatch_packet(
                PacketID.PLI_BOARDMODIFY, data)
        self.game.server.run(_edit)
        return True


def test_tier1b_puts_the_painted_tile_back_on_the_server(make_game):
    """The check passes and the server's tile is the original again.

    Mutation: delete the `c2.modify_board(tx, ty, 1, 1, [original])` line in
    the `finally` of render_smoke._t1b. The server's tile then stays 5 and
    the first tile assertion fails."""
    game = make_game(player_xy=(30.0, 32.0),
                     players=[{"id": _PEER_ID, "x": 34.0, "y": 32.0}])
    client = game.client
    game.frames(3)
    level_name = client._current_level_name
    tx, ty = int(client.x) % 60 + 1, int(client.y) % 60 + 1
    assert (tx, ty) == (31, 33)
    peer = _PeerClient(game, level_name)
    original = peer.get_tile(tx, ty)
    assert original != 5

    _T1B(game, client, peer)

    level = game.server.level(level_name)
    # The server handled the edits: the change list holds the cell.
    assert any(change.x == tx and change.y == ty for change in level.board_changes)
    assert level.get_tile(tx, ty) == original
    assert client.get_tile(tx, ty) == original
    assert game.frame_errors == {}
