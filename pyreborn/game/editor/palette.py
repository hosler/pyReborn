"""game/editor/palette.py — the tileset palette.

Draws the tileset the way the sheet is actually laid out, so a builder who
knows the tileset recognises it: a tile id maps to sheet coordinates as
`tx = (id // 512) * 16 + id % 16`, `ty = (id // 16) % 32` (the same formula
sprites.py's TilesetManager.get_tile uses). That makes the full sheet 128
tiles wide and 32 tall, and picking is that formula inverted.

The palette pulls each tile through `get_tile_or_color`, so a client with no
tileset downloaded still shows the placeholder colours and stays usable
instead of rendering an empty box.
"""

from __future__ import annotations

from typing import Optional, Tuple

import pygame

from .. import theme

TILE = 16                 # source tile size, in pixels
SHEET_COLS = 128          # 8 blocks of 16 columns
SHEET_ROWS = 32
MAX_TILE_ID = SHEET_COLS * SHEET_ROWS - 1     # 4095

PAD = 8
FOOTER_H = 20


def tile_id_at(col: int, row: int) -> int:
    """Sheet column/row -> tile id (the inverse of the layout formula)."""
    block, in_block_col = divmod(col, 16)
    return block * 512 + row * 16 + in_block_col


class TilePalette:
    """A scrollable, zoomable tile picker over the whole tileset."""

    def __init__(self, game):
        self.game = game
        self.scroll_x = 0
        self.scroll_y = 0
        self.zoom = 2                     # integer, so tiles stay crisp
        self._rect = pygame.Rect(0, 0, 0, 0)

    # -- geometry ---------------------------------------------------------

    def rect(self) -> pygame.Rect:
        """The palette panel, pinned to the bottom of the window."""
        g = self.game
        w = min(g.screen_w - 20, SHEET_COLS * TILE * self.zoom + PAD * 2)
        h = min(max(120, g.screen_h // 3), SHEET_ROWS * TILE * self.zoom
                + PAD * 2 + FOOTER_H)
        self._rect = pygame.Rect((g.screen_w - w) // 2, g.screen_h - h - 10, w, h)
        return self._rect

    def _grid_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x + PAD, r.y + PAD,
                           r.w - PAD * 2, r.h - PAD * 2 - FOOTER_H)

    @property
    def step(self) -> int:
        return TILE * self.zoom

    def zoom_by(self, delta: int) -> None:
        self.zoom = max(1, min(4, self.zoom + delta))

    def scroll_by(self, dx: int, dy: int) -> None:
        grid = self._grid_rect()
        max_x = max(0, SHEET_COLS * self.step - grid.w)
        max_y = max(0, SHEET_ROWS * self.step - grid.h)
        self.scroll_x = max(0, min(max_x, self.scroll_x + dx))
        self.scroll_y = max(0, min(max_y, self.scroll_y + dy))

    # -- picking ----------------------------------------------------------

    def tile_at_pos(self, pos: Tuple[int, int]) -> Optional[int]:
        """The tile id under a virtual-canvas point, or None if outside."""
        grid = self._grid_rect()
        if not grid.collidepoint(pos):
            return None
        col = (pos[0] - grid.x + self.scroll_x) // self.step
        row = (pos[1] - grid.y + self.scroll_y) // self.step
        if not (0 <= col < SHEET_COLS and 0 <= row < SHEET_ROWS):
            return None
        return tile_id_at(int(col), int(row))

    # -- drawing ----------------------------------------------------------

    def draw(self, surf, selected: int) -> None:
        g = self.game
        panel = self.rect()
        theme.draw_panel(surf, panel)
        grid = self._grid_rect()

        tiles = g.tileset_mgr
        step = self.step
        first_col = self.scroll_x // step
        first_row = self.scroll_y // step
        cols = grid.w // step + 2
        rows = grid.h // step + 2

        clip = surf.get_clip()
        surf.set_clip(grid)
        for row in range(first_row, min(SHEET_ROWS, first_row + rows)):
            for col in range(first_col, min(SHEET_COLS, first_col + cols)):
                tile_id = tile_id_at(col, row)
                x = grid.x + col * step - self.scroll_x
                y = grid.y + row * step - self.scroll_y
                image = tiles.get_tile_or_color(tile_id)
                if image is not None:
                    if step != TILE:
                        image = pygame.transform.scale(image, (step, step))
                    surf.blit(image, (x, y))
                if tile_id == selected:
                    pygame.draw.rect(surf, theme.MINT,
                                     pygame.Rect(x, y, step, step), width=2)
        surf.set_clip(clip)

        label = (f"tile {selected}  ·  wheel scroll · shift+wheel across · "
                 f"+/- zoom · click to pick · P closes")
        surf.blit(g.font_small.render(label, True, theme.TEXT_DIM),
                  (panel.x + PAD, panel.bottom - PAD - FOOTER_H + 4))
