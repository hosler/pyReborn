from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

import pygame

from reborn_protocol.gs2 import copy_value, to_bool, to_num, to_str

logger = logging.getLogger(__name__)

_logged_once: set = set()


def _log_once(key: Tuple, msg: str, *fmt: Any) -> None:
    if key not in _logged_once:
        _logged_once.add(key)
        logger.warning(msg, *fmt)


# =============================================================================
# Profiles
#
# Torque/Reborn model (verified against the Login server's own addProfiles):
# a profile is DATA, not a control. Scripts derive them by classname --
#   new GuiBlueTransWindowProfile("IRC_WindowProfile") { fontsize = 24; ... }
# where the CLASSNAME names the PARENT profile (an engine builtin like
# GuiBlueTransWindowProfile, or a previously script-defined profile) and the
# ctor arg is the NEW profile's name. Controls reference profiles either by
# name string (`profile = "IRC_ButtonProfile";`) or by bare object reference
# (`profile = IRC_ScrollProfile;` -- resolves to the registered
# GuiControlProfile OBJECT). Effective style = the inheritance chain's field
# dicts overlaid child-over-parent, rooted at builtin field data (the
# engine-builtin Gui*Profiles are never script-defined). Bitmap skin art is
# not emulated; solid fills + alpha approximating the classic blue-trans v6
# look are the bar.
# =============================================================================

#: Largest text-shadow offset a script may ask for, in pixels each way. The
#: reference accepts any integer (GuiControlProfileProperties.cpp:463-466); a
#: hostile server could otherwise park the shadow anywhere on screen.
MAX_SHADOW_OFFSET = 16

#: Fonts a profile's `fonttype` can name are looked up as `<name>.ttf` in the
#: bundled asset directory and the user-content roots' `fonts/` directories
#: ONLY (never a path the script supplies). The name is a plain file stem.
_FONT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")

#: TFontManager::getFontBaseName (FourPlay quattroplay/src/TFontManager.cpp:
#: 144-186): three family prefixes map to the face files that shipped with the
#: client, anything else is the lowercased name itself.
_FONT_FAMILY_PREFIXES = (("tempus", "tempsitc"), ("trebuc", "trebuc"),
                         ("courier", "cour"))


class _TextShadow:
    """A profile's text shadow: truthy when `textshadow` is on. The offset
    and colour are the profile's `shadowoffset` / `shadowcolor`, which the
    reference initialises to (1, 1) and opaque black
    (GuiControlProfile.cpp:189-198) and applies in GuiControl::renderText
    (gui/GuiControl.cpp:2737-2740)."""

    __slots__ = ("enabled", "dx", "dy", "color")

    def __init__(self, enabled=False, dx=1, dy=1, color=(0, 0, 0, 255)):
        self.enabled = bool(enabled)
        self.dx = dx
        self.dy = dy
        self.color = color

    def __bool__(self):
        return self.enabled

    def __repr__(self):
        return (f"_TextShadow({self.enabled}, {self.dx}, {self.dy}, "
                f"{self.color})")


def _shadow_offset(value, default=(1, 1)):
    """A `shadowoffset` field ({x, y} array or 'x y' string) as a pair of
    ints clamped to +-MAX_SHADOW_OFFSET, else `default`."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        parts = list(value[:2])
    else:
        parts = to_str(value).replace(",", " ").split()[:2]
        if len(parts) < 2:
            return default
    try:
        return tuple(max(-MAX_SHADOW_OFFSET, min(MAX_SHADOW_OFFSET,
                                                 int(to_num(p)))) for p in parts)
    except (TypeError, ValueError, OverflowError):
        return default


#: The faces a `fonttype` can name, indexed once per session: lowercase file
#: stem -> resolved path, for every regular `.ttf` directly inside the bundled
#: asset directory and each user-content root's `fonts/` directory (earlier
#: roots win). A script can change `fonttype` every frame, so a lookup must
#: never touch the disk: after the index is built every name -- found or not
#: -- is one dict lookup, and unknown names fall back to the default face.
_font_index: Optional[Dict[str, str]] = None
_font_index_key: Optional[str] = None


def reset_font_resolution() -> None:
    """Forget the font index (a new session, or the content directories
    changed); it is rebuilt on the next lookup."""
    global _font_index, _font_index_key
    _font_index = None
    _font_index_key = None


def prime_font_roots() -> Dict[str, str]:
    """Build the font index from the bundled assets, then the user-content
    roots (asset_paths.content_dirs()). The prefs load and directory scans
    happen here, once, never from the draw path (game/setup.py primes it at
    startup). Rebuilt only when PYREBORN_CONTENT_DIR changes; call
    reset_font_resolution() after the saved content directories change.
    Only a regular file whose resolved path stays inside the directory it was
    listed in is indexed."""
    global _font_index, _font_index_key
    key = os.environ.get("PYREBORN_CONTENT_DIR", "")
    if _font_index is not None and key == _font_index_key:
        return _font_index
    roots = [Path(__file__).resolve().parents[2] / "assets"]
    try:
        from ... import asset_paths
        roots.extend(asset_paths.content_dirs())
    except Exception:  # noqa: BLE001 - prefs/asset trouble must not hide text
        log_swallowed(logger)
    index: Dict[str, str] = {}
    for root in roots:
        for directory in (root, root / "fonts"):
            try:
                real_dir = directory.resolve()
                entries = list(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.suffix.lower() != ".ttf" or not entry.is_file():
                        continue
                    resolved = entry.resolve()
                    if real_dir in resolved.parents:
                        index.setdefault(entry.stem.lower(), str(resolved))
                except OSError:
                    continue
    _font_index, _font_index_key = index, key
    return index


def resolve_font_file(font_type: str, bold: bool) -> Optional[str]:
    """Path of the face file a profile's `fonttype` names, or None.

    Mirrors the reference's file naming (`<base>` + `bd` for bold + `.ttf`,
    TFontManager.cpp:99-142) but only knows the faces prime_font_roots()
    indexed. None means "use the default face". Profiles are re-resolved
    every draw, so this is a dict lookup and never reads the disk."""
    name = font_type.strip().lower()
    if name.endswith(".ttf"):
        name = name[:-4]
    for prefix, base in _FONT_FAMILY_PREFIXES:
        if name.startswith(prefix):
            name = base
            break
    if not _FONT_NAME_RE.match(name):
        return None
    index = prime_font_roots()
    for stem in ([name + "bd", name] if bold else [name]):
        found = index.get(stem)
        if found:
            return found
    return None


class GuiProfile:
    """A RESOLVED style (plain colors/fonts + optional skin-bitmap name),
    built from profile field dicts by _profile_from_fields. bg may be None
    (no fill -- text profiles) or RGBA (translucent windows).

    `border_style` is the profile's `border` field, a RENDERER SELECTOR and
    not a pixel width: TGUIRender::renderBorder switches on it (FourPlay
    quattroplay/src/TGUIRender.cpp:59) with 1 = flat, 2/3/4 = bevels and
    `default: return` for everything else, while 5 is handled by the caller
    as the skinned mode (src/gui/GuiControl.cpp:3387-3410). The pixel
    thickness is the separate `borderthickness` field."""

    __slots__ = ("bg", "border", "border_style", "border_thickness",
                 "border_na", "fg", "title_bg",
                 "title_fg", "font_size", "font_bold", "align",
                 "bitmap", "transparency", "opaque", "text_shadow",
                 "font_type", "font_path", "fg_hl", "fg_sel", "fg_na", "modal")

    def __init__(self, bg, border, fg, title_bg, title_fg,
                 border_style=1, font_size=18, font_bold=False, align="left",
                 bitmap="", transparency=1.0, opaque=None, text_shadow=False,
                 border_thickness=1, border_na=None, font_type="",
                 font_path=None, fg_hl=None, fg_sel=None, modal=False,
                 fg_na=None):
        self.bg = bg
        self.border = border
        self.border_style = border_style
        self.border_thickness = border_thickness
        #: `bordercolorna`, the light edge of border styles 2 and 3
        self.border_na = border_na if border_na is not None else border
        self.fg = fg
        self.title_bg = title_bg
        self.title_fg = title_fg
        self.font_size = font_size
        self.font_bold = font_bold
        self.align = align
        #: profile skin-art sheet filename ("guiblue_window_noback.png", ...)
        #: -- the Torque bitmap-array model; empty = solid-color fallback
        self.bitmap = bitmap
        self.transparency = transparency
        #: Torque `opaque` field: plain containers/text draw a background
        #: fill ONLY when this is set (GuiControl semantics); None = unset
        self.opaque = opaque
        #: bool, or a _TextShadow carrying the profile's offset and colour
        self.text_shadow = text_shadow
        #: `fonttype` as the script wrote it, and the face file it resolved
        #: to (None = default face)
        self.font_type = font_type
        self.font_path = font_path
        #: `fontcolorhl` / `fontcolorsel`; None = the script never set them
        self.fg_hl = fg_hl
        self.fg_sel = fg_sel
        #: `fontcolorna`, the text colour of an inactive control (None = not
        #: set: draw sites dim `fg` instead)
        self.fg_na = fg_na
        #: `modal`: a visible, awake canvas-level control with a modal
        #: profile is fitted to the canvas (GuiCanvas::fitMainControls,
        #: gui/GuiCanvas.cpp:251-305)
        self.modal = modal


_DEFAULT_PROFILE_NAME = "guidefaultprofile"
_MAX_PARENT_DEPTH = 4096
_MAX_PROFILE_CHAIN = 16

# Engine-builtin profile field data (never script-defined; the Login scripts
# derive from these). Same field vocabulary construction blocks use:
# fillcolor {r,g,b[,a]}, fontcolor, bordercolor, fillcolorhl, fontsize,
# fontstyle, align, border (width; 0 = borderless). Palette is the classic
# v6 look: dark translucent blue windows, steel-blue fills, white/pale text.
_BLUE_FILL = (41, 82, 156)
_BLUE_HL = (96, 144, 208)
_PALE_TEXT = (192, 224, 255)

_BUILTIN_PROFILE_FIELDS: Dict[str, Dict[str, Any]] = {
    "guicontrolprofile": {},
    "guidefaultprofile": {
        "fillcolor": (24, 40, 88, 216), "bordercolor": _BLUE_HL,
        "fontcolor": (235, 240, 250), "fillcolorhl": _BLUE_FILL,
    },
    "guicontentprofile": {
        "fillcolor": (16, 28, 64, 216), "bordercolor": _BLUE_HL,
        "fontcolor": (235, 240, 250), "fillcolorhl": _BLUE_FILL,
    },
    "guibluewindowprofile": {
        "fillcolor": (16, 40, 104, 255), "bordercolor": _BLUE_HL,
        "fontcolor": (255, 255, 255), "fillcolorhl": _BLUE_FILL,
        "fontsize": 20, "fontstyle": "b",
        "bitmap": "guiblue_window.png",
    },
    "guibluetranswindowprofile": {
        "fillcolor": (16, 40, 104, 176), "bordercolor": _BLUE_HL,
        "fontcolor": (255, 255, 255), "fillcolorhl": (41, 82, 156, 224),
        "fontsize": 20, "fontstyle": "b",
        "bitmap": "guiblue_window_noback.png",
    },
    "guibluebuttonprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": (255, 255, 255),
        "fillcolorhl": _BLUE_HL, "fontsize": 16, "fontstyle": "b",
        "bitmap": "guiblue_button.png",
    },
    "guistartscreenbuttonprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": (255, 255, 255),
        "fillcolorhl": _BLUE_HL, "fontsize": 16, "fontstyle": "b",
    },
    "guiscrollprofile": {
        "fillcolor": (16, 32, 80, 216), "bordercolor": _BLUE_HL,
        "bitmap": "guiblue_scroll.png",
    },
    "guibluetransscrollprofile": {
        "fillcolor": (16, 32, 80, 144), "bordercolor": _BLUE_HL,
        "bitmap": "guiblue_scroll.png",
    },
    "guitextprofile": {"fontcolor": (255, 255, 255), "fontsize": 18},
    "guistartscreentextprofile": {"fontcolor": (255, 255, 255), "fontsize": 16},
    "guibluetextprofile": {"fontcolor": _PALE_TEXT, "fontsize": 18},
    "guimltextprofile": {"fontcolor": (255, 255, 255), "fontsize": 16},
    "guibluemltextprofile": {"fontcolor": _PALE_TEXT, "fontsize": 16},
    "guimiddlebluemltextprofile": {"fontcolor": _PALE_TEXT, "fontsize": 16,
                                   "align": "center"},
    "guitextlistprofile": {
        "fontcolor": (255, 255, 255), "fillcolorhl": _BLUE_HL, "fontsize": 16,
    },
    "guitabprofile": {
        "fillcolor": (24, 48, 112, 224), "bordercolor": _BLUE_HL,
        "fontcolor": _PALE_TEXT, "fillcolorhl": _BLUE_HL,
        "fontsize": 14, "fontstyle": "b", "align": "center",
        "bitmap": "guiblue_tab.png",
    },
    "guitreeviewprofile": {
        "fontcolor": (255, 255, 255), "fillcolorhl": (255, 255, 255, 144),
        "fontsize": 16,
    },
    "guibluetreeviewprofile": {
        "fontcolor": _PALE_TEXT, "fillcolorhl": (255, 255, 255, 144),
        "fontsize": 16, "fontstyle": "b",
    },
    "guipopupmenuprofile": {
        "fillcolor": (16, 32, 96, 240), "bordercolor": _BLUE_HL,
        "fontcolor": (255, 255, 255), "fillcolorhl": _BLUE_HL,
    },
    "guitexteditprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": (255, 255, 255),
        "fillcolorhl": _BLUE_HL, "fontsize": 16,
        "bitmap": "guiblue_textedit.png",
    },
    "guibluetexteditsliderprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": (255, 255, 255),
        "fillcolorhl": _BLUE_HL, "fontsize": 16, "fontstyle": "b",
    },
    # The remaining GuiBlue* engine builtins Login's Options window
    # references (blue variants of the base profiles above; same skin art).
    "guibluetabprofile": {
        "fillcolor": (24, 48, 112, 224), "bordercolor": _BLUE_HL,
        "fontcolor": _PALE_TEXT, "fillcolorhl": _BLUE_HL,
        "fontsize": 14, "fontstyle": "b", "align": "center",
        "bitmap": "guiblue_tab.png",
    },
    "guibluescrollprofile": {
        "fillcolor": (16, 32, 80, 216), "bordercolor": _BLUE_HL,
        "bitmap": "guiblue_scroll.png",
    },
    "guibluetextlistprofile": {
        "fontcolor": _PALE_TEXT, "fillcolorhl": _BLUE_HL, "fontsize": 16,
    },
    "guibluecheckboxprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": _PALE_TEXT, "fontsize": 16,
    },
    "guibluesliderprofile": {
        "fillcolor": (16, 32, 80, 216), "bordercolor": _BLUE_HL,
        "fillcolorhl": _BLUE_HL,
    },
    "guibluepopupmenuprofile": {
        "fillcolor": (16, 32, 96, 240), "bordercolor": _BLUE_HL,
        "fontcolor": (255, 255, 255), "fillcolorhl": _BLUE_HL,
    },
    "guibluetexteditprofile": {
        "fillcolor": (_BLUE_FILL[0], _BLUE_FILL[1], _BLUE_FILL[2], 255),
        "bordercolor": _BLUE_HL, "fontcolor": (255, 255, 255),
        "fillcolorhl": _BLUE_HL, "fontsize": 16,
        "bitmap": "guiblue_textedit.png",
    },
}

_DEFAULT_GUIPROFILE = GuiProfile(
    bg=(24, 40, 88, 216), border=_BLUE_HL, fg=(235, 240, 250),
    title_bg=_BLUE_FILL, title_fg=(235, 240, 250))

#: profile fields that carry style meaning (everything else a script sets on
#: a profile -- textoffset, tab, modal -- is retained on the object but not
#: consulted by the solid-color renderer)
_STYLE_FIELDS = frozenset({
    "fillcolor", "fontcolor", "bordercolor", "bordercolorna", "fillcolorhl",
    "fillcolorna", "fontsize", "fontstyle", "align", "justify", "border",
    "borderthickness", "opaque", "bitmap", "transparency", "textshadow",
    "shadowoffset", "shadowcolor", "fonttype", "fontcolorhl", "fontcolorsel",
    "fontcolorna", "modal",
})

#: `justify` and `align` are ONE slot under two names -- identical getter and
#: setter pointers in the profile table (quattroplay/src/gui/
#: GuiControlProfileProperties.cpp:550 vs :582) -- and the live content spells
#: it `justify`. Collapsing the alias at merge time keeps last-write-wins
#: within a profile and child-over-parent across the chain.
_STYLE_ALIASES = {"justify": "align"}

#: values `align`/`justify` accepts, byte-exact: the setter walks
#: AlignmentArr (GuiControlProfileProperties.cpp:543-547) with TString's
#: memcmp `==` and silently keeps the old value on a miss.
_ALIGNMENTS = ("left", "center", "right")


def _color(value, default=None):
    """A Torque color field ({r,g,b} / {r,g,b,a} array, or 'r g b' string)
    as a clamped int tuple, else `default`."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        parts = value[:4]
    else:
        parts = to_str(value).replace(",", " ").split()
        if len(parts) < 3:
            return default
        parts = parts[:4]
    try:
        return tuple(max(0, min(255, int(to_num(p)))) for p in parts)
    except (TypeError, ValueError):
        return default


def _profile_fields(ref: Any, mgr, visited: set) -> Dict[str, Any]:
    """Merged style-field dict for a profile reference (object or name),
    walking the classname-parent chain child-over-parent down to builtin
    field data. Cycles/depth guarded via `visited`."""
    if len(visited) > _MAX_PROFILE_CHAIN:
        return {}
    if isinstance(ref, GuiControlProfile):
        if id(ref) in visited:
            return {}
        visited.add(id(ref))
        base = _profile_fields(ref.parent_profile_name, mgr, visited) \
            if ref.parent_profile_name else {}
        for key, value in ref._members.items():
            if key not in _STYLE_FIELDS:
                continue
            key = _STYLE_ALIASES.get(key, key)
            # An enum field compares its value byte-exact and silently keeps
            # the previous one on a miss (GuiControlProfileProperties.cpp:
            # 11-21) -- here "previous" is whatever the parent chain merged.
            if key == "align" and to_str(value) not in _ALIGNMENTS:
                continue
            base[key] = value
        return base
    name = to_str(ref).lower() if ref is not None else ""
    if not name or name in visited:
        return {}
    visited.add(name)
    obj = mgr._named.get(name) if mgr is not None else None
    if isinstance(obj, GuiControlProfile):
        return _profile_fields(obj, mgr, visited)
    builtin = _BUILTIN_PROFILE_FIELDS.get(name)
    if builtin is not None:
        return dict(builtin)
    _log_once(("profile", name),
              "GS2 GUI: unknown profile %r, using default", to_str(ref))
    return {}


def _profile_from_fields(fields: Dict[str, Any]) -> GuiProfile:
    if not fields:
        return _DEFAULT_GUIPROFILE
    bg = _color(fields.get("fillcolor"))
    fg = _color(fields.get("fontcolor"), (235, 240, 250))
    border = _color(fields.get("bordercolor"),
                    _shade(bg, 1.5) if bg else _BLUE_HL)
    title_bg = _color(fields.get("fillcolorhl"),
                      _shade(bg, 1.4) if bg else _BLUE_FILL)
    # An unset `border` is left at 1 (flat): the reference initialises the
    # field neither in GuiControlProfile's constructor nor in initObject
    # (quattroplay/src/gui/GuiControlProfile.cpp:37-63, :184-221) -- it
    # arrives via copyProfileFrom(GuiDefaultProfile), which our builtin field
    # data does not carry a `border` for.
    style = 1
    if "border" in fields:
        style = int(to_num(fields.get("border")))
    thickness = 1
    if "borderthickness" in fields:
        thickness = max(0, int(to_num(fields.get("borderthickness"))))
    size = int(to_num(fields.get("fontsize"))) or 18
    size = max(9, min(28, size))
    transparency = 1.0
    if "transparency" in fields:
        transparency = max(0.0, min(1.0, to_num(fields.get("transparency"))))
    opaque = to_bool(fields["opaque"]) if "opaque" in fields else None
    align = to_str(fields.get("align", "left"))
    bold = "b" in to_str(fields.get("fontstyle", "")).lower()
    font_type = ""
    font_path = None
    if "fonttype" in fields:
        font_type = to_str(fields["fonttype"])[:64]
        font_path = resolve_font_file(font_type, bold)
    shadow = _TextShadow(to_bool(fields.get("textshadow", 0)))
    if "shadowoffset" in fields:
        shadow.dx, shadow.dy = _shadow_offset(fields["shadowoffset"])
    if "shadowcolor" in fields:
        shadow.color = _color(fields["shadowcolor"], shadow.color)
    return GuiProfile(
        bg=bg, border=border, fg=fg, title_bg=title_bg, title_fg=fg,
        border_style=style, border_thickness=thickness,
        border_na=_color(fields.get("bordercolorna"), border),
        font_size=size,
        font_bold=bold,
        align=align if align in _ALIGNMENTS else "left",
        bitmap=to_str(fields.get("bitmap", "")),
        transparency=transparency, opaque=opaque, text_shadow=shadow,
        font_type=font_type, font_path=font_path,
        fg_hl=_color(fields.get("fontcolorhl")),
        fg_sel=_color(fields.get("fontcolorsel")),
        fg_na=_color(fields.get("fontcolorna")),
        modal=to_bool(fields.get("modal", 0)))


def _readable_on(fill, base_bg, default_fg):
    """Text color that stays readable over a highlight `fill` (alpha-
    composited against base_bg): the white/144 tree-and-list selection bar
    washes out pale text, so light effective fills flip to dark text --
    matching the official selected-row look."""
    if fill is None:
        return default_fg
    a = (fill[3] / 255.0) if len(fill) > 3 else 1.0
    bg = base_bg[:3] if base_bg else (20, 35, 80)
    eff = tuple(a * c + (1.0 - a) * b for c, b in zip(fill[:3], bg))
    lum = 0.299 * eff[0] + 0.587 * eff[1] + 0.114 * eff[2]
    return (10, 26, 64) if lum > 140 else default_fg


def _shade(color, factor: float):
    """Multiply an RGB(A) tuple's color channels by `factor`, clamped to
    0-255 (alpha preserved) -- used for the interactive-control hover
    (lighter)/pressed (darker) visual states (GS2GuiManager tracks
    hover/press by mouse position; see `_set_hover`/`_set_pressed`)."""
    rgb = tuple(max(0, min(255, int(c * factor))) for c in color[:3])
    return rgb + tuple(color[3:4])


def _fill_rect(surf, color, rect, width=0, border_radius=0) -> None:
    """pygame.draw.rect that honors an RGBA color's alpha (per-blit
    translucency via a scratch SRCALPHA surface -- the blue-trans windows).
    color=None or an empty rect is a no-op."""
    if color is None or rect.width <= 0 or rect.height <= 0:
        return
    if len(color) >= 4 and color[3] < 255:
        scratch = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(scratch, color, scratch.get_rect(), width, border_radius)
        surf.blit(scratch, rect.topleft)
    else:
        pygame.draw.rect(surf, color[:3], rect, width, border_radius)


_BEVEL_DARK = (0, 0, 0)
_BEVEL_LIGHT = (255, 255, 255)


def _draw_border(surf, rect: pygame.Rect, prof: GuiProfile,
                 skin: Optional["_Skin"] = None, border_radius: int = 0) -> None:
    """Paint the profile's `border` STYLE over `rect`.

    Faithful to TGUIRender::renderBorder's four cases (FourPlay quattroplay/
    src/TGUIRender.cpp:59-153), which draw 1px lines in every case -- the
    line width there is the constant 1.0, so `borderthickness` is layout
    inset only (it is what GuiScrollCtrl measures with,
    src/gui/GuiScrollCtrl.cpp:141). Styles 2/3/4 are two concentric 1px
    rings, half of each in a bevel color (white/black,
    TGUIRender.cpp:13-14). Style 5 is the skinned mode, whose renderer is
    the style sheet we cannot resolve headless; the reference's own no-style
    fallback is the profile bitmap (src/gui/GuiControl.cpp:3409), so that is
    what we draw. Style 0 and anything unrecognised draw nothing.
    """
    style = prof.border_style
    if style <= 0 or rect.width <= 0 or rect.height <= 0:
        return
    if style == 1:
        _fill_rect(surf, prof.border, rect, 1, border_radius)
        return
    if style == 5:
        if skin is not None:
            skin.draw_nine(surf, rect, 0, int(255 * prof.transparency))
        return
    if style not in (2, 3, 4):
        return
    outer = rect
    inner = rect.inflate(-2, -2)
    if style == 2:
        rings = ((outer, prof.border_na, _BEVEL_DARK),
                 (inner, _BEVEL_DARK, prof.border_na))
    elif style == 3:
        rings = ((outer, prof.border_na, _BEVEL_DARK),
                 (inner, _BEVEL_LIGHT, prof.bg or prof.border))
    else:
        rings = ((outer, _BEVEL_DARK, _BEVEL_LIGHT),
                 (inner, None, prof.border))
    for box, top_left, bottom_right in rings:
        if box.width <= 0 or box.height <= 0:
            continue
        if top_left is not None:
            pygame.draw.line(surf, top_left[:3], box.topleft,
                             (box.right - 1, box.y))
            pygame.draw.line(surf, top_left[:3], box.topleft,
                             (box.x, box.bottom - 1))
        if bottom_right is not None:
            pygame.draw.line(surf, bottom_right[:3], (box.x, box.bottom - 1),
                             (box.right - 1, box.bottom - 1))
            pygame.draw.line(surf, bottom_right[:3], (box.right - 1, box.y),
                             (box.right - 1, box.bottom - 1))


def _font(fonts, prof: GuiProfile):
    """The profile's font via the game FontManager (fonts.at(size, bold));
    falls back to the 'small' role for older/simpler fonts objects."""
    if fonts is None:
        return None
    at = getattr(fonts, "at", None)
    if at is not None:
        if prof.font_path:
            try:
                return at(prof.font_size, prof.font_bold, path=prof.font_path)
            except Exception:  # unreadable face file: default face below
                log_swallowed(logger, level=logging.DEBUG)
        try:
            return at(prof.font_size, prof.font_bold)
        except Exception:
            log_swallowed(logger, level=logging.DEBUG)
    return fonts.get("small")


def _wrap_text(font: pygame.font.Font, text: str, max_width: int) -> List[str]:
    """Greedy word-wrap for GuiMLTextCtrl; preserves explicit newlines."""
    lines: List[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if not cur or (max_width <= 0 or font.size(trial)[0] <= max_width):
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _draw_label(surf, font, text, color, pos, shadow=False):
    """Render one text run, with the profile's optional drop shadow
    (textshadow=true on most IRC_* profiles -- the classic look). `shadow` is
    False, True (the default 1px black shadow) or a profile's _TextShadow,
    whose offset and colour come from `shadowoffset` / `shadowcolor`."""
    if shadow:
        if shadow is True:
            dx, dy, tint = 1, 1, (0, 0, 0, 255)
        else:
            dx, dy, tint = shadow.dx, shadow.dy, shadow.color
        cast = font.render(text, True, tuple(tint[:3]))
        if len(tint) > 3 and tint[3] < 255:
            cast.set_alpha(tint[3])
        surf.blit(cast, (pos[0] + dx, pos[1] + dy))
    label = font.render(text, True, color)
    surf.blit(label, pos)
    return label


from .base import GuiControl
from reborn_protocol.gs2 import GS2Object  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from ...logutil import log_swallowed

if TYPE_CHECKING:  # annotation-only; real imports would cycle
    from .skins import _Skin


class GuiControlProfile(GuiControl):
    """A named PROFILE DEFINITION (`new <ParentProfile>("IRC_...Profile")
    { fillcolor = {...}; }` -- see the module's Profiles section), not a
    visual control: registered for later `profile = <name-or-object>`
    references, never drawn, never in the control tree (see
    create_control/addcontrol's is_profile guards).

    `parent_profile_name` is the classname the `new` used -- an engine
    builtin (GuiBlueTransWindowProfile) or another script profile
    (IRC_WindowProfile) -- and roots this profile's inheritance chain.

    has() claims EVERYTHING: a profile is a pure property bag, and both the
    construction block and later `with (IRC_...Profile) { fillcolor = ...; }`
    restyles write through the VM's EXISTENCE-GATED with-scope assignment --
    unclaimed field names silently fell through to temps/globals, which is
    exactly why every script profile resolved with an empty member list
    ('<GS2Object GuiBlueTransWindowProfile []>' in the 07-24 stderr)."""

    CTRL_CLASS = "GuiControlProfile"
    is_profile = True
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({"preloadfont"})

    def __init__(self, ctor_arg: Any = None, parent_name: str = ""):
        super().__init__(ctor_arg)
        self.visible = False
        self.parent_profile_name = parent_name.lower()

    def has(self, key: str) -> bool:
        return True

    def _m_preloadfont(self, *args) -> float:
        # Font loading is lazy in the pygame renderer. Claiming this method
        # preserves the reference's eager-cache hint without changing state.
        return 0.0

    def copy_from(self, source: Any) -> None:
        """The ONE GUI class where `copyfrom` really copies:
        GuiControlProfile's table sets the TGraalVar::copyFrom opt-in bit
        (FourPlay quattroplay/src/gui/GuiControlProfileProperties.cpp:618;
        the gate is TGraalVar.cpp:2208-2214), and profile derivation
        (`new <Parent>("Name")`) and useownprofile both route through it.

        The reference copies all 49 registered properties -- a profile's
        registered fields ARE its full effective style there (derivation
        copies, there is no live parent chain). Our model resolves unset
        fields through `parent_profile_name` at draw time, so copying the
        source's members PLUS its chain root is the equivalent operation."""
        if source is self:
            return
        if isinstance(source, GuiControlProfile):
            for key, value in source._members.items():
                self._members[key] = copy_value(value)
            self.parent_profile_name = source.parent_profile_name
            return
        # a builtin-profile NAME (no registered object): adopt it as chain root
        if isinstance(source, str):
            self.parent_profile_name = source.lower()
            return
        GS2Object.copy_from(self, source)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        return
