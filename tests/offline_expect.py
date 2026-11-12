"""Where, what and in which order: expectations that do not call the renderer.

The probes in offline_game.py say that something changed in a region. These
helpers say what colour a pixel must have, and they work it out from the
synthetic art (``cell_color``, ``tile_color``), the canvas size, the 16 px
tile and the documented camera rule only. Nothing here calls
``Camera2D.world_to_screen``, an entity's blit math or a renderer method.

The camera rule (pyreborn/game/camera.py, game/render.py ``_sync_camera``):
the view is centred on the player's body centre, (x + 1.5, y + 2.5) tiles.
On each axis, a world no larger than the view is centred; a larger one clamps
the centre so the view stays inside the world. A level is 64 tiles square; a
gmap is its grid of those.
"""

from typing import Callable, Iterable, List, Tuple

import pygame

import offline_game as og
from offline_game import (BODY_AT, CELL_PX, HEAD_AT, SHIELD_AT,
                          SHIELD_FRAME_STEP, SWORD_AT, cell_color,
                          sheet_color_at, tile_color)

TILE = 16
LEVEL_TILES = 64
#: Body centre, in tiles from the sprite's top-left: the camera's aim point.
BODY_CENTRE = (1.5, 2.5)
Color = Tuple[int, int, int]


def canvas_size(game) -> Tuple[int, int]:
    """The canvas the world is drawn on, from the surface itself."""
    return game.screen.get_size()


def camera_origin(canvas: Tuple[int, int], world_tiles: Tuple[int, int],
                  player_tiles: Tuple[float, float]) -> Tuple[float, float]:
    """Screen pixel of world tile (0, 0) for a player whose top-left is at
    ``player_tiles``, in a world ``world_tiles`` big (both in tiles)."""
    origin = []
    for axis in (0, 1):
        view = canvas[axis] / TILE
        centre = player_tiles[axis] + BODY_CENTRE[axis]
        world = world_tiles[axis]
        if world <= view:
            centre = world / 2
        else:
            centre = max(view / 2, min(world - view / 2, centre))
        origin.append(canvas[axis] / 2 - centre * TILE)
    return origin[0], origin[1]


def level_origin(game, player_tiles: Tuple[float, float],
                 world_tiles: Tuple[int, int] = (LEVEL_TILES, LEVEL_TILES)
                 ) -> Tuple[float, float]:
    return camera_origin(canvas_size(game), world_tiles, player_tiles)


def to_screen(origin: Tuple[float, float], x: float, y: float
              ) -> Tuple[int, int]:
    """Screen pixel of world tile position (x, y)."""
    return int(origin[0] + x * TILE), int(origin[1] + y * TILE)


# -- reading pixels ----------------------------------------------------------

def pixel(frame: "pygame.Surface", pos: Tuple[int, int]) -> Color:
    x, y = pos
    if not (0 <= x < frame.get_width() and 0 <= y < frame.get_height()):
        raise AssertionError(f"probe pixel {pos} is outside the "
                             f"{frame.get_size()} frame")
    r, g, b, _a = frame.get_at(pos)
    return r, g, b


def expect_pixel(frame, pos, color: Color, what: str) -> None:
    actual = pixel(frame, pos)
    assert actual == color, (f"{what}: pixel {pos} is {actual}, "
                             f"expected {color}")


def expect_not_pixel(frame, pos, color: Color, what: str) -> None:
    actual = pixel(frame, pos)
    assert actual != color, f"{what}: pixel {pos} is {actual}, which it must not be"


def tile_samples(origin, tiles: Iterable[Tuple[int, int]],
                 ids: Callable[[int, int], int]):
    """(what, pixel, colour) for the centre of each (tx, ty) tile."""
    for tx, ty in tiles:
        sx, sy = to_screen(origin, tx + 0.5, ty + 0.5)
        yield f"tile ({tx},{ty}) id {ids(tx, ty)}", (sx, sy), tile_color(ids(tx, ty))


# -- characters (player gani: shadow, body, head, shield, sword) -------------

def character_samples(top_left: Tuple[int, int], body: str, head: str,
                      direction: int, frame: int = 0, sword: bool = False,
                      shield: str = "shield1.png", sword_sheet: str = "sword1.png"
                      ) -> List[Tuple[str, Tuple[int, int], Color]]:
    """(what, pixel, colour) points of a character drawn with the synthetic
    player gani, ``top_left`` being the entity's screen position. Every point
    is one that no later layer covers.

    Layout, from offline_game.BODY_AT / HEAD_AT / SHIELD_AT / SWORD_AT: the
    gani draws a body sprite (direction d = body sheet cell block d), a head
    (head sheet rows of direction d), then the shield, then the sword."""
    x, y = top_left
    d = direction
    out = [
        # head, clear of the shield and sword
        ("head", (x + HEAD_AT[0] + 4, y + HEAD_AT[1] + 4),
         sheet_color_at(head, 4, d * CELL_PX + 4)),
        # the lower body, below the head (head ends 34 px down)
        ("body", (x + BODY_AT[0] + 24, y + BODY_AT[1] + 24),
         sheet_color_at(body, d * CELL_PX + 24, 24)),
        # the head covers the body where they overlap: the later layer wins.
        # (x + 12, y + 20) is body-local (4, 4) and head-local (4, 18).
        ("head over body", (x + BODY_AT[0] + 4, y + BODY_AT[1] + 4),
         sheet_color_at(head, 4, d * CELL_PX + (BODY_AT[1] + 4 - HEAD_AT[1]))),
    ]
    if not sword:
        # (the sword is drawn after the shield and covers its middle)
        sx = x + SHIELD_AT[0] + SHIELD_FRAME_STEP * frame
        out.append(("shield", (sx + 4, y + SHIELD_AT[1] + 4),
                    sheet_color_at(shield, 4, 4)))
    if sword:
        out.append(("sword", (x + SWORD_AT[0] + 2, y + SWORD_AT[1] + 4),
                    sheet_color_at(sword_sheet, 2, 4)))
    return out


def check_character(frame, top_left, body, head, direction, frame_index=0,
                    sword=False, who="character") -> None:
    for what, pos, color in character_samples(top_left, body, head, direction,
                                              frame_index, sword):
        expect_pixel(frame, pos, color, f"{who} {what} (dir {direction}, "
                                        f"frame {frame_index})")
    # The shield's x offset moves with the gani frame: a point inside the
    # shield on one frame is outside it on the other.
    x, y = top_left
    row1 = SHIELD_AT[1] + 9           # shield-local y 9: row 1 of its cells
    left = (x + SHIELD_AT[0] + 1, y + row1)
    right = (x + SHIELD_AT[0] + 14 + SHIELD_FRAME_STEP, y + row1)
    on_left, on_right = ((expect_pixel, expect_not_pixel) if frame_index == 0
                         else (expect_not_pixel, expect_pixel))
    on_left(frame, left, cell_color("shield1.png", 0, 1),
            f"{who} shield left edge, frame {frame_index}")
    on_right(frame, right, cell_color("shield1.png", 1, 1),
             f"{who} shield right edge, frame {frame_index}")


def image_samples(top_left, sheet: str, part: Tuple[int, int, int, int]):
    """Cell-centre points of an image NPC drawn from ``part`` (x, y, w, h) of
    ``sheet`` at ``top_left``. Both the first and the last cell are used."""
    x, y = top_left
    px, py, w, h = part
    cell = og.SHEETS[sheet][1]
    out = []
    for cx, cy in ((cell // 2, cell // 2), (w - cell // 2, h - cell // 2)):
        out.append((f"{sheet} cell at part offset ({cx},{cy})",
                    (x + cx, y + cy), sheet_color_at(sheet, px + cx, py + cy)))
    return out


def check_image(frame, top_left, sheet, part, who) -> None:
    """Both sampled cells show their own colour. A sprite blitted 16 px off
    leaves the first sample on the background, so the position is pinned."""
    for what, pos, color in image_samples(top_left, sheet, part):
        expect_pixel(frame, pos, color, f"{who}: {what}")


# -- text -------------------------------------------------------------------

def opaque_matches(frame: "pygame.Surface", text: "pygame.Surface",
                   pos: Tuple[int, int]) -> Tuple[int, int]:
    """(matching, total) over the fully opaque pixels of ``text`` blitted at
    ``pos``: how many of them have exactly that colour in ``frame``."""
    mask = pygame.mask.from_surface(text, threshold=254)
    total = matching = 0
    width, height = text.get_size()
    for x in range(width):
        for y in range(height):
            if not mask.get_at((x, y)):
                continue
            total += 1
            fx, fy = pos[0] + x, pos[1] + y
            if not (0 <= fx < frame.get_width() and 0 <= fy < frame.get_height()):
                continue
            if frame.get_at((fx, fy))[:3] == text.get_at((x, y))[:3]:
                matching += 1
    return matching, total


def expect_text_at(frame, text, pos, what: str) -> None:
    """``text`` (rendered with the game's own font) is on ``frame`` at
    ``pos``, pixel for pixel, and is not there one pixel or 16 px away."""
    matching, total = opaque_matches(frame, text, pos)
    assert total and matching == total, (
        f"{what}: only {matching}/{total} text pixels match at {pos}")
    for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (16, 0), (0, 16)):
        near, _ = opaque_matches(frame, text, (pos[0] + dx, pos[1] + dy))
        assert near < total, (f"{what}: the text also matches {dx, dy} px "
                              f"away, so its position is not pinned")
