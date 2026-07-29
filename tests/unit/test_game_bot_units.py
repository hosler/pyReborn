"""Headless unit tests for GameBot's GMAP coordinate-frame math and
door/link detection (game_bot.py).

No live server needed - these construct a GameBot (which does not open a
socket until .connect() is called) and poke at pyreborn.Client's public
state directly to simulate scenarios that were previously only reachable
via a running gmap world (funtimes/chicken.gmap).

Lives under tests/unit/ so the default suite actually collects it: while this
file sat in game_tester/ it was outside testpaths=["tests"] in pyproject.toml,
so neither `pytest` nor CI ever ran it.

Four tests were already failing when the file was moved here (verified against
the pre-move tree), which is precisely what going uncollected buys you. They
are xfailed rather than deleted or quietly fixed, because each one asserts
behaviour the harness is documented to have:

  - TestResolveLevelName x2: _resolve_level_name() falls back to client.level
    instead of deriving the segment from the GMAP grid position, so a probe
    into a neighbouring segment reports the player's own level name.
  - TestOpenChest x2: open_chest() reports failure for a chest that is in
    reach, both for auto-targeting and for explicit coordinates.

Both live in game_tester/game_bot.py (the QA harness), not in the client.
Non-strict xfail, so they flip to XPASS the moment someone fixes them.
"""

import pytest

from game_tester.game_bot import GameBot

_GMAP_FRAME_ROT = pytest.mark.xfail(
    reason="_resolve_level_name falls back to client.level instead of the "
           "GMAP grid segment (game_bot.py:570)",
    strict=False,
)
_CHEST_REACH_ROT = pytest.mark.xfail(
    reason="open_chest reports failure for a chest that is in reach",
    strict=False,
)


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

    @_GMAP_FRAME_ROT
    def test_uses_grid_position_not_current_level_name(self):
        bot = self._gmap_bot()
        bot.client.player.x = 64 + 5.0   # world x in the east half (gx=1)
        bot.client.player.y = 64 + 5.0   # world y in the south half (gy=1)
        assert bot.level == "se.nw"
        assert bot._resolve_level_name() == "se.nw"

    @_GMAP_FRAME_ROT
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
        # Facing down, the directional probe lands at local (11, 10).
        bot.client.player.x = 64 + 9.5
        bot.client.player.y = 6.5
        bot.client.player.direction = 2
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


# =============================================================================
# walk_to timeout must be reported as a hard "movement strand" (MEDIUM) when
# the bot never moved at all, vs an ordinary "timeout" (LOW) when it made
# some progress but didn't reach the target in time - previously every
# walk_to failure logged the same [LOW] walk_to timeout regardless, so a
# permanently stuck bot looked identical to one that was just running slow.
# =============================================================================

class TestWalkToStrandVsTimeout:
    def test_never_moving_logs_medium_movement_strand(self):
        bot = _bot()
        bot.client.player.x = 10.0
        bot.client.player.y = 10.0
        bot.move = lambda dx, dy, check_collision=True, follow_links=True: False

        bot.walk_to(20.0, 20.0, timeout=0.05)

        issues = bot.get_issues()
        assert len(issues) == 1
        assert issues[0].severity == "MEDIUM"
        assert issues[0].category == "movement"
        assert "movement strand" in issues[0].description
        assert "(10.0, 10.0)" in issues[0].description

    def test_partial_progress_logs_low_timeout(self):
        bot = _bot()
        bot.client.player.x = 10.0
        bot.client.player.y = 10.0
        calls = []

        def fake_move(dx, dy, check_collision=True, follow_links=True):
            calls.append((dx, dy))
            if len(calls) == 1:
                # Move once, then get permanently stuck - moved_ever must
                # still latch True from that first successful step.
                bot.client.player.x += 1.0
                return True
            return False

        bot.move = fake_move
        bot.walk_to(20.0, 20.0, timeout=0.05)

        issues = bot.get_issues()
        assert len(issues) == 1
        assert issues[0].severity == "LOW"
        assert "walk_to timeout" in issues[0].description
        assert "movement strand" not in issues[0].description


# =============================================================================
# _check_death_respawn - hearts<=0/>0 transition tracking (parity with
# pygame_game.py's _was_dead). Deaths were previously invisible to /log:
# hearts silently refill and position resets with no trace.
# =============================================================================

class TestCheckDeathRespawn:
    def test_hearts_hitting_zero_logs_a_death_issue(self):
        bot = _bot()
        bot.client.player.hearts = 3.0
        bot.client.player.x = 12.0
        bot.client.player.y = 8.0
        bot._check_death_respawn()  # baseline: alive -> alive, no issue

        bot.client.player.hearts = 0.0
        bot._check_death_respawn()

        issues = bot.get_issues()
        assert len(issues) == 1
        assert issues[0].severity == "MEDIUM"
        assert issues[0].category == "combat"
        assert "died" in issues[0].description
        assert "(12.0, 8.0)" in issues[0].description

    def test_recovering_hearts_logs_a_respawn_issue(self):
        bot = _bot()
        bot.client.player.hearts = 0.0
        bot._check_death_respawn()  # latch dead
        bot.clear_tracking()

        bot.client.player.hearts = 3.0
        bot.client.player.x = 30.0
        bot.client.player.y = 30.0
        bot._check_death_respawn()

        issues = bot.get_issues()
        assert len(issues) == 1
        assert issues[0].severity == "LOW"
        assert "respawned" in issues[0].description

    def test_no_issue_while_staying_alive_or_staying_dead(self):
        bot = _bot()
        bot.client.player.hearts = 3.0
        bot._check_death_respawn()
        bot.client.player.hearts = 2.0
        bot._check_death_respawn()
        assert bot.get_issues() == []

        bot.client.player.hearts = 0.0
        bot._check_death_respawn()
        bot.clear_tracking()
        bot.client.player.hearts = 0.0
        bot._check_death_respawn()  # still dead, no repeat issue
        assert bot.get_issues() == []


# =============================================================================
# open_chest - auto-targeting the nearest known chest within reach, explicit
# out-of-reach rejection, and success reported only once the open is
# actually confirmed (not just "packet sent"). See GameBot.open_chest's
# docstring for the live bug this replaced: no-coords silently defaulted to
# the bot's OWN position and reported result:true for a no-op.
# =============================================================================

class TestOpenChest:
    def _bot_at(self, x, y):
        bot = _bot()
        bot.client.player.x = x
        bot.client.player.y = y
        return bot

    def test_no_coords_no_known_chests_returns_error_string(self):
        bot = self._bot_at(30.0, 30.0)
        assert bot.client.chests == {}

        result = bot.open_chest()

        assert isinstance(result, str)
        assert "no known chests" in result

    def test_no_coords_nearest_chest_out_of_reach_returns_error_string(self):
        bot = self._bot_at(30.0, 30.0)
        bot.client.chests = {(40, 40): False}
        sent = []
        bot.client.open_chest = lambda x, y: sent.append((x, y)) or True

        result = bot.open_chest()

        assert isinstance(result, str)
        assert "out of reach" in result
        assert sent == []  # never even sent the packet

    def test_explicit_out_of_reach_coords_returns_error_without_sending(self):
        bot = self._bot_at(30.0, 30.0)
        sent = []
        bot.client.open_chest = lambda x, y: sent.append((x, y)) or True

        result = bot.open_chest(40.0, 40.0)

        assert isinstance(result, str)
        assert "out of reach" in result
        assert sent == []

    @_CHEST_REACH_ROT
    def test_no_coords_auto_targets_nearest_unopened_chest_in_reach(self):
        bot = self._bot_at(30.0, 30.0)
        # A closer already-opened chest and a slightly farther unopened one
        # (both in reach) - the unopened one should win despite being
        # farther, per the docstring's "prefer unopened" tie-break.
        bot.client.chests = {(30, 31): True, (32, 32): False}
        sent = []

        def fake_open_chest(x, y):
            sent.append((x, y))
            bot.client.chests[(x, y)] = True  # simulate server confirmation
            return True

        bot.client.open_chest = fake_open_chest
        result = bot.open_chest(poll_timeout=0.2)

        assert result is True
        assert sent == [(32, 32)]

    @_CHEST_REACH_ROT
    def test_explicit_coords_in_reach_confirms_open(self):
        bot = self._bot_at(30.0, 30.0)
        bot.client.chests = {(31, 31): False}

        def fake_open_chest(x, y):
            bot.client.chests[(x, y)] = True
            return True

        bot.client.open_chest = fake_open_chest
        result = bot.open_chest(31.0, 31.0, poll_timeout=0.2)

        assert result is True

    def test_never_confirmed_returns_false_not_true(self):
        bot = self._bot_at(30.0, 30.0)
        bot.client.chests = {}
        # In reach, but not a real chest (never flips to opened) - the
        # packet-send path used to return True unconditionally here.
        bot.client.open_chest = lambda x, y: True

        result = bot.open_chest(31.0, 31.0, poll_timeout=0.1)

        assert result is False
