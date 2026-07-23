"""game/theme.py — the client's single source of visual truth.

The palette is sampled from the bundled leaf-mandala emblem
(``assets/emblem.png``): layered greens — deep forest through emerald up to a
mint highlight — sitting on a very dark navy field. Every UI file (login and
server-select screens, the widget toolkit, the HUD, the inventory overlay, the
level-loading card) pulls named colors and the shared panel/glow helpers from
here instead of scattering hex literals, so a future reskin is a one-file edit.

Rules of thumb for picking a name:
    * Backgrounds / chrome surfaces  -> the navy family (NIGHT*, SURFACE*).
    * Accents, focus, selection      -> the green family (FOREST..MINT).
    * Body copy                      -> TEXT / TEXT_DIM / TEXT_FAINT.
    * Meaningful game colors (hearts, MP/AP bars, error text) keep their
      semantic hue — ERROR/WARN/INFO live here so even the exceptions are
      named, but they are deliberately *not* green.

This module must stay importable without pygame (inventory_ui is part of the
pygame-optional surface of the library); only the surface-producing helpers
need it and they raise if it is missing.
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in pygame-free installs
    PYGAME_AVAILABLE = False

EMBLEM_PATH = Path(__file__).resolve().parents[1] / "assets" / "emblem.png"

# -- core palette (sampled from assets/emblem.png) ---------------------------
NIGHT = (4, 17, 37)             # the emblem's navy field; window background
NIGHT_DEEP = (2, 10, 24)        # sunken wells: text inputs, chat entry bar
SURFACE = (9, 25, 44)           # resting panel/row fill
SURFACE_RAISED = (17, 41, 58)   # hovered rows, secondary chrome

FOREST = (22, 58, 48)           # darkest leaf green: quiet borders, dividers
MOSS = (29, 70, 54)             # deep leaf green: panel borders
EMERALD_DEEP = (34, 99, 56)     # inner-leaf green: overlay borders, buttons
EMERALD = (37, 121, 63)         # mid leaf green: primary actions
EMERALD_BRIGHT = (39, 160, 76)  # sunlit leaf: hover on primary actions
MINT = (41, 195, 95)            # brightest highlight: focus, selection, keys
MINT_PALE = (168, 232, 192)     # green-tinted light text for emphasis

TEXT = (232, 240, 235)
TEXT_DIM = (148, 168, 156)
TEXT_FAINT = (96, 116, 106)
TEXT_ON_ACCENT = (6, 26, 16)    # dark text over MINT/EMERALD fills

# Semantic colors (deliberately outside the green family).
ERROR = (240, 110, 100)
ERROR_DIM = (170, 95, 90)
WARN = (240, 205, 120)
INFO = (110, 200, 235)

# -- role aliases ------------------------------------------------------------
# Translucent plates. PLATE is the badge/chat backing (used with set_alpha);
# PANEL_BG backs the menu screens; OVERLAY_BG backs modals over live gameplay.
PLATE = (3, 13, 27)
PANEL_BG = (8, 24, 42, 240)
PANEL_BORDER = MOSS
OVERLAY_BG = (4, 14, 30, 215)
OVERLAY_BORDER = EMERALD_DEEP
SHADE = (2, 8, 18, 190)         # full-screen dim behind the big map
SELECTION = (34, 99, 56, 190)   # highlighted row in modal lists

BUTTON_BG = (16, 44, 40)
BUTTON_BG_HOVER = MOSS
BUTTON_BG_DISABLED = (10, 24, 34)
BUTTON_BORDER = FOREST
BUTTON_FG = TEXT
PRIMARY_BG = EMERALD
PRIMARY_HOVER = EMERALD_BRIGHT

INPUT_BG = NIGHT_DEEP
INPUT_BG_FOCUS = (7, 22, 40)
INPUT_BORDER = FOREST
INPUT_BORDER_FOCUS = MINT

SLOT_BG = (11, 30, 40)          # item/weapon slot wells
BAR_TRACK = (14, 30, 36)        # empty portion of MP/AP-style bars


def plate_rgba(alpha: int = 150) -> Tuple[int, int, int, int]:
    """The PLATE color with an explicit alpha, for SRCALPHA draws."""
    return (*PLATE, alpha)


# -- surface helpers ---------------------------------------------------------

def draw_panel(surf: "pygame.Surface", rect: "pygame.Rect", *,
               bg: Tuple[int, ...] = OVERLAY_BG,
               border: Optional[Tuple[int, int, int]] = OVERLAY_BORDER,
               border_w: int = 2, radius: int = 8) -> None:
    """Fill `rect` with the standard translucent themed panel + border."""
    plate = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(plate, bg, plate.get_rect(), border_radius=radius)
    if border is not None:
        pygame.draw.rect(plate, (*border, 255), plate.get_rect(),
                         width=border_w, border_radius=radius)
    surf.blit(plate, rect.topleft)


_GLOW_CACHE: Dict[tuple, "pygame.Surface"] = {}


def focus_glow(surf: "pygame.Surface", rect: "pygame.Rect", *,
               color: Tuple[int, int, int] = MINT, radius: int = 6,
               spread: int = 3) -> None:
    """A soft glow ring around `rect` — the focus treatment for inputs.

    Cached by (size, color, radius, spread): the glow only depends on the
    rect's size, so each distinctly-sized widget costs one surface build.
    """
    key = (rect.size, color, radius, spread)
    glow = _GLOW_CACHE.get(key)
    if glow is None:
        if len(_GLOW_CACHE) > 64:
            _GLOW_CACHE.clear()
        glow = pygame.Surface((rect.w + spread * 2, rect.h + spread * 2),
                              pygame.SRCALPHA)
        for i, alpha in enumerate((70, 42, 20)[:spread]):
            inset = spread - 1 - i
            pygame.draw.rect(glow, (*color, alpha),
                             glow.get_rect().inflate(-inset * 2, -inset * 2),
                             width=1, border_radius=radius + i)
        _GLOW_CACHE[key] = glow
    surf.blit(glow, (rect.x - spread, rect.y - spread))


# -- emblem art --------------------------------------------------------------

_EMBLEM_BASE: Optional["pygame.Surface"] = None
_EMBLEM_CACHE: Dict[int, "pygame.Surface"] = {}


def _load_emblem_base() -> Optional["pygame.Surface"]:
    """Load the emblem once: key out its baked-in navy field so the mandala
    can sit on any panel, then crop to the leaf art's bounding box."""
    global _EMBLEM_BASE
    if _EMBLEM_BASE is not None:
        return _EMBLEM_BASE
    try:
        img = pygame.image.load(str(EMBLEM_PATH))
    except (OSError, pygame.error, FileNotFoundError):
        return None
    img = img.convert_alpha() if pygame.display.get_init() else img
    keyed = pygame.Surface(img.get_size(), pygame.SRCALPHA)
    br, bg_, bb = NIGHT
    for y in range(img.get_height()):
        for x in range(img.get_width()):
            r, g, b, a = img.get_at((x, y))
            # The field is near-uniform navy; anything close to it goes
            # transparent. The darkest leaf greens are well clear of this.
            if abs(r - br) + abs(g - bg_) + abs(b - bb) < 24:
                a = 0
            keyed.set_at((x, y), (r, g, b, a))
    bounds = keyed.get_bounding_rect()
    _EMBLEM_BASE = keyed.subsurface(bounds).copy()
    return _EMBLEM_BASE


def emblem(scale: int = 1, alpha: int = 255) -> Optional["pygame.Surface"]:
    """The leaf-mandala logo, nearest-neighbour scaled (it is pixel art) by an
    integer factor, background keyed out. Returns None if the asset or pygame
    is unavailable, so callers can simply skip the blit."""
    if not PYGAME_AVAILABLE:
        return None
    base = _load_emblem_base()
    if base is None:
        return None
    scale = max(1, int(scale))
    scaled = _EMBLEM_CACHE.get(scale)
    if scaled is None:
        w, h = base.get_size()
        scaled = pygame.transform.scale(base, (w * scale, h * scale))
        _EMBLEM_CACHE[scale] = scaled
    if alpha >= 255:
        return scaled
    faded = scaled.copy()
    faded.set_alpha(alpha)
    return faded
