"""FontManager — keyed, cached font lookup.

Before this, the client scattered `pygame.font.Font(None, 24)` and
`pygame.font.Font(None, 18)` calls across render.py, pygame_screens.py and the
HUD. Each `Font(...)` allocation is non-trivial, sizes were magic numbers, and
there was no single place to swap in a bundled TTF.

Borrowed from the C# client's FontSystem (FontSystem.cs): fonts are cached by a key
built from (name, size, style) so identical requests share one object, and a
named role can map to a concrete size/style in one place.

Usage:
    fonts = FontManager()
    fonts.get("hud").render("Hearts", ...)        # role lookup
    fonts.at(28, bold=True).render("Title", ...)   # explicit size
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame

CLASSIC_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "rebornfont.ttf"
CLASSIC_FONT_SIZE = 18


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
        self._classic_cache: Dict[int, pygame.font.Font] = {}

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

    def classic(self, size: int = CLASSIC_FONT_SIZE) -> pygame.font.Font:
        """Return the bundled sign face, falling back to pygame's default.

        The result (including the fallback) is cached by :meth:`at`, so a bad
        or stripped asset install is only probed once per manager and size.
        """
        cached = self._classic_cache.get(size)
        if cached is not None:
            return cached
        path = str(CLASSIC_FONT_PATH)
        try:
            font = self.at(size, path=path)
        except (OSError, pygame.error):
            font = self.at(size)
        self._classic_cache[size] = font
        return font

    def render(self, role_or_size, text: str, color, *, bold: bool = False,
               antialias: bool = True) -> pygame.Surface:
        """Convenience: render `text` with a role name or explicit size."""
        font = self.get(role_or_size) if isinstance(role_or_size, str) \
            else self.at(role_or_size, bold)
        return font.render(text, antialias, color)

def render_outlined_text(font: pygame.font.Font, text: str, color,
                          outline_color: Tuple[int, int, int] = (0, 0, 0),
                          outline_width: int = 1) -> pygame.Surface:
    """Render `text` with a full outline baked into one surface.

    A single southeast drop-shadow (the client's old approach for nameplates)
    all but disappears over busy or dark level art. Stamping the glyphs in the
    outline colour at every offset around the fill -- what the C# client does
    for nicknames/signs -- reads reliably over any background instead. The
    returned surface is padded by `outline_width` on every side versus a plain
    `font.render()`, so callers centring on `get_size()` still land correctly.
    """
    fill = font.render(text, True, color)
    w, h = fill.get_size()
    pad = outline_width
    surf = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
    stroke = font.render(text, True, outline_color)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx or dy:
                surf.blit(stroke, (pad + dx, pad + dy))
    surf.blit(fill, (pad, pad))
    return surf
