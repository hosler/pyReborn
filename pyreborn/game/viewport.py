"""Viewport — resolution-independent rendering with a resizable window.

The client used to call `pygame.display.set_mode((640, 480))` and draw directly
to that fixed surface, so the window couldn't be resized and every layout number
assumed exactly 640x480.

Borrowed from Preagonal's ResolutionIndependentRenderer
(ResolutionIndependentRenderer.cs): keep a fixed **virtual** canvas (all game and
HUD layout math stays in virtual pixels), then scale that canvas to whatever size
the window currently is, preserving aspect ratio with letterbox/pillarbox bars.
Mouse coordinates are scaled back into virtual space so hit-testing still works.

All game code draws to `viewport.canvas`. Once per frame `viewport.present()`
scales the canvas onto the real window.
"""

from typing import Tuple

import pygame


class Viewport:
    def __init__(self, virtual_w: int, virtual_h: int,
                 window_w: int = 0, window_h: int = 0,
                 caption: str = "", bg=(0, 0, 0)):
        self.virtual_w = virtual_w
        self.virtual_h = virtual_h
        self.bg = bg

        window_w = window_w or virtual_w
        window_h = window_h or virtual_h
        self.window = pygame.display.set_mode((window_w, window_h),
                                              pygame.RESIZABLE)
        if caption:
            pygame.display.set_caption(caption)

        # Everything is drawn here, then scaled onto the window.
        self.canvas = pygame.Surface((virtual_w, virtual_h)).convert()

        self._dest_rect = pygame.Rect(0, 0, window_w, window_h)
        self._scale = 1.0
        self._recompute_layout(window_w, window_h)

    # -- window events ----------------------------------------------------

    def handle_resize(self, w: int, h: int):
        """Call on pygame.VIDEORESIZE.

        Calling set_mode() itself emits a fresh VIDEORESIZE under SDL2, so
        re-creating the window unconditionally here spawns a new window every
        frame. Only re-create when the size actually changed to break that loop.
        """
        if self.window.get_size() == (w, h):
            return
        self.window = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self._recompute_layout(w, h)

    def _recompute_layout(self, w: int, h: int):
        # Largest integer-friendly scale that fits both axes (aspect preserved).
        self._scale = min(w / self.virtual_w, h / self.virtual_h)
        dest_w = int(self.virtual_w * self._scale)
        dest_h = int(self.virtual_h * self._scale)
        self._dest_rect = pygame.Rect((w - dest_w) // 2, (h - dest_h) // 2,
                                      dest_w, dest_h)

    # -- coordinate mapping ----------------------------------------------

    def window_to_virtual(self, wx: float, wy: float) -> Tuple[float, float]:
        """Map a window/mouse pixel to virtual-canvas coordinates."""
        if self._scale == 0:
            return (0.0, 0.0)
        vx = (wx - self._dest_rect.x) / self._scale
        vy = (wy - self._dest_rect.y) / self._scale
        return (vx, vy)

    def mouse_pos(self) -> Tuple[int, int]:
        """Current mouse position in virtual-canvas coordinates."""
        mx, my = pygame.mouse.get_pos()
        vx, vy = self.window_to_virtual(mx, my)
        return (int(vx), int(vy))

    # -- present ----------------------------------------------------------

    def present(self):
        """Scale the canvas onto the window and flip."""
        self.window.fill(self.bg)
        if self._dest_rect.size == (self.virtual_w, self.virtual_h):
            self.window.blit(self.canvas, self._dest_rect)        # 1:1, no scale
        else:
            pygame.transform.scale(self.canvas, self._dest_rect.size,
                                   self.window.subsurface(self._dest_rect))
        pygame.display.flip()
