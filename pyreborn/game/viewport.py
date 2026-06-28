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
                 caption: str = "", bg=(0, 0, 0),
                 native: bool = False, on_resize=None):
        self.virtual_w = virtual_w
        self.virtual_h = virtual_h
        self.bg = bg
        # native=True: draw straight to the window at its real resolution (the
        # game uses this so it fills the whole window, with the world centred by
        # the camera). native=False: keep a fixed virtual canvas and letterbox-
        # scale it (the login/server-select screens use this).
        self.native = native
        self.on_resize = on_resize

        window_w = window_w or virtual_w
        window_h = window_h or virtual_h
        self.window = pygame.display.set_mode((window_w, window_h),
                                              pygame.RESIZABLE)
        if caption:
            pygame.display.set_caption(caption)

        if native:
            # Draw straight to the window surface; no scaling.
            self.canvas = self.window
        else:
            # Everything is drawn here, then scaled onto the window.
            self.canvas = pygame.Surface((virtual_w, virtual_h)).convert()

        self._dest_rect = pygame.Rect(0, 0, window_w, window_h)
        self._scale_x = 1.0
        self._scale_y = 1.0
        if not native:
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
        if self.native:
            # Canvas IS the window; hand the new size to the game so it can
            # resize the camera/HUD to match.
            self.canvas = self.window
            if self.on_resize:
                self.on_resize(w, h)
        else:
            self._recompute_layout(w, h)

    def _recompute_layout(self, w: int, h: int):
        # Largest scale that fits both axes (aspect preserved → letterbox).
        scale = min(w / self.virtual_w, h / self.virtual_h)
        self._scale_x = self._scale_y = scale
        dest_w = int(self.virtual_w * scale)
        dest_h = int(self.virtual_h * scale)
        self._dest_rect = pygame.Rect((w - dest_w) // 2, (h - dest_h) // 2,
                                      dest_w, dest_h)

    # -- coordinate mapping ----------------------------------------------

    def window_to_virtual(self, wx: float, wy: float) -> Tuple[float, float]:
        """Map a window/mouse pixel to virtual-canvas coordinates."""
        if self.native:
            return (float(wx), float(wy))   # canvas == window, 1:1
        if self._scale_x == 0 or self._scale_y == 0:
            return (0.0, 0.0)
        vx = (wx - self._dest_rect.x) / self._scale_x
        vy = (wy - self._dest_rect.y) / self._scale_y
        return (vx, vy)

    def mouse_pos(self) -> Tuple[int, int]:
        """Current mouse position in virtual-canvas coordinates."""
        mx, my = pygame.mouse.get_pos()
        vx, vy = self.window_to_virtual(mx, my)
        return (int(vx), int(vy))

    # -- present ----------------------------------------------------------

    def present(self):
        """Show the frame. Native draws straight to the window; scaled mode
        letterbox-scales the virtual canvas onto it."""
        if self.native:
            pygame.display.flip()
            return
        self.window.fill(self.bg)
        if self._dest_rect.size == (self.virtual_w, self.virtual_h):
            self.window.blit(self.canvas, self._dest_rect)        # 1:1, no scale
        else:
            pygame.transform.scale(self.canvas, self._dest_rect.size,
                                   self.window.subsurface(self._dest_rect))
        pygame.display.flip()
