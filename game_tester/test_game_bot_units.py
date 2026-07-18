"""Headless unit tests for GameBot's GMAP coordinate-frame math and
door/link detection (game_bot.py).

No live server needed - these construct a GameBot (which does not open a
socket until .connect() is called) and poke at pyreborn.Client's public
state directly to simulate scenarios that were previously only reachable
via a running gmap world (funtimes/chicken.gmap).

NOT part of the default `tests` suite (testpaths=["tests"] in pyproject.toml,
owned outside game_tester/) - run explicitly:

    pytest game_tester/test_game_bot_units.py -q
"""

from game_tester.game_bot import GameBot


def _bot() -> GameBot:
    # Never calls .connect() - Client() doesn't open a socket until then,
    # so this is safe to construct without a running server.
    return GameBot("unittest", "localhost", 1)


# =============================================================================
# _resolve_level_name - the fix for client._current_level_name being a poor
# proxy for "the level the player is standing in" while on a GMAP.
# =============================================================================

class TestResolveLevelName:
    def _gmap_bot(self) -> GameBot:
        bot = _bot()
        bot.client.gmap_width = 2
        bot.client.gmap_height = 2
        bot.client.gmap_grid = {
            (0, 0): "nw.nw", (1, 0): "ne.nw",
            (0, 1): "sw.nw", (1, 1): "se.nw",
        }
        # Simulate the confirmed-live corruption: _current_level_name has
        # been stolen by an unrelated adjacent-segment board announcement.
        bot.client._current_level_name = "WRONG.nw"
        return bot

    def test_uses_grid_position_not_current_level_name(self):
        bot = self._gmap_bot()
        bot.client.player.x = 64 + 5.0   # world x in the east half (gx=1)
        bot.client.player.y = 64 + 5.0   # world y in the south half (gy=1)
        assert bot.level == "se.nw"
        assert bot._resolve_level_name() == "se.nw"

    def test_probed_point_can_differ_from_players_own_segment(self):
        # Collision lookahead probes a point up to a tile away from the
        # player, which can itself be across a segment boundary - the
        # resolver must key off the PROBED point, not just player.x/y.
        bot = self._gmap_bot()
        bot.client.player.x = 63.9   # player still in the west half (gx=0)
        bot.client.player.y = 5.0
        assert bot._resolve_level_name() == "nw.nw"
        assert bot._resolve_level_name(64.1, 5.0) == "ne.nw"

    def test_off_grid_position_falls_back_to_current_level_name(self):
        bot = self._gmap_bot()
        bot.client._current_level_name = "interior.nw"
        # World position way outside the 2x2 grid.
        bot.client.player.x = 900.0
        bot.client.player.y = 900.0
        assert bot._resolve_level_name() == "interior.nw"

    def test_non_gmap_level_uses_current_level_name(self):
        bot = _bot()
        assert bot.client.is_gmap is False
        bot.client._current_level_name = "onlinestartlocal.nw"
        bot.client.player.x = 30.0
        bot.client.player.y = 30.0
        assert bot._resolve_level_name() == "onlinestartlocal.nw"
        assert bot.level == "onlinestartlocal.nw"


# =============================================================================
# _get_tile_at - must read the tile board for whichever segment actually
# owns the probed world position, not client._current_level_name's board.
# =============================================================================

class TestGetTileAt:
    def test_reads_board_for_the_segment_that_owns_the_point(self):
        bot = _bot()
        bot.client.gmap_width = 2
        bot.client.gmap_height = 1
        bot.client.gmap_grid = {(0, 0): "west.nw", (1, 0): "east.nw"}
        bot.client._current_level_name = "west.nw"  # stale/wrong on purpose

        west_tiles = [0] * 4096
        east_tiles = [0] * 4096
        east_tiles[2 * 64 + 2] = -1  # -1 -> TileType.BLOCKING unconditionally
        bot.client.levels = {"west.nw": west_tiles, "east.nw": east_tiles}
        bot.client.tiles = west_tiles

        # World (66, 2) is local (2, 2) of the EAST segment - must read
        # east_tiles, not west_tiles (which is what _current_level_name
        # would incorrectly select).
        assert bot._get_tile_at(66.0, 2.0) == -1
        # The same local (2, 2) on the west segment is untouched (0).
        assert bot._get_tile_at(2.0, 2.0) == 0

    def test_non_gmap_ignores_current_level_name_entirely(self):
        bot = _bot()
        tiles = [0] * 4096
        tiles[5 * 64 + 5] = -1
        bot.client.tiles = tiles
        assert bot._get_tile_at(5.0, 5.0) == -1


# =============================================================================
# check_link_collision - reimplemented in GameBot to key off the position-
# derived level rather than client._current_level_name.
# =============================================================================

class TestCheckLinkCollision:
    def _gmap_bot_with_link(self):
        bot = _bot()
        bot.client.gmap_width = 2
        bot.client.gmap_height = 1
        bot.client.gmap_grid = {(0, 0): "west.nw", (1, 0): "east.nw"}
        bot.client._current_level_name = "west.nw"  # stale/wrong on purpose
        # A non-edge (interior) door link at local (10, 10)-(12, 11) on the
        # EAST segment, going to some standalone interior.
        bot.client.links = {
            "east.nw": [{"x": 10, "y": 10, "width": 3, "height": 1,
                        "dest_level": "cave.nw", "dest_x": "5", "dest_y": "5"}],
        }
        return bot

    def test_detects_link_on_position_derived_level(self):
        bot = self._gmap_bot_with_link()
        # World (64+11, 64*0+10) -> local (11, 10) on the east segment,
        # standing squarely on the link.
        bot.client.player.x = 64 + 11.0
        bot.client.player.y = 10.0
        link = bot.check_link_collision()
        assert link is not None
        assert link["dest_level"] == "cave.nw"

    def test_no_link_when_not_overlapping(self):
        bot = self._gmap_bot_with_link()
        bot.client.player.x = 64 + 30.0
        bot.client.player.y = 30.0
        assert bot.check_link_collision() is None

    def test_edge_link_to_gmap_neighbour_is_ignored(self):
        # Edge links stitch GMAP segments together for seamless walking -
        # check_link_collision must NOT fire a warp for those (client.move()
        # already handles the seamless crossing), only for "interior" doors.
        bot = _bot()
        bot.client.gmap_width = 2
        bot.client.gmap_height = 1
        bot.client.gmap_grid = {(0, 0): "west.nw", (1, 0): "east.nw"}
        bot.client.links = {
            "west.nw": [{"x": 63, "y": 0, "width": 1, "height": 64,
                        "dest_level": "east.nw", "dest_x": "0", "dest_y": "playery"}],
        }
        bot.client.player.x = 63.5
        bot.client.player.y = 30.0
        assert bot.check_link_collision() is None


# =============================================================================
# walk_to's stuck-recovery heuristic must sidestep TOWARD the target, not a
# fixed south-then-east regardless of which way the bot actually needs to go
# (live repro: action log showed dx:+1 "east" move steps while the target
# was west of the bot).
# =============================================================================

class TestWalkToStuckRecoveryDirection:
    def _stuck_bot(self, start_x, start_y):
        bot = _bot()
        bot.client.player.x = start_x
        bot.client.player.y = start_y
        calls = []

        def fake_move(dx, dy, check_collision=True, follow_links=True):
            calls.append((dx, dy))
            return False  # never actually moves -> always "stuck"

        bot.move = fake_move
        return bot, calls

    def test_sidesteps_toward_a_west_target(self):
        # Target due WEST: move_dx=-1, move_dy=0 (no vertical need). Only
        # the move_dx stuck branch should fire, sidestepping along Y.
        bot, calls = self._stuck_bot(10.0, 10.0)
        bot.walk_to(5.0, 10.0, timeout=0.05)

        assert calls[0] == (-1, 0)
        # After 11 consecutive stuck attempts (_stuck_count > 10), the
        # unstick logic fires two sidestep moves before resuming (-1, 0).
        assert calls[11:13] == [(0, 1), (0, 1)]
        # The old fixed heuristic fired self.move(1, 0) here (due EAST) -
        # exactly away from a west target. Assert that never happens.
        assert (1, 0) not in calls[11:13]

    def test_sidesteps_toward_a_northwest_target(self):
        # Target NORTHWEST: move_dx=-1, move_dy=-1 - both stuck branches
        # fire, each sidestepping toward the target's own sign.
        bot, calls = self._stuck_bot(10.0, 10.0)
        bot.walk_to(5.0, 5.0, timeout=0.05)

        assert calls[0] == (-1, -1)
        unstick = calls[11:15]
        assert unstick == [(0, -1), (0, -1), (-1, 0), (-1, 0)]

    def test_sidesteps_toward_a_southeast_target(self):
        bot, calls = self._stuck_bot(5.0, 5.0)
        bot.walk_to(10.0, 10.0, timeout=0.05)

        assert calls[0] == (1, 1)
        unstick = calls[11:15]
        assert unstick == [(0, 1), (0, 1), (1, 0), (1, 0)]
