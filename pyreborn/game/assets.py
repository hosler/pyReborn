"""FontManager — keyed, cached font lookup.

Before this, the client scattered `pygame.font.Font(None, 24)` and
`pygame.font.Font(None, 18)` calls across render.py, pygame_screens.py and the
HUD. Each `Font(...)` allocation is non-trivial, sizes were magic numbers, and
there was no single place to swap in a bundled TTF.

Borrowed from Preagonal's FontSystem (FontSystem.cs): fonts are cached by a key
built from (name, size, style) so identical requests share one object, and a
named role can map to a concrete size/style in one place.

Usage:
    fonts = FontManager()
    fonts.get("hud").render("Hearts", ...)        # role lookup
    fonts.at(28, bold=True).render("Title", ...)   # explicit size
"""

from typing import Dict, Optional, Tuple

import pygame


class FontManager:
    """Caches pygame Font objects keyed by (path, size, bold, italic).

    Named *roles* (hud, small, title, chat, ...) decouple call sites from
    concrete point sizes, so restyling the UI is a one-line change here instead
    of a hunt through every render method.
    """

    # role -> (size, bold, italic). Tweak the look of the whole client here.
    ROLES: Dict[str, Tuple[int, bool, bool]] = {
        "title":   (42, True, False),
        "heading": (28, True, False),
        "hud":     (24, False, False),
        "chat":    (20, False, False),
        "small":   (18, False, False),
        "tiny":    (14, False, False),
    }

    def __init__(self, font_path: Optional[str] = None):
        # None => pygame's built-in default font. A bundled .ttf can be wired in
        # here later without touching any call site.
        self.font_path = font_path
        self._cache: Dict[Tuple[Optional[str], int, bool, bool], pygame.font.Font] = {}

    def at(self, size: int, bold: bool = False, italic: bool = False,
           path: Optional[str] = None) -> pygame.font.Font:
        """Return a cached Font of an explicit size/style."""
        key = (path or self.font_path, size, bold, italic)
        font = self._cache.get(key)
        if font is None:
            font = pygame.font.Font(key[0], size)
            font.set_bold(bold)
            font.set_italic(italic)
            self._cache[key] = font
        return font

    def get(self, role: str) -> pygame.font.Font:
        """Return the Font for a named UI role (see ROLES)."""
        size, bold, italic = self.ROLES.get(role, self.ROLES["hud"])
        return self.at(size, bold, italic)

    def render(self, role_or_size, text: str, color, *, bold: bool = False,
               antialias: bool = True) -> pygame.Surface:
        """Convenience: render `text` with a role name or explicit size."""
        font = self.get(role_or_size) if isinstance(role_or_size, str) \
            else self.at(role_or_size, bold)
        return font.render(text, antialias, color)
