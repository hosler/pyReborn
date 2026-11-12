"""Entity text rendering mixin."""

from __future__ import annotations

from typing import List, Optional, Tuple

import pygame

from .assets import render_outlined_text
from .frame_context import FrameContext


#: Side of a grid cell, in screen pixels. A plate is roughly 60x14, so a
#: plate touches a handful of cells and a cell holds a handful of plates.
_CELL = 64
#: A rect covering more cells than this is kept in a flat list instead.
_MAX_CELLS = 64


class _NameplateGrid:
    """Coarse bucket grid over the plates placed so far this frame.

    `first_collision` finds a placed rect that `rect.colliderect` accepts, and
    None exactly when `any(rect.colliderect(r) for r in rects)` was False: the grid only narrows which placed rects are tested, always to a
    superset of those that can collide (it buckets by each rect's normalised
    bounds), and `colliderect` still decides every candidate."""

    __slots__ = ('rects', 'count', 'cells', 'wide')

    def __init__(self, rects: list):
        self.rects = rects
        self.count = 0
        self.cells: dict = {}
        self.wide: list = []
        for r in rects:
            self.add(r)
        self.count = len(rects)

    @staticmethod
    def _span(rect):
        x0, x1 = rect.x, rect.x + rect.w
        y0, y1 = rect.y, rect.y + rect.h
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0
        return x0 // _CELL, x1 // _CELL, y0 // _CELL, y1 // _CELL

    def add(self, rect) -> None:
        cx0, cx1, cy0, cy1 = self._span(rect)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > _MAX_CELLS:
            self.wide.append(rect)
        else:
            cells = self.cells
            for cy in range(cy0, cy1 + 1):
                for cx in range(cx0, cx1 + 1):
                    bucket = cells.get((cx, cy))
                    if bucket is None:
                        cells[(cx, cy)] = [rect]
                    else:
                        bucket.append(rect)
        self.count += 1

    def first_collision(self, rect):
        for r in self.wide:
            if rect.colliderect(r):
                return r
        cx0, cx1, cy0, cy1 = self._span(rect)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > _MAX_CELLS:
            # a very large probe: test every placed rect, as the flat scan did
            return next((r for r in self.rects if rect.colliderect(r)), None)
        cells = self.cells
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                bucket = cells.get((cx, cy))
                if bucket:
                    for r in bucket:
                        if rect.colliderect(r):
                            return r
        return None


class RenderTextMixin:
    def _place_nameplate(self, name_x: float, name_y: float,
                          size: Tuple[int, int],
                          frame: Optional[FrameContext] = None
                          ) -> Tuple[float, float]:
        """Stagger a nameplate vertically if it would overlap one already
        placed this frame. Two players (or an NPC and a player) standing on
        or near the same tile otherwise draw their nickname at the same
        y-offset, producing garbled overlapping text; nudge each subsequent
        overlapper straight down by one box-height until it clears. The
        already-placed rects live on the frame, so they reset with it."""
        rects = (self._frame_context() if frame is None else frame).nameplate_rects
        w, h = size
        rect = pygame.Rect(int(name_x), int(name_y), int(w), int(h))
        index = self._nameplate_index(rects)
        step = h + 2
        solid = w > 0 and h > 0
        while True:
            hit = index.first_collision(rect)
            if hit is None:
                break
            if solid and hit.w > 0 and hit.h > 0 and rect.y < hit.bottom:
                # Every nudge that still overlaps `hit` would collide and be
                # nudged again, so go straight to the first one that clears it.
                rect.y += max(1, -(-(hit.bottom - rect.y) // step)) * step
            else:
                rect.y += step
        index.add(rect)
        rects.append(rect)
        return rect.x, rect.y

    def _nameplate_index(self, rects: list) -> "_NameplateGrid":
        """The spatial index over this frame's placed plates. It is tied to
        the frame's own `nameplate_rects` list (identity and length), so a new
        frame, or a plate appended behind its back, rebuilds it."""
        held = getattr(self, '_nameplate_grid', None)
        if held is None or held.rects is not rects or held.count != len(rects):
            held = self._nameplate_grid = _NameplateGrid(rects)
        return held

    def _render_text_cached(self, font: pygame.font.Font, text: str,
                             color: Tuple[int, int, int]) -> pygame.Surface:
        """Render (and cache) a plain (unoutlined) text surface. Speech
        bubbles re-render the same handful of strings every frame otherwise;
        keying on (font identity, text, color) lets every caller share one
        cache. Cleared wholesale once it grows large so a chat-heavy session
        doesn't leak memory. Fine as-is for bubble text, which already sits on
        a solid white plate -- text drawn straight over the level (nameplates,
        showtext) wants `_render_text_outlined_cached` instead, below."""
        cache = getattr(self, '_text_surf_cache', None)
        if cache is None:
            cache = self._text_surf_cache = {}
        key = (id(font), text, color)
        surf = cache.get(key)
        if surf is None:
            if len(cache) > 500:
                cache.clear()
            surf = cache[key] = font.render(text, True, color)
        return surf

    def _render_text_outlined_cached(self, font: pygame.font.Font, text: str,
                                      color: Tuple[int, int, int],
                                      outline_color: Tuple[int, int, int] = (0, 0, 0)
                                      ) -> pygame.Surface:
        """Outlined sibling of `_render_text_cached`, for text drawn straight
        over the level (nameplates, NPC showtext) rather than inside a
        solid-colour bubble/box -- a flat fill (even with a 1px drop shadow)
        all but vanishes against busy/dark level art. See
        assets.render_outlined_text for the actual stamping."""
        cache = getattr(self, '_text_outline_cache', None)
        if cache is None:
            cache = self._text_outline_cache = {}
        key = (id(font), text, color, outline_color)
        surf = cache.get(key)
        if surf is None:
            if len(cache) > 500:
                cache.clear()
            surf = cache[key] = render_outlined_text(font, text, color, outline_color)
        return surf

    def _wrapped_lines(self, text: str) -> List[str]:
        """Word-wrap speech-bubble text into up to 3 lines under ~120px.
        Recomputing this (with a font.render() per word) every frame for the
        same message is wasteful, so cache the wrap result keyed by the full
        text - messages are static once received."""
        cache = getattr(self, '_wrap_cache', None)
        if cache is None:
            cache = self._wrap_cache = {}
        lines = cache.get(text)
        if lines is not None:
            return lines

        max_width = 120
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_surf = self._render_text_cached(self.font_small, test_line, (0, 0, 0))
            if test_surf.get_width() > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)
        lines = lines[:3]  # Limit to 3 lines max

        if len(cache) > 300:
            cache.clear()
        cache[text] = lines
        return lines

    def _render_speech_bubble(self, x: float, y: float, text: str):
        """Render a speech bubble above an entity."""
        if not text:
            return

        lines = self._wrapped_lines(text)
        if not lines:
            # Whitespace-only text wraps to no words; nothing to show. Without
            # this guard the max() below crashes the whole render loop, which a
            # remote player sending an all-space chat could trigger for everyone.
            return

        # Calculate bubble dimensions
        line_height = 14
        padding = 4
        bubble_height = len(lines) * line_height + padding * 2
        bubble_width = max(self._render_text_cached(self.font_small, line, (0, 0, 0)).get_width()
                           for line in lines) + padding * 2

        # Position bubble above entity (centered, above head)
        bubble_x = x + 16 - bubble_width // 2
        bubble_y = y - bubble_height - 8

        # Draw bubble background (white with black border)
        pygame.draw.rect(self.screen, (255, 255, 255),
                        (bubble_x, bubble_y, bubble_width, bubble_height))
        pygame.draw.rect(self.screen, (0, 0, 0),
                        (bubble_x, bubble_y, bubble_width, bubble_height), 1)

        # Draw small triangle pointer
        pointer_x = x + 16
        pygame.draw.polygon(self.screen, (255, 255, 255), [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x + 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6)
        ])
        pygame.draw.lines(self.screen, (0, 0, 0), False, [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6),
            (pointer_x + 4, bubble_y + bubble_height)
        ], 1)

        # Draw text lines
        for i, line in enumerate(lines):
            text_surf = self._render_text_cached(self.font_small, line, (0, 0, 0))
            text_x = bubble_x + padding
            text_y = bubble_y + padding + i * line_height
            self.screen.blit(text_surf, (text_x, text_y))
