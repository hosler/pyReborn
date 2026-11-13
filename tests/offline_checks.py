"""The colour checks behind tests/unit/test_offline_positions.py: where, what
and in which order the offline frame draws things.

Every assertion here is a colour at a pixel. The synthetic art gives every
tile id, and every cell of every body/head/sword/shield/NPC sheet, a colour of
its own (offline_game.cell_color); the expected pixel and its position come
from tests/offline_expect.py, which works from the canvas size, the 16 px tile
and the documented camera rule and never calls the renderer's own placement
code. So a blit that is 16 px off, a tile id that is off by one, a sprite
cell that is wrong or a draw order that is flipped changes a pixel that one
of these checks names.

``POSITION_CHECKS`` maps a check name to ``fn(make_game)`` that raises
AssertionError. tests/unit/test_offline_positions.py runs each one; test_offline_render.py's
self-check runs them again with a deliberate behavioural mutation applied and
requires them to fail.
"""

from pygame.locals import K_F1

import offline_expect as ex
import offline_game as og
from frame_baseline import capture
from offline_game import (GANI_NPC, IMAGE_NPC, NAMED_NPC, OTHER_LOOK,
                          key_event)
from pyreborn.alignment import alignment_color
from pyreborn.game.assets import render_outlined_text
from pyreborn.tiletypes import TileType, get_tile_type

#: Tile ids that are plain floor (no water shimmer, no chair, no damage), so
#: nothing but the tileset decides what a tile looks like.
FLOOR_IDS = [i for i in range(4096)
             if get_tile_type(i) == TileType.NONBLOCK]


def floor_tile(tx: int, ty: int) -> int:
    return FLOOR_IDS[(tx * 7 + ty * 13) % len(FLOOR_IDS)]


def settle(game, frames: int = 6, label: str = "settled"):
    """Run ``frames`` frames, capturing the first and the last for the frame
    baseline tool, and return the last one."""
    game.frames(1)
    capture(game, f"{label}/f1")
    game.frames(frames - 1)
    capture(game, f"{label}/f{frames}")
    assert game.frame_errors == {}
    return game.last_frame


def top_left(origin, x, y):
    return ex.to_screen(origin, x, y)


# == (a) tiles =================================================================

#: Away from the HUD panel (top-left 240x90 px), the corner hint and the
#: player at tiles 30..33, 30..33.
TILE_SAMPLE = [(0, 16), (63, 16), (0, 54), (63, 54), (10, 22), (52, 22),
               (20, 45), (45, 48), (6, 38), (58, 33), (24, 27), (40, 51)]


def check_tiles(make_game):
    game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0))
    frame = settle(game, label="tiles")
    origin = ex.level_origin(game, (30.0, 30.0))
    assert origin == (0.0, -160.0)       # 1024x720 canvas: x centred, y free
    for what, pos, color in ex.tile_samples(origin, TILE_SAMPLE, floor_tile):
        ex.expect_pixel(frame, pos, color, what)
    # A tile's first pixel is its sheet cell's outline: pins the position to
    # the pixel, where the centre sample alone would forgive a 1-7 px shift.
    for tx, ty in TILE_SAMPLE[:6]:
        sx, sy = ex.to_screen(origin, tx, ty)
        ex.expect_pixel(frame, (sx, sy), og.cell_outline(og.tile_color(
            floor_tile(tx, ty))), f"tile ({tx},{ty}) outline")


# == (b) own player and the camera ===============================================

def _own_body_check(game, frame, origin, xy, direction=2, who="own player"):
    tl = top_left(origin, *xy)
    ex.check_character(frame, tl, "body.png", "head0.png", direction, 0,
                      who=who)
    return tl


def check_camera(make_game):
    # Single level, 64x64 tiles on a 1024x720 canvas: x is always centred
    # (the world is exactly as wide as the view); y follows the player until
    # the level edge clamps it, at the top and at the bottom.
    for y, origin_y in ((30.0, -160.0), (3.0, 0.0), (60.0, -304.0)):
        game = make_game(tiles=floor_tile, player_xy=(30.0, y))
        frame = settle(game, label=f"camera_level_y{int(y)}")
        origin = ex.level_origin(game, (30.0, y))
        assert origin == (0.0, origin_y), "expectation drifted from the rule"
        _own_body_check(game, frame, origin, (30.0, y))
        # the body centre sits on the canvas's mid-height only while the
        # camera is not clamped (x never is: the level is as wide as the view)
        body_y = origin[1] + (y + 2.5) * 16
        assert (body_y == 360.0) == (y == 30.0)
        for what, pos, color in ex.tile_samples(
                origin, [(2, 26), (60, 26), (8, 58)], floor_tile):
            if 0 <= pos[1] < 720:
                ex.expect_pixel(frame, pos, color, f"y={y} {what}")

    # A 2x2 gmap is 128 tiles square: x clamps at both ends and is free in
    # the middle. Our world x is the segment's 64 * column plus the local x.
    for segment, local_x, origin_x in (((0, 0), 2.0, 0.0),
                                       ((0, 0), 60.0, -472.0),
                                       ((1, 0), 60.0, -1024.0)):
        game = make_game(gmap=True, gmap_segment=segment, tiles=floor_tile,
                         player_xy=(local_x, 30.0))
        frame = settle(game, label=f"camera_gmap_{segment[0]}_{local_x:g}")
        world_x = segment[0] * 64 + local_x
        origin = ex.level_origin(game, (world_x, 30.0), (128, 128))
        assert origin == (origin_x, -160.0), (segment, local_x, origin)
        _own_body_check(game, frame, origin, (world_x, 30.0))
        for tx in (world_x - 20, world_x + 18):
            sx, _ = ex.to_screen(origin, tx + 0.5, 0)
            if 0 <= sx < 1024:
                tile = floor_tile(int(tx) % 64, 40)
                ex.expect_pixel(frame, ex.to_screen(origin, tx + 0.5, 40.5),
                                og.tile_color(tile), f"gmap tile {tx}")


# == (c) image NPC, gani NPC, other player ==========================================

def _position_scene(make_game, **extra):
    return make_game(
        tiles=floor_tile, player_xy=(30.0, 30.0),
        npcs=[IMAGE_NPC, GANI_NPC],
        players=[dict({"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"},
                      **OTHER_LOOK)], **extra)


def check_npc_positions(make_game):
    game = _position_scene(make_game)
    frame = settle(game, label="npc_positions")
    origin = ex.level_origin(game, (30.0, 30.0))
    ex.check_image(frame, top_left(origin, 24.0, 24.0), "pics1.png",
                   (0, 0, 32, 32), "image NPC")
    ex.check_character(frame, top_left(origin, 34.0, 24.0), "body3.png",
                       "head2.png", 2, 0, who="gani NPC")


def check_other_player_position(make_game):
    game = _position_scene(make_game)
    frame = settle(game, label="other_player")
    origin = ex.level_origin(game, (30.0, 30.0))
    ex.check_character(frame, top_left(origin, 20.0, 20.0), "body2.png",
                       "head1.png", 0, 0, who="other player")


def check_own_player_position(make_game):
    game = _position_scene(make_game)
    frame = settle(game, label="own_player")
    origin = ex.level_origin(game, (30.0, 30.0))
    ex.check_character(frame, top_left(origin, 30.0, 30.0), "body.png",
                       "head0.png", 2, 0, who="own player")


# == (d) sprite cells: directions and frames ============================================

def check_sprite_cells(make_game):
    # Other players face all four ways at once; each direction picks its own
    # body block and head rows.
    spots = [(6.0, 20.0), (12.0, 20.0), (44.0, 20.0), (50.0, 20.0)]
    players = [dict({"id": 10 + d, "x": x, "y": y, "nickname": f"P{d}",
                     "sprite": d}, **OTHER_LOOK)
               for d, (x, y) in enumerate(spots)]
    game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0), players=players)
    frame = settle(game, label="cells_directions")
    origin = ex.level_origin(game, (30.0, 30.0))
    for d, (x, y) in enumerate(spots):
        ex.check_character(frame, top_left(origin, x, y), "body2.png",
                           "head1.png", d, 0, who=f"other player facing {d}")

    # The own player: same four cells through its own animation state.
    game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0))
    for d in range(4):
        game.player_anim.set_direction(d)
        game.frames(2)
        capture(game, f"cells_own/d{d}")
        ex.check_character(game.last_frame, top_left(origin, 30.0, 30.0),
                           "body.png", "head0.png", d, 0,
                           who=f"own player facing {d}")

    # Walk and sword play two frames each; at 1/60 s a frame, one frame in is
    # still frame 0 and four frames in (0.067 s) is past the 0.05 s step.
    for ani, sword in (("walk", False), ("sword", True)):
        for frames, index in ((1, 0), (4, 1)):
            game = make_game(
                tiles=floor_tile, player_xy=(30.0, 30.0),
                players=[dict({"id": 20, "x": 20.0, "y": 20.0,
                               "nickname": "W", "sprite": 3, "gani": ani},
                              **OTHER_LOOK)])
            game.frames(frames)
            capture(game, f"cells_{ani}/f{frames}")
            ex.check_character(game.last_frame, top_left(origin, 20.0, 20.0),
                               "body2.png", "head1.png", 3, index,
                               sword=sword,
                               who=f"{ani} player, frame {index}")


# == (e) z-order ==============================================================================

def _front_pixel(make_game, a_at, b_at, expect, what, layer=None):
    """Two image NPCs at ``a_at`` / ``b_at``; the overlap pixel is the colour
    of ``expect`` ('a' or 'b')."""
    a = dict(IMAGE_NPC, id=101, x=a_at[0], y=a_at[1])
    b = dict(IMAGE_NPC, id=102, x=b_at[0], y=b_at[1], image="sprites.png")
    game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0), npcs=[a, b])
    frame = settle(game, label=f"zorder_{what}")
    origin = ex.level_origin(game, (30.0, 30.0))
    px, py = ex.to_screen(origin, 25.5, 25.5)
    # world (25.5, 25.5): local (24, 24) of an NPC at (24, 24), local (8, 8)
    # of one at (25, 25).
    colours = {}
    for key, (sheet, at) in (("a", ("pics1.png", a_at)),
                             ("b", ("sprites.png", b_at))):
        colours[key] = og.sheet_color_at(sheet, int((25.5 - at[0]) * 16),
                                         int((25.5 - at[1]) * 16))
    ex.expect_pixel(frame, (px, py), colours[expect],
                    f"overlap pixel, {what}: {expect!r} is in front")
    ex.expect_not_pixel(frame, (px, py), colours["b" if expect == "a" else "a"],
                        f"overlap pixel, {what}")


def check_z_order(make_game):
    # An image's bottom edge is its depth: the one that ends lower is in
    # front. Both orderings, so a flipped sort cannot pass by luck.
    _front_pixel(make_game, (24.0, 24.0), (25.0, 25.0), "b", "b lower")
    _front_pixel(make_game, (25.0, 25.0), (24.0, 24.0), "a", "a lower")
    check_layer_bands(make_game)


def check_layer_bands(make_game):
    """The player against an NPC that draws over or under players. The
    sample point is the player's lower body, (512, 360); the NPC covers it."""
    for ny, script, front in (
            (30.75, "", "player"),                     # NPC ends above: behind
            (30.75, "if (created) {drawoverplayer;}", "npc"),
            (32.0, "", "npc"),                         # NPC ends below: front
            (32.0, "if (created) {drawunderplayer;}", "player")):
        npc = dict(IMAGE_NPC, id=101, x=30.5, y=ny, script=script)
        game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0), npcs=[npc])
        frame = settle(game, label=f"bands_{ny}_{front}")
        origin = ex.level_origin(game, (30.0, 30.0))
        pos = (512, 360)
        assert pos == (int(origin[0] + 32 * 16), int(origin[1] + 32.5 * 16 + 0))
        npc_xy = ex.to_screen(origin, 30.5, ny)
        npc_colour = og.sheet_color_at("pics1.png", pos[0] - npc_xy[0],
                                       pos[1] - npc_xy[1])
        player_colour = og.sheet_color_at("body.png", 2 * 32 + 24, 24)
        want = npc_colour if front == "npc" else player_colour
        ex.expect_pixel(frame, pos, want,
                        f"NPC y={ny} script={script!r}: {front} in front")


# == (f) hearts =================================================================================

HEART_FULL = (255, 50, 50)
HEART_EMPTY = (80, 30, 30)
#: The heart row is drawn at (10, 10), 16 px hearts, 2 px apart, ten a row.
HEART_X0, HEART_Y0, HEART_PITCH = 10, 10, 18


def read_hearts(frame, slots):
    """For each heart slot: 'full', 'half' or 'empty' (or None for no heart),
    read from the pixels a full heart colours in its left and right halves."""
    out = []
    for i in range(slots):
        x = HEART_X0 + (i % 10) * HEART_PITCH
        y = HEART_Y0 + (i // 10) * HEART_PITCH
        left, right = pixel_pair(frame, x + 6, x + 11, y + 9)
        if left == HEART_FULL and right == HEART_FULL:
            out.append("full")
        elif left == HEART_FULL and right == HEART_EMPTY:
            out.append("half")
        elif left == HEART_EMPTY and right == HEART_EMPTY:
            out.append("empty")
        else:
            out.append(None)
    return out


def pixel_pair(frame, x1, x2, y):
    return ex.pixel(frame, (x1, y)), ex.pixel(frame, (x2, y))


def check_hearts(make_game):
    for hearts, maximum, want in (
            (3.0, 3, ["full"] * 3),
            (2.5, 3, ["full", "full", "half"]),
            (1.0, 5, ["full"] + ["empty"] * 4),
            (4.5, 9, ["full"] * 4 + ["half"] + ["empty"] * 4)):
        game = make_game(hearts=hearts, me={"max_hearts": float(maximum)})
        frame = settle(game, label=f"hearts_{hearts}_{maximum}")
        slots = read_hearts(frame, maximum + 1)
        assert slots[:maximum] == want, (
            f"hearts {hearts}/{maximum}: drawn {slots[:maximum]}, want {want}")
        assert slots[maximum] is None, (
            f"hearts {hearts}/{maximum}: a heart is drawn past the maximum")


# == (g) nameplates ===============================================================================

def check_nameplates(make_game):
    game = _position_scene(make_game)
    frame = settle(game, label="nameplates")
    origin = ex.level_origin(game, (30.0, 30.0))
    font = game.font_small
    ap = game.client.player.ap

    def plate(text, color):
        return render_outlined_text(font, text, color, (0, 0, 0))

    # Centred 1.5 tiles (24 px) in from x. The top of the text sits 3.5 tiles
    # (56 px) below the local player's y and 2.5 tiles (40 px) below another
    # player's or a character NPC's (TServerPlayer.cpp:1337, :1424; the
    # local player skips the -1.0 adjustment, TPlayer.cpp:659).
    own = plate(og.ACCOUNT, alignment_color(ap))
    ox, oy = top_left(origin, 30.0, 30.0)
    ex.expect_text_at(frame, own, (ox + 24 - own.get_width() // 2, oy + 56),
                      "own nameplate")
    peer = game.client.players[5]
    assert peer["nickname"] == "*Bob"          # pygserver marks unregistered names
    bob = plate(peer["nickname"], alignment_color(peer["ap"]))
    bx, by = top_left(origin, 20.0, 20.0)
    ex.expect_text_at(frame, bob, (bx + 24 - bob.get_width() // 2, by + 40),
                      "other player nameplate")
    # A character NPC's label is drawn by the reference's player draw: the bare
    # nick, centred 1.5 tiles (24 px) in from the NPC's x, 40 px down, in the
    # alignment colour (default alignment 50: white) -- the same rule as the
    # players' plates above.
    npc = dict(NAMED_NPC)
    game = make_game(tiles=floor_tile, player_xy=(30.0, 30.0), npcs=[npc])
    frame = settle(game, label="nameplates_npc")
    guard = plate("Offline Guard", alignment_color(50))
    nx, ny = top_left(origin, 28.0, 34.0)
    ex.expect_text_at(frame, guard, (nx + 24 - guard.get_width() // 2, ny + 40),
                      "NPC nameplate")


# == (h) debug overlay =============================================================================

def _blend(base, over, alpha):
    return tuple(round(b + (o - b) * alpha / 255) for b, o in zip(base, over))


def check_debug_overlay(make_game):
    """F1's tile overlay: blocking tiles are tinted red (alpha 100), other
    non-empty tiles green (alpha 50), tile 0 is left alone."""
    blocking, walkable = 4, 1
    assert get_tile_type(blocking) == TileType.BLOCKING
    assert get_tile_type(walkable) == TileType.NONBLOCK

    def tiles(tx, ty):
        return {0: blocking, 1: walkable}.get(ty % 3, 0)

    game = make_game(tiles=tiles, player_xy=(30.0, 30.0))
    game.frames(1)
    game.frames(1, events=[key_event(K_F1)])
    game.frames(4)
    capture(game, "debug_tiles/f6")
    assert game.debug_mode
    frame = game.last_frame
    origin = ex.level_origin(game, (30.0, 30.0))
    for tx, ty, tint, alpha in ((8, 21, (255, 0, 0), 100),    # ty % 3 == 0
                                (50, 40, (0, 255, 0), 50),    # ty % 3 == 1
                                (12, 45, (255, 0, 0), 100),
                                (55, 28, (0, 255, 0), 50)):
        base = og.tile_color(tiles(tx, ty))
        want = _blend(base, tint, alpha)
        actual = ex.pixel(frame, ex.to_screen(origin, tx + 0.5, ty + 0.5))
        assert all(abs(a - w) <= 2 for a, w in zip(actual, want)), (
            f"debug tint of tile ({tx},{ty}): {actual}, expected {want}")
    # tile 0 is skipped by the overlay: its own colour, untinted
    tx, ty = 50, 41                                            # ty % 3 == 2
    ex.expect_pixel(frame, ex.to_screen(origin, tx + 0.5, ty + 0.5),
                    og.tile_color(0), "debug overlay leaves tile 0 alone")


POSITION_CHECKS = {
    "tiles": check_tiles,
    "camera": check_camera,
    "own_player_position": check_own_player_position,
    "npc_positions": check_npc_positions,
    "other_player_position": check_other_player_position,
    "sprite_cells": check_sprite_cells,
    "z_order": check_z_order,
    "hearts": check_hearts,
    "nameplates": check_nameplates,
    "debug_overlay": check_debug_overlay,
}
