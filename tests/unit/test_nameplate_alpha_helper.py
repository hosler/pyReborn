"""Pixel pins for the nameplate / alpha twins of render_entities.py.

Covers what tests/offline_checks.py:check_nameplates does not: that an image
NPC draws no plate, a character NPC's alignment colour, the " (paused)" suffix, and every alpha case (hidden
status, ghost mode 1 and 2, the local player's combat alpha, another
player's hidden status). Expected pixels are worked out from the layout
(tests/offline_expect.py), not from the renderer's own arithmetic.
"""

import offline_expect as ex
import offline_game as og
import pytest
from offline_checks import floor_tile, settle, top_left
from offline_game import IMAGE_NPC, NAMED_NPC, OTHER_LOOK
from pyreborn.packets import PacketID
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


def test_image_npc_draws_no_plate(make_game):
    # The reference draws a nickname only through the player draw, which only a
    # character NPC reaches (TServerNPC.cpp:1886-1891; a non-character NPC
    # takes drawAni/drawNPCImage). A static image NPC with a nickname draws
    # the same frame as the same NPC without one.
    # Mutation: draw the plate for any NPC with a nickname (drop the
    # is_character test in _render_npc) -> fails the pixel count.
    named = _scene(make_game, npcs=[dict(IMAGE_NPC, nickname="Signpost")])
    named.frames(4)
    plain = _scene(make_game, npcs=[dict(IMAGE_NPC)])
    plain.frames(4)
    assert og.changed_pixels(named, plain) == 0


def test_gani_npc_without_a_character_look_draws_no_plate(make_game):
    # A gani NPC whose image prop is a real image (not empty, not showcharacter)
    # is not a character: the same frame as without the nickname.
    # Mutation: draw the plate for any NPC with a nickname (drop the
    # is_character test) -> fails the pixel count.
    def build(**extra):
        game = _scene(make_game, npcs=[dict(
            {"id": 104, "x": 24.0, "y": 24.0, "gani": "idle"}, **extra)])
        name = b"pics1.png"
        game.feed(PacketID.PLO_NPCPROPS,
                  bytes(((104 >> 14) + 32, ((104 >> 7) & 0x7F) + 32,
                         (104 & 0x7F) + 32, 32, len(name) + 32)) + name)
        game.frames(4)
        return game
    named, plain = build(nickname="Statue"), build()
    assert named.client.npcs[104]["nickname"] == "Statue"
    assert "is_character" not in named.client.npcs[104]
    assert og.changed_pixels(named, plain) == 0


def test_character_npc_plate_uses_its_alignment(make_game):
    # The plate colour is alignment_color(NPCPROP 33): fed as the wire prop,
    # centred 24 px in from the NPC's x, 40 px down.
    # Mutation: colour it alignment_color(50) always (ignore npc['ap']) ->
    # the 80 AP (green) plate no longer matches.
    from pyreborn.packets import PacketID
    game = _scene(make_game, npcs=[dict(NAMED_NPC)])
    game.feed(PacketID.PLO_NPCPROPS,
              bytes(((103 >> 14) + 32, ((103 >> 7) & 0x7F) + 32,
                     (103 & 0x7F) + 32, 33 + 32, 80 + 32)))
    assert game.client.npcs[103]["ap"] == 80
    frame = settle(game, label="alpha_helper_npc_ap")
    origin = ex.level_origin(game, (30.0, 30.0))
    plate = _plate(game, "Offline Guard", alignment_color(80))
    nx, ny = top_left(origin, 28.0, 34.0)
    ex.expect_text_at(frame, plate, (nx + 24 - plate.get_width() // 2, ny + 40),
                      "NPC nameplate at 80 AP")


def test_other_player_on_a_horse_has_its_plate_one_tile_higher(make_game):
    # A horse subtracts another 1.0 from y before the +3.5 (TServerPlayer.cpp:
    # 1339-1340, :1424): 1.5 tiles, 24 px, below the player's y instead of 40.
    # Mutation: ignore horse_image in _render_other_player (no horse=...) ->
    # the plate stays at +40 and no longer matches.
    game = _scene(make_game)
    game.client.players[5]["horse_image"] = "horse.png"
    frame = settle(game, label="alpha_helper_horse")
    origin = ex.level_origin(game, (30.0, 30.0))
    bob = _plate(game, game.client.players[5]["nickname"],
                 alignment_color(game.client.players[5]["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 24),
                      "other player nameplate on a horse")


def _own_plate_top(game, label, dy):
    """Assert the local player's plain plate sits dy px below its ground y."""
    frame = settle(game, label=label)
    origin = ex.level_origin(game, (30.0, 30.0))
    own = _plate(game, og.ACCOUNT, alignment_color(game.client.player.ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    ex.expect_text_at(frame, own, (ox + 24 - own.get_width() // 2, oy + dy),
                      label)


def test_local_player_on_foot_plate_is_56_px_down(make_game):
    # The local player skips the reference's y adjustment: 3.5 tiles = 56 px
    # below its ground y (TServerPlayer.cpp:1424; the gate is the local-player
    # flag, TPlayer.cpp:659).
    # Mutation: pass own=False in _render_player -> the plate sits at +40.
    _own_plate_top(_scene(make_game), "alpha_helper_own_foot", 56)


def test_local_player_on_a_horse_plate_does_not_move(make_game):
    # No horse term for the local player.
    # Mutation: pass horse=bool(player.horse_image) with own=False in
    # _render_player -> the plate sits at +24.
    game = _scene(make_game)
    game.client.player.horse_image = "horse.png"
    _own_plate_top(game, "alpha_helper_own_horse", 56)


def test_local_player_plate_stays_on_the_ground_when_z_is_raised(make_game):
    # The sprite rises by z (1 tile = 16 px) but the local plate does not.
    # Mutation: use y (already minus z) instead of y + z_offset in
    # _render_player -> the plate rises to +40.
    game = _scene(make_game)
    game.client.player.z = 1.0
    _own_plate_top(game, "alpha_helper_own_z", 56)


def test_other_player_plate_follows_a_raised_z(make_game):
    # Another player's plate hangs 40 px below the DRAWN origin, which is
    # raised by z (1 tile = 16 px): 24 px below the ground y.
    # Mutation: use y + z_offset in _render_other_player -> the plate stays
    # at +40.
    game = _scene(make_game)
    game.client.players[5]["z"] = 1.0
    frame = settle(game, label="alpha_helper_other_z")
    origin = ex.level_origin(game, (30.0, 30.0))
    peer = game.client.players[5]
    bob = _plate(game, peer["nickname"], alignment_color(peer["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 24),
                      "other player nameplate with z raised")


def test_nameplate_names_an_empty_nick_unknown(make_game):
    # TServerPlayer.cpp:957-972: an empty nick reads "unknown", " (paused)"
    # after it. Players only; no account fallback.
    # Mutation: drop `name = name or 'unknown'` in _nameplate_label -> the
    # plates read the account / nothing and no longer match.
    game = _scene(make_game)
    game.client.player.nickname = ""
    game.client.players[5]["nickname"] = ""
    game.client.players[5]["status"] = 1
    frame = settle(game, label="alpha_helper_unknown_nick")
    origin = ex.level_origin(game, (30.0, 30.0))
    own = _plate(game, "unknown", alignment_color(game.client.player.ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    ex.expect_text_at(frame, own, (ox + 24 - own.get_width() // 2, oy + 56),
                      "own empty nick")
    peer = game.client.players[5]
    bob = _plate(game, "unknown (paused)", alignment_color(peer["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 40),
                      "other empty paused nick")


def test_paused_suffix_own_and_other(make_game):
    game = _scene(make_game)
    game.client.player.status = 1
    game.client.players[5]["status"] = 1
    frame = settle(game, label="alpha_helper_paused")
    origin = ex.level_origin(game, (30.0, 30.0))
    own = _plate(game, og.ACCOUNT + " (paused)",
                 alignment_color(game.client.player.ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    ex.expect_text_at(frame, own, (ox + 24 - own.get_width() // 2, oy + 56),
                      "own paused nameplate")
    peer = game.client.players[5]
    bob = _plate(game, peer["nickname"] + " (paused)",
                 alignment_color(peer["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 40),
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
        frame, own, (ox + 24 - own.get_width() // 2, oy + 56))
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
