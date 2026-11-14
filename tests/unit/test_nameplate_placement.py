"""Where a nameplate goes, what it says and when it is hidden.

The reference draws every nick at once, at its own spot, and only keeps it
inside the view (TPlayer.cpp:4105-4165, drawTextTokenAbsolute): there is no
overlap test and no staggering. The label is the nick, "unknown" for an empty
player nick, and " (paused)"; nothing else is appended
(TServerPlayer.cpp:950-985). The nick is skipped while the hurt flag is set
(TServerPlayer.cpp:1416).
"""

import offline_expect as ex
import pygame
import pytest
from offline_checks import floor_tile, settle, top_left
from offline_game import NAMED_NPC, OTHER_LOOK
from pyreborn.alignment import alignment_color
from pyreborn.game.assets import render_outlined_text
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.hurt import HURT_TICKS


def _plate(game, text, color):
    return render_outlined_text(game.font_small, text, color, (0, 0, 0))


def _scene(make_game, others=None, **extra):
    others = others or [{"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}]
    return make_game(
        tiles=floor_tile, player_xy=(30.0, 30.0),
        players=[dict(o, **OTHER_LOOK) for o in others], **extra)


def test_overlapping_plates_are_not_staggered(make_game):
    """Two players on one spot with one nick draw one plate in one place.

    Mutation: in `_draw_nameplate` keep a module-level list of plates placed
    and add `14 * len(placed)` to `top_y` (the old stagger) -> the second
    plate lands a box lower and a second copy of the text appears there.
    """
    others = [{"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"},
              {"id": 6, "x": 20.0, "y": 20.0, "nickname": "Bob"}]  # served as "*Bob"
    game = _scene(make_game, others)
    frame = settle(game, label="placement_no_stagger")
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, game.client.players[5]["nickname"],
                   alignment_color(game.client.players[5]["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    at = (bx + 24 - plate.get_width() // 2, by + 40)
    ex.expect_text_at(frame, plate, at, "both Bob plates")
    _, total = ex.opaque_matches(frame, plate, at)
    lower, _ = ex.opaque_matches(frame, plate,
                                 (at[0], at[1] + plate.get_height() + 2))
    assert lower < total, "a second plate was staggered one box lower"


def test_plate_is_clamped_into_the_view_and_skipped_outside_it(make_game):
    """Centre outside [0, view width]: nothing. Inside: the text is shifted to
    stay within the view (TPlayer.cpp:4105-4165).

    Mutation: in `_draw_nameplate` drop the `min(...)` / `max(0, ...)` clamp
    -> the plate hangs off the left and right edges.
    """
    game = make_game()
    width = game.screen.get_width()
    color = (255, 255, 255)
    plate = _plate(game, "Bobby Longname", color)
    w = plate.get_width()
    for centre, want_x in ((2, 0), (width - 2, width - w), (width // 2,
                                                            width // 2 - w // 2)):
        game.screen.fill((40, 40, 40))
        game._draw_nameplate("Bobby Longname", color, centre, 100)
        matching, total = ex.opaque_matches(game.screen, plate, (want_x, 100))
        assert total and matching == total, (centre, want_x)
    for centre in (-1, width + 1):
        game.screen.fill((40, 40, 40))
        before = pygame.image.tobytes(game.screen, "RGB")
        game._draw_nameplate("Bobby Longname", color, centre, 100)
        assert pygame.image.tobytes(game.screen, "RGB") == before, centre


def test_label_rules():
    """An empty player nick reads "unknown", " (paused)" follows with a space
    only after text, and nothing else is ever appended.

    Mutation: make `_nameplate_label` return `name + " [away]"` -> every
    row below fails.
    """
    label = EntityRenderMixin._nameplate_label
    assert label("", False, 5) == "unknown"
    assert label("", True, 5) == "unknown (paused)"
    assert label("Bob", True, 5) == "Bob (paused)"
    assert label("Bob", False, 5) == "Bob"
    assert label("", True, 0) == "(paused)"
    assert label("", False, 0) == ""


def test_status_list_label_is_not_appended(make_game):
    """A player whose status indexes the server's status list still shows the
    bare nick (nothing in the reference nick path reads that list).

    Mutation: re-add `f"{name} [{self._status_label(status)}]"` to the
    plate text in `_render_other_player` -> the bare nick no longer matches.
    """
    game = _scene(make_game)
    game.client.status_list = ["Idle", "Away"]
    game.client.players[5]["status"] = 0
    frame = settle(game, label="placement_no_status_suffix")
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, game.client.players[5]["nickname"],
                   alignment_color(game.client.players[5]["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, plate, (bx + 24 - plate.get_width() // 2, by + 40),
                      "nick without a status suffix")


def _own_plate_matches(game, label):
    """Whether the local plate is on the frame, searched within 20 px of
    where the player stands (a hurt knocks the player back, so its screen
    spot is not fixed)."""
    frame = settle(game, label=label)
    me = game.client.player
    origin = ex.level_origin(game, (me.x, me.y))
    plate = _plate(game, me.nickname, alignment_color(me.ap))
    ox, oy = top_left(origin, me.x, me.y)
    x0, y0 = ox + 24 - plate.get_width() // 2, oy + 56
    for dx in range(-20, 21):
        matching, total = ex.opaque_matches(frame, plate, (x0 + dx, y0))
        if total and matching == total:
            return True
    return False


def _hurt_local(game):
    """The local player has just been hit (counter 40, action mode 3) after
    the nick grace counter ran out."""
    game.nick_grace_ticks = -1
    player = game.client.player
    player.hurt.start(1.0, 0.0, game.clock.sim_now())
    player.action_mode = 3


def test_local_nick_is_hidden_for_the_first_ten_ticks_of_a_hurt(make_game):
    """TPlayer.cpp:3947: hurt = actionMode == 3 && counter > 30, counter 40
    after a hit, one less per tick: hidden for 10 ticks, then back.

    Mutation: in `_local_nick_visible` return True before the hurt test ->
    the plate is drawn in the hurt window.
    """
    game = _scene(make_game)
    _hurt_local(game)
    assert game.client.player.hurt.ticks < 10
    assert not _own_plate_matches(game, "placement_hurt_hidden")
    game.ticks(HURT_TICKS - 25)
    assert game.client.player.hurt.ticks >= 10
    assert _own_plate_matches(game, "placement_hurt_over")


def _hurt_now(game, hurt_ticks=0):
    """The local player is mid-hurt (action mode 3) with `hurt_ticks` ticks
    of the 40-tick counter gone."""
    player = game.client.player
    player.hurt.start(1.0, 0.0, game.clock.sim_now())
    player.hurt.ticks = hurt_ticks
    player.action_mode = 3


def test_local_nick_ignores_a_hurt_while_the_grace_counter_is_not_below_zero(
        make_game):
    """TPlayer::draw draws the nick again with no hurt test while the counter
    (TPlayer.cpp:785, :5636, :3962, :7250) is >= 0.

    Mutation: change `self.nick_grace_ticks >= 0` to `> 0` in
    `_local_nick_visible` -> the counter at 0 hides the nick.
    """
    game = _scene(make_game)
    _hurt_now(game)
    game.nick_grace_ticks = 0
    assert game._local_nick_visible()
    game.nick_grace_ticks = -1
    assert not game._local_nick_visible()
    game.nick_grace_ticks = 5
    game.frames(1)
    assert _own_plate_matches(game, "placement_hurt_in_grace")


def test_grace_lasts_61_ticks_after_the_respawn_and_not_after_a_warp(make_game):
    """A death ends in loadStartLevel (TPlayer.cpp:2166, :5636) which sets
    the counter to 60: drawn on tick 60 (counter 0), hurt-hidden on tick 61
    (counter -1). A warp does not set it.

    Mutation: set `_NICK_START_GRACE_TICKS = 59` -> hidden on tick 60.
    Mutation: skip the re-arm on respawn in `_simulation_tick` -> the first
    assert after the respawn fails.
    """
    game = _scene(make_game)
    game.ticks(70)
    assert game.nick_grace_ticks == -1
    game.client.player.hearts = 0
    game.ticks(2)
    game.client.player.hearts = 3
    game.ticks(1)                       # the respawn tick sets the counter
    assert game.nick_grace_ticks == 60
    game.ticks(60)
    _hurt_now(game)
    assert game.nick_grace_ticks == 0 and game._local_nick_visible()
    game.ticks(1)
    _hurt_now(game)
    assert game.nick_grace_ticks == -1 and not game._local_nick_visible()
    game.ticks(5)
    game.client.warp_to_level("a.nw", 10.0, 10.0)
    game.ticks(3)
    assert game.nick_grace_ticks == -1


def test_hurt_hides_the_nick_for_exactly_ten_ticks(make_game):
    """Hidden while counter > 30, the counter being 40 - hurt.ticks: hidden
    through the 10th tick of a hurt (ticks 0..9), shown from the 11th
    (ticks == 10, counter 30).

    Mutation: change `> 30` to `>= 30` in `_local_nick_visible` -> still
    hidden at hurt.ticks == 10.
    """
    game = _scene(make_game)
    game.nick_grace_ticks = -1
    _hurt_now(game, 9)
    assert not game._local_nick_visible()
    _hurt_now(game, 10)
    assert game._local_nick_visible()


def test_other_player_nick_stays_while_the_hurt_gani_plays(make_game):
    """No code sets another player's hurt flag true (setIsHurt has no such
    caller: TServerPlayer.cpp:254, :1218 NPC branch, :1233, TPlayer.cpp:3947
    is the local player), so a remote player's nick is never hidden.

    Mutation: skip the nick in `_render_other_player` when pdata['ani'] is
    'hurt' -> the plate disappears.
    """
    game = _scene(make_game)
    game.client.players[5]["ani"] = "hurt"
    frame = settle(game, label="placement_other_hurt")
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, game.client.players[5]["nickname"],
                   alignment_color(game.client.players[5]["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, plate, (bx + 24 - plate.get_width() // 2, by + 40),
                      "nick of a player in the hurt gani")


@pytest.mark.parametrize("gani, shown", [("idle", True), ("hurt", True),
                                         ("hiddenstill", False)])
def test_character_npc_nick_follows_its_gani_type(make_game, gani, shown):
    """A server NPC's hurt flag is `gani type in {0x0b, 0x0d}`
    (TServerPlayer.cpp:1213-1218), the stock "hiddenstill" and "hidden".

    Mutation: empty `_NICK_HIDING_GANIS` -> the hiddenstill row draws it.
    Mutation: add 'hurt' to `_NICK_HIDING_GANIS` -> the hurt row loses it.
    """
    npc = dict(NAMED_NPC, gani=gani)
    game = _scene(make_game, npcs=[npc])
    frame = settle(game, label="placement_npc_" + gani)
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, "Offline Guard", alignment_color(50))
    nx, ny = top_left(origin, 28.0, 34.0)
    matching, total = ex.opaque_matches(
        frame, plate, (nx + 24 - plate.get_width() // 2, ny + 40))
    assert (matching == total) is shown
