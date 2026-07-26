from __future__ import annotations

from typing import List, Optional

import pygame
from .profiles import GuiProfile, _color  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Tuple  # noqa: F401  - kept: original import block (star-import consumers rely on it)



# =============================================================================
# Skin art (Torque bitmap arrays)
#
# A profile's `bitmap` field names a skin sheet (guiblue_window_noback.png,
# guiblue_button.png, ...) divided into cells by separator lines in the
# sheet's top-left pixel color (verified against the C# client's
# TBitmapArrayHolder + the live art served by loginserver.graal.in).
# Layouts, from the shipped guiblue_* sheets:
#   * button/tab sheets: each visual STATE is a 3-row group of 3 cells
#     (corners + stretchable edges/center -- a 9-patch);
#     button states in order: normal, hilight, pressed, inactive.
#   * textedit: one 9-patch (3 rows x 3 cells).
#   * window sheet (64px wide): title-bar buttons (4 rows), active +
#     inactive title bar [left corner, right corner, middle], frame strip
#     row -- drawn with the exact source rects the C# client's
#     GuiWindowCtrl.DrawStyle uses.
#   * scroll sheet: row0 = up/down arrows x3 states, rows1-4 = vertical
#     thumb top/mid/bottom + track (x3 states), row5+ = horizontal pieces.
# =============================================================================

def _split_bitmap_array(sheet: pygame.Surface) -> List[List[pygame.Rect]]:
    """Torque bitmap-array split: separator color = pixel(0,0); rows are
    runs of non-separator pixels down column 0, cells are runs of
    non-separator pixels across each row's top line."""
    w, h = sheet.get_size()
    if w <= 0 or h <= 0:
        return []
    sep = sheet.get_at((0, 0))[:3]
    rows: List[List[pygame.Rect]] = []
    y = 0
    while y < h:
        if sheet.get_at((0, y))[:3] == sep:
            y += 1
            continue
        rh = 0
        while y + rh < h and sheet.get_at((0, y + rh))[:3] != sep:
            rh += 1
        cells: List[pygame.Rect] = []
        x = 0
        while x < w:
            if sheet.get_at((x, y))[:3] == sep:
                x += 1
                continue
            cw = 0
            while x + cw < w and sheet.get_at((x + cw, y))[:3] != sep:
                cw += 1
            cells.append(pygame.Rect(x, y, cw, rh))
            x += cw
        rows.append(cells)
        y += rh
    return rows


class _Skin:
    """One sliced skin sheet + scratch helpers. Never cache by bare id():
    the entry pins the source surface and the manager identity-checks it on
    every hit (sprite downloads replace surfaces in place)."""

    def __init__(self, name: str, sheet: pygame.Surface):
        self.name = name
        try:
            self.sheet = sheet.convert_alpha()
        except pygame.error:            # no display surface (headless tests)
            self.sheet = sheet
        self.source = sheet             # identity guard for cache validity
        self.rows = _split_bitmap_array(sheet)

    def cell(self, row: int, col: int) -> Optional[pygame.Rect]:
        if 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            return self.rows[row][col]
        return None

    def blit_scaled(self, surf, src: pygame.Rect, dest: pygame.Rect,
                    alpha: int = 255) -> None:
        if src is None or dest.width <= 0 or dest.height <= 0:
            return
        piece = self.sheet.subsurface(src)
        if piece.get_size() != dest.size:
            piece = pygame.transform.smoothscale(piece, dest.size)
        if alpha < 255:
            piece = piece.copy()
            piece.set_alpha(alpha)
        surf.blit(piece, dest.topleft)

    def draw_nine(self, surf, dest: pygame.Rect, row0: int,
                  alpha: int = 255) -> bool:
        """Draw the 3-row 9-patch group starting at `rows[row0]` stretched
        over dest (corner cells fixed, edges/center stretched)."""
        if row0 + 2 >= len(self.rows):
            return False
        top, mid, bot = self.rows[row0], self.rows[row0 + 1], self.rows[row0 + 2]
        if len(top) < 3 or len(mid) < 3 or len(bot) < 3:
            return False
        lw = min(top[0].width, max(1, dest.width // 3))
        rw = min(top[2].width, max(1, dest.width // 3))
        th = min(top[0].height, max(1, dest.height // 3))
        bh = min(bot[0].height, max(1, dest.height // 3))
        cw = max(0, dest.width - lw - rw)
        ch = max(0, dest.height - th - bh)
        x0, y0 = dest.x, dest.y
        grid = [
            (top[0], pygame.Rect(x0, y0, lw, th)),
            (top[1], pygame.Rect(x0 + lw, y0, cw, th)),
            (top[2], pygame.Rect(x0 + lw + cw, y0, rw, th)),
            (mid[0], pygame.Rect(x0, y0 + th, lw, ch)),
            (mid[1], pygame.Rect(x0 + lw, y0 + th, cw, ch)),
            (mid[2], pygame.Rect(x0 + lw + cw, y0 + th, rw, ch)),
            (bot[0], pygame.Rect(x0, y0 + th + ch, lw, bh)),
            (bot[1], pygame.Rect(x0 + lw, y0 + th + ch, cw, bh)),
            (bot[2], pygame.Rect(x0 + lw + cw, y0 + th + ch, rw, bh)),
        ]
        for src, dst in grid:
            self.blit_scaled(surf, src, dst, alpha)
        return True

    # -- window sheet (rects verified against the C# client's DrawStyle) --

    WINDOW_TITLE_H = 24

    def looks_like_window_sheet(self) -> bool:
        return (self.sheet.get_width() >= 64
                and self.sheet.get_height() >= 118)

    def has_window_background(self) -> bool:
        """guiblue_window.png carries a 16x16 background cell at (0,136);
        the *_noback variant (135px tall) ends right before it -- that is
        the whole difference between the opaque and translucent windows."""
        return (self.looks_like_window_sheet()
                and self.sheet.get_height() >= 152)

    def draw_window_background(self, surf, dest: pygame.Rect,
                               alpha: int = 255) -> bool:
        if not self.has_window_background():
            return False
        tile = self.sheet.subsurface(pygame.Rect(0, 136, 16, 16))
        if alpha < 255:
            tile = tile.copy()
            tile.set_alpha(alpha)
        prev = surf.get_clip()
        surf.set_clip(dest if prev is None else dest.clip(prev))
        for ty in range(dest.y, dest.bottom, 16):
            for tx in range(dest.x, dest.right, 16):
                surf.blit(tile, (tx, ty))
        surf.set_clip(prev)
        return True

    def draw_window_frame(self, surf, dest: pygame.Rect,
                          alpha: int = 255) -> bool:
        """Title bar + side/bottom frame (no background -- the caller fills
        the client area with the profile's fillcolor, which is exactly what
        the *_noback sheets are for)."""
        if not self.looks_like_window_sheet():
            return False
        R = pygame.Rect
        w, h = dest.width, dest.height
        x0, y0 = dest.x, dest.y
        cw = min(23, max(1, w // 2))
        # title bar: left corner, stretched middle, right corner
        self.blit_scaled(surf, R(0, 61, 23, 24), R(x0, y0, cw, 24), alpha)
        self.blit_scaled(surf, R(48, 61, 16, 24),
                         R(x0 + cw, y0, max(0, w - 2 * cw), 24), alpha)
        self.blit_scaled(surf, R(24, 61, 23, 24),
                         R(x0 + w - cw, y0, cw, 24), alpha)
        if h <= 24:
            return True
        eh = max(0, h - 24 - 6)
        # left/right edges + bottom strip + bottom corners
        self.blit_scaled(surf, R(0, 111, 6, 24), R(x0, y0 + 24, 6, eh), alpha)
        self.blit_scaled(surf, R(7, 111, 6, 24),
                         R(x0 + w - 6, y0 + 24, 6, eh), alpha)
        self.blit_scaled(surf, R(27, 111, 6, 6),
                         R(x0 + 6, y0 + h - 6, max(0, w - 12), 6), alpha)
        self.blit_scaled(surf, R(20, 111, 6, 6), R(x0, y0 + h - 6, 6, 6), alpha)
        self.blit_scaled(surf, R(52, 111, 6, 6),
                         R(x0 + w - 6, y0 + h - 6, 6, 6), alpha)
        return True
