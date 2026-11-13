"""Pixel pins for the nameplate / alpha twins of render_entities.py.

Covers what tests/offline_checks.py:check_nameplates does not: a static-image
NPC's plate anchor, the " (paused)" suffix, and every alpha case (hidden
status, ghost mode 1 and 2, the local player's combat alpha, another
player's hidden status). Expected pixels are worked out from the layout
(tests/offline_expect.py), not from the renderer's own arithmetic.
"""

import offline_expect as ex
import offline_game as og
import pytest
from offline_checks import floor_tile, settle, top_left
from offline_game import IMAGE_NPC, OTHER_LOOK
from pyreborn.alignment import alignment_color
from pyreborn.game.assets import render_outlined_text

HIDDEN = 0x02


def _plate(game, text, color):
    return render_outlined_text(game.font_small, text, color, (0, 0, 0))


def _blend(base, over, alpha):
    return tuple(round(b + (o - b) * alpha / 255) for b, o in zip(base, over))


def _scene(make_game, **extra):
    return make_game(
        tiles=floor_tile, player_xy=(30.0, 30.0),
        players=[dict({"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"},
                      **OTHER_LOOK)], **extra)


def _body_sample(frame, origin, x, y, body, head, direction=2):
    """(pixel, opaque colour, colour under it, bare tile colour) of a body point of the
    character whose top-left is tile (x, y). Its gani draws the shadow first:
    a 24x12 black ellipse (alpha 80) at (12, 34), so a point near the
    ellipse centre (24, 40), clear of the head (ends at y 34) and the shield
    (starts at x 26), sits over tile colour darkened by 80/255. The point is
    also off the tile outline (offset 4..11 of 16 on both axes)."""
    zx, zy = top_left(origin, 0.0, 0.0)
    tlx, tly = top_left(origin, x, y)
    bx = next(b for b in range(10, 17)
              if 4 <= (tlx + og.BODY_AT[0] + b - zx) % 16 <= 11)
    by = next(b for b in range(21, 28)
              if 4 <= (tly + og.BODY_AT[1] + b - zy) % 16 <= 11)
    pos = (tlx + og.BODY_AT[0] + bx, tly + og.BODY_AT[1] + by)
    assert 18 <= pos[0] - tlx <= 30 and 37 <= pos[1] - tly <= 43, pos
    color = og.sheet_color_at(body, direction * og.CELL_PX + bx, by)
    tile = og.tile_color(floor_tile((pos[0] - zx) // 16, (pos[1] - zy) // 16))
    return pos, color, _blend(tile, (0, 0, 0), 80), tile


def _expect_alpha(frame, sample, alpha, what):
    pos, color, under, _tile = sample
    want = _blend(under, color, alpha)
    got = ex.pixel(frame, pos)
    assert all(abs(g - w) <= 2 for g, w in zip(got, want)), (
        f"{what}: {got}, expected {want} (alpha {alpha})")


def test_image_npc_plate_anchor(make_game):
    # A static image NPC's plate hangs from the image's bottom centre:
    # x + width/2, y + height, here the 32x32 part -> +16, +32. Blue.
    npc = dict(IMAGE_NPC, nickname="Signpost")
    game = _scene(make_game, npcs=[npc])
    frame = settle(game, label="alpha_helper_image_npc")
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, "Signpost", (0, 0, 255))
    nx, ny = top_left(origin, 24.0, 24.0)
    ex.expect_text_at(frame, plate, (nx + 16 - plate.get_width() // 2, ny + 32),
                      "image NPC nameplate")


def test_paused_suffix_own_and_other(make_game):
    game = _scene(make_game)
    game.client.player.status = 1
    game.client.players[5]["status"] = 1
    frame = settle(game, label="alpha_helper_paused")
    origin = ex.level_origin(game, (30.0, 30.0))
    own = _plate(game, og.ACCOUNT + " (paused)",
                 alignment_color(game.client.player.ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    ex.expect_text_at(frame, own, (ox + 24 - own.get_width() // 2, oy + 48),
                      "own paused nameplate")
    peer = game.client.players[5]
    bob = _plate(game, peer["nickname"] + " (paused)",
                 alignment_color(peer["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 48),
                      "other paused nameplate")


def test_own_alpha_visible_is_opaque(make_game):
    game = _scene(make_game)
    frame = settle(game, label="alpha_helper_own_plain")
    origin = ex.level_origin(game, (30.0, 30.0))
    _expect_alpha(frame, _body_sample(frame, origin, 30.0, 30.0, "body.png",
                                      "head0.png"), 255, "own plain")


@pytest.mark.parametrize("how", ["status", "ghost1"])
def test_own_alpha_hidden_or_ghost(make_game, how):
    game = _scene(make_game)
    if how == "status":
        game.client.player.status = HIDDEN
    else:
        game.client.ghost_mode = 1
    frame = settle(game, label=f"alpha_helper_own_{how}")
    origin = ex.level_origin(game, (30.0, 30.0))
    _expect_alpha(frame, _body_sample(frame, origin, 30.0, 30.0, "body.png",
                                      "head0.png"), 115, f"own {how}")


def test_own_ghost2_not_drawn(make_game):
    game = _scene(make_game)
    game.client.ghost_mode = 2
    frame = settle(game, label="alpha_helper_own_ghost2")
    origin = ex.level_origin(game, (30.0, 30.0))
    pos, _color, _under, tile = _body_sample(frame, origin, 30.0, 30.0,
                                             "body.png", "head0.png")
    ex.expect_pixel(frame, pos, tile, "own player under ghost mode 2")
    own = _plate(game, og.ACCOUNT, alignment_color(game.client.player.ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    matching, total = ex.opaque_matches(
        frame, own, (ox + 24 - own.get_width() // 2, oy + 48))
    assert matching < total, "ghost mode 2 still draws the own nameplate"


@pytest.mark.parametrize("hidden, want", [(False, 127), (True, 57)])
def test_own_alpha_goes_through_combat_alpha(make_game, hidden, want):
    # The local player's alpha is passed through combat_presentation: the
    # stub halves whatever base it is handed (255 -> 127, hidden 115 -> 57).
    game = _scene(make_game)
    game.combat_presentation.player_alpha = lambda now, base: base // 2
    if hidden:
        game.client.player.status = HIDDEN
    frame = settle(game, label=f"alpha_helper_combat_{hidden}")
    origin = ex.level_origin(game, (30.0, 30.0))
    _expect_alpha(frame, _body_sample(frame, origin, 30.0, 30.0, "body.png",
                                      "head0.png"), want, "own combat alpha")


@pytest.mark.parametrize("hidden, want", [(False, 255), (True, 115)])
def test_other_alpha(make_game, hidden, want):
    game = _scene(make_game)
    game.combat_presentation.player_alpha = lambda now, base: 0  # must not apply
    game.client.ghost_mode = 1                                   # must not apply
    if hidden:
        game.client.players[5]["status"] = HIDDEN
    frame = settle(game, label=f"alpha_helper_other_{hidden}")
    origin = ex.level_origin(game, (30.0, 30.0))
    _expect_alpha(frame, _body_sample(frame, origin, 20.0, 20.0, "body2.png",
                                      "head1.png", 0), want, "other player")
