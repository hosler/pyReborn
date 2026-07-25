"""GS2 GUI-controls rendering layer: showgui/GuiControl support.

Modern Reborn servers build menus/shops/dialogs by sending GS2 bytecode that
constructs a tree of `Gui*Ctrl` objects and shows/hides it. Before this module
every GUI builtin (`addcontrol`, `showgui`, `hidegui`, `new GuiButtonCtrl`...)
was a silent stub in gs2_client.py -- nothing rendered, nothing dispatched.

Investigation: how does `new GuiButtonCtrl("x") { onAction() {...} }` compile?
----------------------------------------------------------------------------
Verified against `gs2test`, the real GServer-v2 compiler binary (built from
xtjoeytx/gs2-parser, cached at reborn-protocol/tests/tools/gs2test), which is
the ground-truth toolchain our disassembler/VM corpus is checked against.

1. `new ClassName(arg) { ... }` with an inline `{ }` body is a **statement**
   (`stmt_new` in gs2parser.y -> `StatementNewNode`), not an expression --
   `temp.ctrl = new GuiButtonCtrl("x") { ... }` fails to compile ("missing
   semicolon"). There is no assignment token in that grammar rule at all.
   `GS2CompilerVisitor::Visit(StatementNewNode*)` instead:
     - evaluates the single constructor arg expression (asserted to be
       exactly one arg) to a *reference* (a VarRef/member-access lvalue, e.g.
       `temp.ctrl`), not a value;
     - duplicates that reference, constructs the object with the arg's
       *current* (pre-call) value, then immediately OP_ASSIGNs the new object
       back into that same reference -- so `new GuiButtonCtrl(temp.ctrl) {..}`
       both reads and overwrites `temp.ctrl`;
     - opens `with (thatobject) { <block> }` so bare identifier assignments
       inside the block (`x = 10;`, `text = "Hello";`) land as members on the
       newly constructed object;
     - after the with-block, auto-emits **exactly one** `addcontrol(<that
       reference>)` call per `new` statement -- the script never calls
       addcontrol() itself for this idiom. Nested `new` statements (a window
       containing child controls) run their own create+with+addcontrol fully
       (innermost first) before the enclosing statement's own addcontrol call
       fires, i.e. children are always fully constructed and addcontrol()-ed
       before their parent is. `addcontrol()`'s single argument carries no
       parent pointer -- this module infers nesting purely from that
       innermost-first call order (see GS2GuiManager's construction stack).
   (An alternate, also-valid idiom compiles fine too: the plain expression
   form `temp.ctrl = new GuiButtonCtrl("name");` followed by an explicit,
   script-written `addcontrol(temp.ctrl);` call -- same two host hooks handle
   both.)

2. Event handlers use the expression form `onAction = function() { ... };`
   inside the with-block (`expr_functionobj` / `ExpressionFnObject`), not a
   distinct "method on the constructed object" mechanism. The compiler lifts
   the function body out as an ordinary same-script function (a generated
   name like `function_100_1`), and the assignment's RHS becomes
   `this.function_100_1` (OP_THIS + OP_MEMBER_ACCESS + OP_CONV_TO_OBJECT) --
   `this` being the *calling* script's this (e.g. the weapon's onCreated),
   not the with-block's target. The shared VM (reborn_protocol/gs2/vm.py)
   resolves that RHS itself: reading `this.<generated-function-name>` yields
   a `GS2ScriptFunction` bound to the owning VM, so the assignment stores a
   real callable in the control's `onaction` slot and `fire_event`'s
   `handler = self.get(event); if callable(handler)` path picks it up with
   no host involvement. (An earlier round emulated this at the host layer,
   here and in gs2_client.py's `_ThisObject`; both emulations were removed
   once the VM took the resolution over.)
   `GS2VM.script_function(name)` is the explicit lookup if a handler ever
   needs resolving by name instead of by slot; it recurses into joined
   classes, so a handler defined inside a joined class's own `new ... {}`
   block resolves too. `host.create_object()` was already consulted for
   every `new` (see `_op_new_object` in vm.py), so construction needed no
   vm.py change either.

Wiring
------
`GS2ClientHost.create_object()` routes any classname starting with "gui" to
`GS2GuiManager.create_control()`; `call_builtin()` routes `addcontrol`,
`showgui`, `hidegui`, and `destroy` (both the bare-function and
`ctrl.destroy()` object-method forms) to the matching manager method.
`render.py` draws the manager last (topmost, on top of HUD/inventory);
`handle_event(event)` is exposed for the input mixin's modal chain to call.

Coordinates are absolute screen pixels, top-left origin, regardless of
nesting depth (per the C# client's reference semantics) -- a child's x/y are
plain numbers set by field assignment inside the with-block, not relative to
its parent. `GuiScrollCtrl` is the one place children get an *additional*
scroll offset applied at render/hit-test time (see `GuiControl.rect()`).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pygame

from reborn_protocol.gs2 import GS2Object, to_bool, to_num, to_str

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

class GuiProfile:
    """A RESOLVED style (plain colors/fonts + optional skin-bitmap name),
    built from profile field dicts by _profile_from_fields. bg may be None
    (no fill -- text profiles) or RGBA (translucent windows)."""

    __slots__ = ("bg", "border", "border_width", "fg", "title_bg",
                 "title_fg", "font_size", "font_bold", "align",
                 "bitmap", "transparency", "opaque", "text_shadow")

    def __init__(self, bg, border, fg, title_bg, title_fg,
                 border_width=1, font_size=18, font_bold=False, align="left",
                 bitmap="", transparency=1.0, opaque=None, text_shadow=False):
        self.bg = bg
        self.border = border
        self.border_width = border_width
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
        self.text_shadow = text_shadow


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
}

_DEFAULT_GUIPROFILE = GuiProfile(
    bg=(24, 40, 88, 216), border=_BLUE_HL, fg=(235, 240, 250),
    title_bg=_BLUE_FILL, title_fg=(235, 240, 250))

#: profile fields that carry style meaning (everything else a script sets on
#: a profile -- bitmap art names, textoffset, shadow params -- is retained on
#: the object but not consulted by the solid-color renderer)
_STYLE_FIELDS = frozenset({
    "fillcolor", "fontcolor", "bordercolor", "fillcolorhl", "fillcolorna",
    "fontsize", "fontstyle", "align", "border", "opaque",
    "bitmap", "transparency", "textshadow",
})


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
        own = {k: v for k, v in ref._members.items() if k in _STYLE_FIELDS}
        base.update(own)
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
    bw = 1
    if "border" in fields:
        bw = max(0, min(3, int(to_num(fields.get("border")))))
    size = int(to_num(fields.get("fontsize"))) or 18
    size = max(9, min(28, size))
    transparency = 1.0
    if "transparency" in fields:
        transparency = max(0.0, min(1.0, to_num(fields.get("transparency"))))
    opaque = to_bool(fields["opaque"]) if "opaque" in fields else None
    return GuiProfile(
        bg=bg, border=border, fg=fg, title_bg=title_bg, title_fg=fg,
        border_width=bw, font_size=size,
        font_bold="b" in to_str(fields.get("fontstyle", "")).lower(),
        align=to_str(fields.get("align", "left")).lower() or "left",
        bitmap=to_str(fields.get("bitmap", "")),
        transparency=transparency, opaque=opaque,
        text_shadow=to_bool(fields.get("textshadow", 0)))


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


def _font(fonts, prof: GuiProfile):
    """The profile's font via the game FontManager (fonts.at(size, bold));
    falls back to the 'small' role for older/simpler fonts objects."""
    if fonts is None:
        return None
    at = getattr(fonts, "at", None)
    if at is not None:
        try:
            return at(prof.font_size, prof.font_bold)
        except Exception:
            pass
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
    """Render one text run, with the profile's optional 1px black drop
    shadow (textshadow=true on most IRC_* profiles -- the classic look)."""
    if shadow:
        surf.blit(font.render(text, True, (0, 0, 0)), (pos[0] + 1, pos[1] + 1))
    label = font.render(text, True, color)
    surf.blit(label, pos)
    return label


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


# =============================================================================
# GuiMLTextCtrl mini-HTML
#
# The wire text is Torque ML ("<font size=4><b><i>Account:</i></b></font>
# hosler<br>", headings, <center>, <a href=...>). Full HTML is out of
# scope; this handles exactly the vocabulary the live Login server sends
# so the panes read cleanly instead of showing raw markup.
# =============================================================================

_ML_TOKEN_RE = None                     # compiled lazily (re import below)

#: Torque <font size=N> steps mapped to pixel sizes around the profile base
_ML_FONT_SIZES = {1: 9, 2: 11, 3: 13, 4: 15, 5: 17, 6: 20, 7: 24}
_ML_HEADING_SIZES = {1: 24, 2: 21, 3: 19, 4: 17, 5: 15, 6: 13}
_ML_LINK_COLOR = (224, 224, 255)

_ML_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
                "&quot;": '"', "&#39;": "'"}


class _MLSegment:
    __slots__ = ("text", "bold", "italic", "size", "color", "link")

    def __init__(self, text, bold, italic, size, color, link):
        self.text = text
        self.bold = bold
        self.italic = italic
        self.size = size            # None = profile base size
        self.color = color          # None = profile font color
        self.link = link


def _ml_parse_color(value: str):
    value = (value or "").strip().strip('"').strip("'")
    if value.startswith("#"):
        value = value[1:]
        try:
            if len(value) >= 6:
                return (int(value[0:2], 16), int(value[2:4], 16),
                        int(value[4:6], 16))
        except ValueError:
            return None
    named = {"white": (255, 255, 255), "black": (0, 0, 0),
             "red": (224, 64, 64), "yellow": (240, 224, 96),
             "green": (96, 224, 96), "blue": (120, 160, 255)}
    return named.get(value.lower())


def parse_mltext(text: str):
    """Parse Torque ML text into paragraphs: (align, [segments]) lists.
    Unknown tags are stripped; <br>/<p>/<h*> produce line breaks."""
    import re
    global _ML_TOKEN_RE
    if _ML_TOKEN_RE is None:
        _ML_TOKEN_RE = re.compile(r"<[^<>]*>")
    for ent, ch in _ML_ENTITIES.items():
        text = text.replace(ent, ch)

    paragraphs: List[Tuple[str, List[_MLSegment]]] = []
    cur: List[_MLSegment] = []
    bold = 0
    italic = 0
    align_stack: List[str] = []
    size_stack: List[Optional[int]] = []
    color_stack: List[Optional[Tuple[int, int, int]]] = []
    link_depth = 0
    ignore_linebreaks = False

    def cur_align() -> str:
        return align_stack[-1] if align_stack else "left"

    def flush(force: bool = False):
        # Block-tag boundaries (h*, p, center) only break a line when there
        # is pending text; <br> forces a break so "<br><br>" keeps the
        # intentional blank line.
        nonlocal cur
        if cur or force:
            paragraphs.append((cur_align(), cur))
            cur = []

    def emit(run: str):
        if not run:
            return
        cur.append(_MLSegment(
            run, bold > 0, italic > 0,
            size_stack[-1] if size_stack else None,
            (_ML_LINK_COLOR if link_depth > 0
             else (color_stack[-1] if color_stack else None)),
            link_depth > 0))

    pos = 0
    for m in _ML_TOKEN_RE.finditer(text):
        raw = text[pos:m.start()]
        if raw:
            if not ignore_linebreaks and "\n" in raw:
                parts = raw.split("\n")
                for i, part in enumerate(parts):
                    emit(part)
                    if i < len(parts) - 1:
                        flush(force=True)
            else:
                emit(raw.replace("\n", " "))
        pos = m.end()
        tag = m.group(0)[1:-1].strip()
        name, _, attrs = tag.partition(" ")
        name = name.lower()
        closing = name.startswith("/")
        if closing:
            name = name[1:]
        if name in ("br", "br/"):
            flush(force=True)
        elif name == "p":
            flush()
            if closing:
                if align_stack:
                    align_stack.pop()
            else:
                am = None
                for chunk in attrs.split():
                    k, _, v = chunk.partition("=")
                    if k.lower() == "align":
                        am = v.strip('"').strip("'").lower()
                align_stack.append(am or cur_align())
        elif name == "center":
            flush()
            if closing:
                if align_stack:
                    align_stack.pop()
            else:
                align_stack.append("center")
        elif name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            flush()
            if closing:
                bold = max(0, bold - 1)
                if size_stack:
                    size_stack.pop()
            else:
                bold += 1
                size_stack.append(_ML_HEADING_SIZES.get(int(name[1]), 17))
        elif name in ("b", "strong"):
            bold = max(0, bold - 1) if closing else bold + 1
        elif name in ("i", "em"):
            italic = max(0, italic - 1) if closing else italic + 1
        elif name == "font":
            if closing:
                if size_stack:
                    size_stack.pop()
                if color_stack:
                    color_stack.pop()
            else:
                fsize = size_stack[-1] if size_stack else None
                fcolor = color_stack[-1] if color_stack else None
                for chunk in attrs.split():
                    k, _, v = chunk.partition("=")
                    k = k.lower()
                    if k == "size":
                        try:
                            fsize = _ML_FONT_SIZES.get(
                                int(v.strip('"').strip("'")), fsize)
                        except ValueError:
                            pass
                    elif k == "color":
                        fcolor = _ml_parse_color(v) or fcolor
                size_stack.append(fsize)
                color_stack.append(fcolor)
        elif name == "a":
            link_depth = max(0, link_depth - 1) if closing else link_depth + 1
        elif name == "ignorelinebreaks":
            ignore_linebreaks = True
        # anything else (img, table, spans...) is stripped silently
    tail = text[pos:]
    if tail:
        if not ignore_linebreaks and "\n" in tail:
            parts = tail.split("\n")
            for i, part in enumerate(parts):
                emit(part)
                if i < len(parts) - 1:
                    flush(force=True)
        else:
            emit(tail.replace("\n", " "))
    flush()
    # collapse trailing empty paragraphs (every closing tag flushed one)
    while len(paragraphs) > 1 and not paragraphs[-1][1]:
        paragraphs.pop()
    return paragraphs


# =============================================================================
# Control tree
# =============================================================================

class _InertDrawable(GS2Object):
    """Stand-in for an engine drawing surface (`ctrl.icon` / `row.icon`):
    scripts call clearAll()/drawImage()/drawImageRectangle() on it
    (-Serverlist_Chat smilie buttons and channel-menu rows); those are
    engine-canvas calls with no headless equivalent, so every unknown
    member resolves to a no-op callable -- keeping the whole chain on the
    object-exists path instead of logging unknown-method."""

    def get(self, key: str) -> Any:
        v = super().get(key)
        return v if v is not None else (lambda *a: 0.0)

    def has(self, key: str) -> bool:
        return True


class GuiListRow(GS2Object):
    """One addRow() result: text/id members plus an inert `icon` drawing
    surface (scripts do `with (row) { icon.clearAll(); ... }`)."""

    def __init__(self, text: str, row_id: Any):
        super().__init__(name="row")
        self.set("text", text)
        self.set("id", row_id)

    def get(self, key: str) -> Any:
        k = key.lower()
        v = super().get(k)
        if v is None and k not in self._members:
            v = self._members[k] = _InertDrawable(name=f"row.{k}")
        return v

    def has(self, key: str) -> bool:
        # claim everything: `icon` (and friends) must resolve through the
        # with-scope lookup inside `with (row) {...}` blocks
        return True


class GuiControl(GS2Object):
    """Base GS2 GUI control: a script-visible GS2Object (property get/set
    from bytecode) that doubles as a render/hit-test tree node.

    `x`/`y`/`width`/`height`/`text`/`visible`/`profile` are real Python
    attributes (fast, and readable from Python without going through
    GS2Object's dict); any other property a script sets (including
    `onaction`, which ends up holding a Python callable -- see module
    docstring point 2) falls through to the generic member dict.

    Control METHODS (showTop/addRow/...) are exposed as bound callables via
    get(): the VM calls `obj.m(...)` through LValue.get, and -- crucially --
    bare calls inside `with (ctrl) { setIconSize(16,16); }` resolve through
    the VM's with-scope lookup, which only consults `wobj.get(name)`; the
    host's call_builtin never sees the with target, so method names MUST be
    answered here (Login's -Serverlist_Chat builds its whole chat window in
    that style)."""

    CTRL_CLASS = "GuiControl"
    #: profile-definition objects (GuiControlProfile) set this True and are
    #: kept out of the render/hit-test tree by the manager
    is_profile = False

    _NUM_ATTRS = ("x", "y", "width", "height")
    _STR_ATTRS = {"text": "text", "name": "ctrl_name"}
    _EVENT_MEMBERS = {"onaction", "onselect"}
    # Registered Torque property surface. The official runtime's with-scope
    # assignment is EXISTENCE-GATED (verified against the reversed
    # interpreter): a construction-block field like `canmove = true;` only
    # lands on the control because the control CLAIMS the name -- so has()
    # must claim every registered property, or those writes fall through to
    # temps/this. Core GuiControl fields plus every field the live Login
    # server's -Serverlist_Chat construction blocks assign.
    _TORQUE_PROPS = frozenset({
        "position", "extent", "minextent", "clientrelative", "clientextent",
        "horizsizing", "vertsizing", "docking", "style", "active", "modal",
        "helptag", "tooltip", "canmove", "canresize", "destroyonhide",
        "isexternal", "bordercolor", "columncount", "sortorder", "sortmode",
        "groupsortorder", "textprofile", "hscrollbar", "vscrollbar",
        "willfirstrespond", "historysize", "tabcomplete",
        # Login -Rescripted/Serverlist construction fields (taskbar buttons,
        # tree view, tabs) -- existence-gating means unclaimed names fall
        # through to temps, so each must be listed to land on the control.
        "clientwidth", "clientheight", "stylesection", "boxwidth",
        "statuswidth", "fitparentwidth", "columns", "clipcolumntext",
        "wrapcolumntext", "firstlinevisible", "tabwidth", "leveling",
        "canminimize", "canmaximize", "canclose", "tile", "hint",
    })
    _METHOD_NAMES = frozenset({
        "showtop", "show", "hide", "makefirstresponder",
        "seticonsize", "clearrows", "addrow", "sort", "setcolumnoffset",
        "setrowoffset",
        "pushtoback", "clearcontrols", "isactuallyvisible",
        # 2026-07-24 live Login corpus (weapon-*.gs2 under the GS2 compiler's
        # loginserver test scripts): these were the with-scope/method calls
        # the host answered with "unknown method".
        "isfirstresponder", "bringtofront", "settext", "gettext",
        "setlines", "getlines", "clearall",
        "globaltolocalcoord", "localtoglobalcoord",
        # second wave: the deep crawler's client-install weapon fetch
        # (-Serverlist_Chat's log/chat panes, -Serverlist's chat bar)
        "addtext", "scrolltobottom", "openatmouse",
        # third wave (2026-07-24 static census): isEmpty() has no entry in
        # the reference client's binding tables (FourPlay quattroplay/src/gui
        # has none) -- it is a Torque control method the live Login corpus
        # calls on its password field, `if (!PassEdit.isEmpty()) doLogin();`
        # (graal-loginserver weapon-Rescripted_IRC_Login2001.txt:65,
        # weapon-LoginScreen.txt:78). Answering it as "the edit buffer is
        # empty" is both the plain reading and the only one consistent with
        # this client's credential policy: pyReborn never lets a script fill
        # or read a password field, so the field IS empty and the
        # auto-login branch correctly does not fire. Unanswered it returned
        # 0.0, i.e. "not empty", which would have taken that branch.
        "isempty",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(name=self.CTRL_CLASS)
        self.ctrl_name: str = ctor_arg if isinstance(ctor_arg, str) else ""
        self.x = 0.0
        self.y = 0.0
        self.width = 100.0
        self.height = 24.0
        self.text = ""
        self.visible = True
        self.profile_name = _DEFAULT_PROFILE_NAME
        #: `profile = IRC_ScrollProfile;` assigns the registered profile
        #: OBJECT (Torque semantics); kept alongside the name so late field
        #: writes (`with (IRC_ScrollProfile) {...}` after control creation)
        #: are seen at draw time
        self.profile_obj: Optional["GuiControlProfile"] = None
        self.parent: Optional["GuiControl"] = None
        self.children: List["GuiControl"] = []
        # Render-only mouse state, maintained by GS2GuiManager the same way
        # it maintains GuiTextEditCtrl.focused -- not script-visible (not
        # routed through get()/set()).
        self.hovered = False
        self.pressed = False
        # back-reference stamped by GS2GuiManager.create_control -- lets
        # bound methods (showTop) reach z-order/focus state
        self._manager = None
        # The GS2VM whose script constructed this control (stamped at its
        # addcontrol; see GS2GuiManager.addcontrol). Live Login's
        # -Serverlist_Chat wires most control events NOT as member closures
        # but as dotted same-script FUNCTIONS ("GlobalChat_ChatField.
        # onAction", "GlobalChat_ChatTab.onSelect", ... -- all registered in
        # vm.functions under the dotted name); fire_event falls back to
        # those, which a member-only lookup left permanently dead.
        self._owner_vm = None
        # generic list-row model (GuiTextListCtrl/GuiContextMenuCtrl style;
        # distinct from GuiPopUpEditCtrl's own `rows`)
        self.list_rows: List[GuiListRow] = []
        self.icon_w = 0.0
        self.icon_h = 0.0
        # last image painted onto this control's `icon` drawing surface
        # (icon.drawimage/drawimagestretched in construction blocks --
        # taskbar buttons); rendered by GuiButtonCtrl
        self.icon_image = ""

    # -- GS2Object property bridge ------------------------------------------

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in self._NUM_ATTRS:
            return float(getattr(self, k))
        if k == "visible":
            return 1.0 if self.visible else 0.0
        if k == "profile":
            return self.profile_obj if self.profile_obj is not None \
                else self.profile_name
        if k in self._STR_ATTRS:
            return getattr(self, self._STR_ATTRS[k])
        # Torque client-area geometry READS: Login's -Rescripted/Serverlist
        # sizes nearly every child off its parent (`width =
        # Serverlist_Window.clientwidth`, `extent = Serverlist_Panel.extent`,
        # right-aligned taskbar buttons at `clientwidth - width - 25`).
        # These reads previously fell through to the empty member dict ->
        # None -> 0, collapsing the whole layout to zero/negative sizes.
        # These three are DERIVED, never stored: the reference readers hand
        # back m_size (the client size) unconditionally, and the writers
        # resize the outer bounds to suit -- see set() below.
        if k == "clientwidth":
            return float(self.client_width())
        if k == "clientheight":
            return float(self.client_height())
        if k == "clientextent":
            return [float(self.client_width()), float(self.client_height())]
        if k == "extent" and k not in self._members:
            return [float(self.width), float(self.height)]
        if k == "parent" and k not in self._members:
            if self.parent is not None:
                return self.parent
            # a root control's Torque parent is the canvas itself --
            # updateChatBarSize does `ChatBar.parent.clientwidth` on a
            # control added straight to GraalControl; None here read as 0
            # and sized the chat bar to nothing
            return (self._manager.canvas_object()
                    if self._manager is not None else None)
        if k in self._METHOD_NAMES and not super().has(k):
            return getattr(self, "_m_" + k)
        if k == "icon" and k not in self._members:
            # engine drawing surface (`with (button) { icon.drawimage(...) }`)
            # -- records the painted image name into self.icon_image so the
            # renderer can show it (same recorder tree nodes use)
            v = self._members[k] = _TreeNodeIcon(self)
            return v
        # `onAction = function(){...}` stores a VM-bound GS2ScriptFunction in
        # the slot (see module docstring point 2), so a plain member read is
        # all fire_event needs.
        return super().get(k)

    # -- script-callable methods -----------------------------------------

    def _m_showtop(self, *args) -> float:
        """showTop(): make visible and raise to the top of the sibling
        z-order (-Serverlist_Chat openChat: GlobalChat_Window.showtop())."""
        if self._manager is not None:
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    _m_show = _m_showtop

    def _m_isempty(self, *args) -> bool:
        """isEmpty(): True when this control holds no text. See the
        _METHOD_NAMES note for why the polarity matters on Login."""
        return not to_str(self.text)

    def _m_hide(self, *args) -> float:
        if self._manager is not None:
            self._manager.hide(self)
        else:
            self.visible = False
        return 0.0

    def _m_makefirstresponder(self, *args) -> float:
        if self._manager is not None:
            self._manager.focus(self if not args or to_bool(args[0]) else None)
        return 0.0

    def _m_isfirstresponder(self, *args) -> float:
        """isFirstResponder(): does this control hold keyboard focus?
        Login's staff sprite-editor weapon gates its whole key handler on it
        (`if (<zoom edit>.isFirstResponder()) return;`), so a missing answer
        read 0 and the editor swallowed every keystroke."""
        return 1.0 if (self._manager is not None
                       and self._manager._focus is self) else 0.0

    def _m_bringtofront(self, *args) -> float:
        """bringToFront(): raise to the top of the sibling z-order WITHOUT
        touching visibility (showTop does both). Called bare inside
        construction blocks (`with (window) { ...; bringtofront(); }`)."""
        if self._manager is not None:
            self._manager.bring_to_front(self)
        return 0.0

    def _m_settext(self, *args) -> float:
        self.text = to_str(args[0]) if args else ""
        return 0.0

    def _m_gettext(self, *args) -> str:
        return self.text

    def _m_setlines(self, *args) -> float:
        """setLines(array): replace the text with one line per element."""
        lines = args[0] if args else []
        if not isinstance(lines, (list, tuple)):
            lines = [lines]
        self.text = "\n".join(to_str(line) for line in lines)
        return 0.0

    def _m_getlines(self, *args) -> List[str]:
        return self.text.split("\n") if self.text else []

    def _m_addtext(self, *args) -> float:
        """addText(text, [scrollToBottom]): append to a log/chat pane
        (`addtext(msg SPC ... NL "", true)` in Login's F2 log window). The
        optional second argument asks the engine to follow the tail, which
        is scrollToBottom()'s job."""
        self.text += to_str(args[0]) if args else ""
        if len(args) > 1 and to_bool(args[1]):
            self._m_scrolltobottom()
        return 0.0

    def _m_openatmouse(self, *args) -> float:
        """openAtMouse(): show this control with its top-left at the
        pointer -- a context menu (the live -ShopGlobal opens its item menu
        this way). The manager records the pointer in the same
        virtual-canvas space control x/y live in, so no remapping is
        needed; with no pointer seen yet the control opens where it is."""
        if self._manager is not None:
            pos = self._manager.last_mouse
            if pos is not None:
                self.x, self.y = float(pos[0]), float(pos[1])
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    def _m_scrolltobottom(self, *args) -> float:
        """scrollToBottom(): pin the enclosing scroll view to its end --
        what a chat/log pane does after every appended line."""
        node: Optional["GuiControl"] = self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                return 0.0
            if isinstance(node, GuiScrollCtrl):
                node.scroll_y = node.max_scroll_y()
                return 0.0
            node = node.parent
        return 0.0

    def _m_clearall(self, *args) -> float:
        """clearAll(): the engine's "empty this control" verb. On a plain
        control that is its row model (the tree/list subclasses override)."""
        return self._m_clearrows()

    def _m_globaltolocalcoord(self, *args) -> List[float]:
        """globalToLocalCoord({x, y}): canvas coordinates -> this control's
        own coordinate space. Login's staff sprite-editor weapon maps every
        mouse position through it before hit-testing its sprite canvas."""
        x, y = self._coord_arg(args)
        ox, oy = self.effective_offset()
        return [x - (self.x + ox), y - (self.y + oy)]

    def _m_localtoglobalcoord(self, *args) -> List[float]:
        """localToGlobalCoord({x, y}): the inverse -- Login anchors its start
        menu with Serverlist_TaskButton_Start.localtoglobalcoord({0, 0})."""
        x, y = self._coord_arg(args)
        ox, oy = self.effective_offset()
        return [x + self.x + ox, y + self.y + oy]

    @staticmethod
    def _coord_arg(args) -> Tuple[float, float]:
        """A coordinate argument, as either one {x, y} array or two scalars."""
        if len(args) >= 2:
            return to_num(args[0]), to_num(args[1])
        pair = GuiControl._num_pair(args[0]) if args else None
        return pair if pair is not None else (0.0, 0.0)

    def _m_seticonsize(self, *args) -> float:
        if len(args) >= 2:
            self.icon_w, self.icon_h = to_num(args[0]), to_num(args[1])
        return 0.0

    def _m_setcolumnoffset(self, *args) -> float:
        """setColumnOffset(index, offset): the x of column divider `index`.

        Torque's argument order, and the one both live call sites use --
        `setColumnOffset(1, 150)` on a 600-wide two-column frameset
        (Preagonal/gbf/bytecode/login/_Serverlist_Chat.gs2bc.gs2:578, the
        Global Chat window) and `setColumnOffset(1, 210)` on a two-column
        one (_IRC_InstallerGUI.gs2bc.gs2:90). Read the other way round those
        would be "column 150 at offset 1" and "column 210 at offset 1",
        which is nonsense; read this way they are the divider positions the
        layouts obviously want.
        """
        offsets = self._members.setdefault("_column_offsets", {})
        if len(args) >= 2:
            offsets[int(to_num(args[0]))] = to_num(args[1])
        elif args:
            offsets[0] = to_num(args[0])
        return 0.0

    def _m_setrowoffset(self, *args) -> float:
        """setRowOffset(index, offset): the y of row divider `index`.
        Same convention as setColumnOffset; Login's Playerlist splits its PM
        window with `setrowoffset(1, 140)` over a 280-tall two-row frameset
        (Preagonal/gbf/bytecode/login/_Playerlist.gs2bc.gs2:2517-2519)."""
        offsets = self._members.setdefault("_row_offsets", {})
        if len(args) >= 2:
            offsets[int(to_num(args[0]))] = to_num(args[1])
        elif args:
            offsets[0] = to_num(args[0])
        return 0.0

    def _m_clearrows(self, *args) -> float:
        self.list_rows.clear()
        return 0.0

    def _m_addrow(self, *args) -> GuiListRow:
        """addRow(id, text) -> row object (scripts then `with (row) {...}`
        to decorate its icon). Argument order is the Torque one, same as
        GuiPopUpEditCtrl's: every Login call site passes the id first
        (`addRow(11, "Global Chat")`, `addRow(0, "Map")`)."""
        row = GuiListRow(to_str(args[1]) if len(args) > 1 else "",
                         args[0] if args else len(self.list_rows))
        self.list_rows.append(row)
        return row

    def _m_sort(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold())
        return 0.0

    def _m_pushtoback(self, *args) -> float:
        """pushToBack(): send to the back of the sibling z-order (Login's
        Serverlist_MainPanel_Back background bitmap)."""
        siblings = (self.parent.children if self.parent is not None
                    else (self._manager.roots if self._manager else None))
        if siblings and self in siblings:
            siblings.remove(self)
            siblings.insert(0, self)
        return 0.0

    def _m_clearcontrols(self, *args) -> float:
        """clearControls(): remove every child (Login rebuilds its
        Serverlist_TablesPanel0 contents this way on each tab switch).
        Children stay in the name registry -- the rebuild recreates them
        under the same names, which overwrites the entries."""
        for child in list(self.children):
            if self._manager is not None:
                self._manager._release_pointers_under(child)
            self.remove_child(child)
        return 0.0

    def _m_isactuallyvisible(self, *args) -> float:
        """isActuallyVisible(): visible AND every ancestor visible (the
        Torque canvas walk; Login gates its server-map icon refresh on it)."""
        node: Optional["GuiControl"] = self
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                return 1.0
            if not node.visible or id(node) in visited:
                return 0.0
            visited.add(id(node))
            node = node.parent
        return 0.0

    # -- client-area geometry --------------------------------------------

    def client_inset(self) -> Tuple[float, float]:
        """(outer - client) for this control class: the non-client chrome.
        Zero for a plain control, the title bar for a window."""
        return 0.0, 0.0

    def client_width(self) -> float:
        return max(0.0, self.width - self.client_inset()[0])

    def client_height(self) -> float:
        return max(0.0, self.height - self.client_inset()[1])

    @staticmethod
    def _num_pair(value) -> Optional[Tuple[float, float]]:
        """A Torque two-component field value: {a, b} array or "a b" string."""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return to_num(value[0]), to_num(value[1])
        parts = to_str(value).replace(",", " ").split()
        if len(parts) >= 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
        return None

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in self._NUM_ATTRS:
            setattr(self, k, to_num(value))
            return
        if k == "visible":
            self.visible = to_bool(value)
            return
        if k == "profile":
            # accept a profile OBJECT (`profile = IRC_ScrollProfile;` -- the
            # bare reference resolves to the registered GuiControlProfile) or
            # a name string; stringifying the object took its repr and every
            # such control fell back to the default flat style
            if isinstance(value, GuiControlProfile):
                self.profile_obj = value
                self.profile_name = value.ctrl_name or value.name or ""
            else:
                self.profile_obj = None
                self.profile_name = to_str(value)
            return
        if k in self._STR_ATTRS:
            setattr(self, self._STR_ATTRS[k], to_str(value))
            return
        if k in ("clientextent", "clientwidth", "clientheight"):
            # Torque client-area WRITES resize the OUTER bounds so that the
            # CLIENT area ends up the requested size -- the reference is
            #   extent = (bounds.extent - m_size) + clientExtent
            # (propfun_guicontrol_clientextent_w / _clientheight_w, FourPlay
            # quattroplay/src/gui/GuiControlProperties.cpp:115-133). On a
            # plain GuiControl the chrome is 0 and this is a plain extent
            # write; on a GuiWindowCtrl it is the title bar.
            #
            # We used to store the value and treat it AS the outer extent,
            # so `clientextent = {600, 400}` on Global Chat's window
            # (Preagonal/gbf/bytecode/login/_Serverlist_Chat.gs2bc.gs2:566)
            # gave a 600x400 outer window with a 600x378 client area, while
            # the frame set inside it was built 400 tall from the stored
            # value -- its bottom row (chat field + smilie buttons) hung 22px
            # out through the bottom of the window. Nothing is stored now:
            # the reader above recomputes from the live bounds, exactly as
            # propfun_guicontrol_clientextent_r returns m_size.
            pair = self._num_pair(value)
            if k == "clientwidth":
                pair = (to_num(value), self.client_height())
            elif k == "clientheight":
                pair = (self.client_width(), to_num(value))
            if pair is not None:
                inset = self.client_inset()
                self.width, self.height = pair[0] + inset[0], pair[1] + inset[1]
            return
        if k in ("position", "extent"):
            pair = self._num_pair(value)
            if pair is not None:
                if k == "position":
                    self.x, self.y = pair
                else:
                    self.width, self.height = pair
        super().set(k, value)

    def has(self, key: str) -> bool:
        k = key.lower()
        return (k in self._NUM_ATTRS or k == "visible" or k == "icon"
                or k == "profile"
                or k in self._STR_ATTRS or k in self._EVENT_MEMBERS
                or k in self._TORQUE_PROPS or super().has(k))

    def resolve_profile(self) -> GuiProfile:
        """This control's effective style: the referenced profile's
        inheritance chain merged over builtin field data (see the module's
        Profiles section). Recomputed per draw -- profiles are tiny dicts
        and scripts mutate them after creation (`with (IRC_...Profile)`)."""
        ref = self.profile_obj if self.profile_obj is not None \
            else self.profile_name
        mgr = self._manager
        if not ref:
            return _DEFAULT_GUIPROFILE
        return _profile_from_fields(_profile_fields(ref, mgr, set()))

    # -- tree -----------------------------------------------------------

    def add_child(self, child: "GuiControl") -> bool:
        node: Optional["GuiControl"] = self
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            if node is child or id(node) in visited:
                return False
            visited.add(id(node))
            node = node.parent
        else:
            return False
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)
        return True

    def remove_child(self, child: "GuiControl") -> None:
        if child in self.children:
            self.children.remove(child)
        if child.parent is self:
            child.parent = None

    def effective_offset(self) -> Tuple[float, float]:
        """Extra (dx, dy) from ancestor state: parent origins (control x/y
        are PARENT-RELATIVE, Torque semantics -- Login's -Rescripted/
        Serverlist places windows at x=280 whose children sit at x=0, and
        window children at y=-22 relative to the client area to overlay the
        title bar; treating x/y as canvas-absolute clumped every nested
        control at the top-left corner) plus ancestor GuiScrollCtrl scroll
        state, composed across nesting. A GuiWindowCtrl parent whose script
        set `clientrelative = true` additionally offsets its children by its
        title-bar height (their coordinates are relative to the client area
        below the title bar; Login's panels use y = -22 to overlay it)."""
        ox = oy = 0.0
        p = self.parent
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if p is None or id(p) in visited:
                break
            visited.add(id(p))
            ox += p.x
            oy += p.y
            if (isinstance(p, GuiWindowCtrl)
                    and to_bool(p._members.get("clientrelative", 0))):
                oy += p.TITLE_H
            if isinstance(p, GuiScrollCtrl):
                ox -= p.scroll_x
                oy -= p.scroll_y
            p = p.parent
        return ox, oy

    def rect(self) -> pygame.Rect:
        ox, oy = self.effective_offset()
        return pygame.Rect(int(self.x + ox), int(self.y + oy),
                           max(0, int(self.width)), max(0, int(self.height)))

    def fire_event(self, event: str, *args) -> bool:
        """Dispatch a control event: a script-assigned member handler first
        (`onAction = function(){...}` -> a bound vm.call closure, or a
        catchevent binding), then the dotted same-script function the live
        servers actually use ("GlobalChat_ChatField.onAction" et al, keyed
        f"{name}.{event}" in the owning VM's function table). Returns True
        if a handler ran. Handler argument conventions (disasm-verified on
        Login's -Serverlist_Chat; params list reversed = call order):
        onAction(text) for a text field, onSelect(entryid, entrytext,
        entryindex), onDblClick(selectedid, selectedtext, selectedrow)."""
        event = event.lower()
        handler = self.get(event)
        if callable(handler):
            try:
                handler(*args)
            except Exception:
                logger.exception("GS2 GUI: %s handler for %s raised",
                                 event, self.ctrl_name or self.CTRL_CLASS)
            return True
        vm = self._owner_vm
        if vm is not None and self.ctrl_name:
            fname = f"{self.ctrl_name}.{event}".lower()
            try:
                if vm.has_function(fname):
                    vm.call(fname, *args)
                    return True
            except Exception:
                logger.exception("GS2 GUI: %s handler for %s raised",
                                 event, self.ctrl_name)
                return True
        return False

    def fire_action(self, *args) -> bool:
        """fire_event("onaction") -- kept as the manager/host entry point."""
        return self.fire_event("onaction", *args)

    # -- render (subclasses override _draw_self) -------------------------

    def draw(self, surf: pygame.Surface, fonts, sprite_mgr=None) -> None:
        self._draw_self(surf, fonts, sprite_mgr)

    def _skin(self, prof: GuiProfile, sprite_mgr) -> Optional["_Skin"]:
        if self._manager is None:
            return None
        return self._manager.skin(prof.bitmap, sprite_mgr)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        # Plain container semantics (Torque GuiControl): draw NOTHING unless
        # the profile is explicitly `opaque` -- containers used to stack
        # translucent fills over the whole canvas, which is why the login
        # screen's background looked layered navy instead of the level.
        prof = self.resolve_profile()
        r = self.rect()
        if prof.opaque:
            skin = self._skin(prof, sprite_mgr)
            if skin is None or not skin.draw_nine(
                    surf, r, 0, int(255 * prof.transparency)):
                _fill_rect(surf, prof.bg if prof.bg is not None
                           else prof.title_bg, r)
                if prof.border_width:
                    _fill_rect(surf, prof.border, r, prof.border_width)
        if self.text and fonts is not None:
            _draw_label(surf, _font(fonts, prof), self.text, prof.fg,
                        (r.x + 4, r.y + 4), prof.text_shadow)


class GuiWindowCtrl(GuiControl):
    """Frame + title bar + draggable (drag handled by GS2GuiManager).

    TITLE_H is 22 per the Login scripts' own layout math: every panel is
    placed at y = -22 relative to the client area precisely to overlay the
    title bar (Serverlist_DescriptionPanel/TablesPanel), so a different
    title height shifts the whole pane contents."""

    CTRL_CLASS = "GuiWindowCtrl"
    TITLE_H = 22

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 240.0, 160.0

    def titlebar_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x, r.y, r.width, min(self.TITLE_H, r.height))

    def client_inset(self) -> Tuple[float, float]:
        # the client area children are laid out in starts below the title bar
        return 0.0, float(self.TITLE_H)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        tb = self.titlebar_rect()
        skin = self._skin(prof, sprite_mgr)
        alpha = int(255 * prof.transparency)
        drew_frame = False
        if skin is not None and skin.looks_like_window_sheet():
            # client area first: the full window sheet carries a tiled
            # background cell (guiblue_window.png -- IRC_WindowRedProfile's
            # red fillcolor is never seen in the official look); the
            # *_noback sheets have none, there the translucent blue
            # fillcolor IS the background. Then the sliced title bar +
            # frame art on top.
            client = pygame.Rect(r.x, r.y + tb.height, r.width,
                                 max(0, r.height - tb.height))
            if not skin.draw_window_background(surf, client, alpha):
                _fill_rect(surf, prof.bg, client)
            drew_frame = skin.draw_window_frame(surf, r, alpha)
        if not drew_frame:
            _fill_rect(surf, prof.bg, r)
            if prof.border_width:
                _fill_rect(surf, prof.border, r, prof.border_width)
            _fill_rect(surf, prof.title_bg, tb)
        if self.text and fonts is not None:
            font = _font(fonts, prof)
            label_w = font.size(self.text)[0]
            if prof.align == "right":
                lx = tb.right - label_w - 8
            elif prof.align == "center":
                lx = tb.centerx - label_w // 2
            else:
                lx = tb.x + 8
            label_h = font.get_height()
            _draw_label(surf, font, self.text, prof.title_fg,
                        (lx, tb.y + (tb.height - label_h) // 2),
                        prof.text_shadow or drew_frame)


class GuiButtonCtrl(GuiControl):
    """Rect + text (aligned per profile) + optional icon; onAction fires on
    click (GS2GuiManager). Skin sheets (guiblue_button.png) carry four
    9-patch state groups in order normal/hilight/pressed/inactive."""

    CTRL_CLASS = "GuiButtonCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 24.0

    def _label_text(self) -> str:
        if self.text:
            return self.text
        # The taskbar start button has no script-side text -- the official
        # client paints it from the window-style skin. Use the start menu's
        # own title as the label so it isn't an anonymous slab.
        if (to_str(self._members.get("stylesection", "")).lower()
                == "taskbar.startbutton" and self._manager is not None):
            menu = next((c for c in self._manager.roots
                         if isinstance(c, GuiStartMenuCtrl)), None)
            if menu is not None and menu.text:
                return menu.text
            return "Start"
        return ""

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        state_row = 6 if self.pressed else (3 if self.hovered else 0)
        drew = False
        if skin is not None:
            drew = skin.draw_nine(surf, r, state_row,
                                  int(255 * prof.transparency))
            if not drew and state_row:
                drew = skin.draw_nine(surf, r, 0,
                                      int(255 * prof.transparency))
        if not drew:
            fill = prof.bg if prof.bg is not None else prof.title_bg
            if self.pressed:
                fill = _shade(fill, 0.75)
            elif self.hovered:
                fill = _shade(fill, 1.2)
            _fill_rect(surf, fill, r, border_radius=4)
            if prof.border_width:
                _fill_rect(surf, prof.border, r, prof.border_width,
                           border_radius=4)
        # optional icon (icon.drawimagestretched from the construction
        # block -- the taskbar's server buttons)
        tx = r.x + 8
        if self.icon_image and sprite_mgr is not None:
            img = sprite_mgr.load_sheet(self.icon_image)
            if img is None and self._manager is not None:
                self._manager.request_image(self.icon_image)
            if img is not None:
                iw = int(self.icon_w) or 24
                ih = int(self.icon_h) or 24
                if img.get_size() != (iw, ih):
                    img = pygame.transform.smoothscale(img, (iw, ih))
                surf.blit(img, (tx, r.centery - ih // 2))
                tx += iw + 4
        text = self._label_text()
        if text and fonts is not None:
            font = _font(fonts, prof)
            tw = font.size(text)[0]
            if prof.align == "left":
                lx = tx
            elif prof.align == "right":
                lx = r.right - tw - 8
            else:
                lx = max(tx, r.centerx - tw // 2)
            _draw_label(surf, font, text, prof.fg,
                        (lx, r.centery - font.get_height() // 2),
                        prof.text_shadow)


class GuiTextCtrl(GuiControl):
    """A plain (non-interactive) text label."""

    CTRL_CLASS = "GuiTextCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 16.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = self.resolve_profile()
        r = self.rect()
        font = _font(fonts, prof)
        tw = font.size(self.text)[0]
        if prof.align == "right":
            lx = r.right - tw
        elif prof.align == "center":
            lx = r.centerx - tw // 2
        else:
            lx = r.x
        _draw_label(surf, font, self.text, prof.fg, (lx, r.y),
                    prof.text_shadow)


class GuiMLTextCtrl(GuiControl):
    """Multi-line Torque-ML text: minimal markup handling (see
    parse_mltext) with word-wrap and inline bold/italic/size/color runs.
    Height auto-grows to the laid-out content (Torque MLText autosizes;
    the script-set height of 10-14px is just a seed) so an enclosing
    GuiScrollCtrl clips/scrolls it instead of the text vanishing."""

    CTRL_CLASS = "GuiMLTextCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 80.0
        self._ml_cache_key = None
        self._ml_paragraphs = None

    def _paragraphs(self):
        if self._ml_cache_key != self.text:
            self._ml_cache_key = self.text
            try:
                self._ml_paragraphs = parse_mltext(self.text)
            except Exception:
                logger.exception("GS2 GUI: mltext parse failed")
                self._ml_paragraphs = [("left", [_MLSegment(
                    self.text, False, False, None, None, False)])]
        return self._ml_paragraphs

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = self.resolve_profile()
        r = self.rect()
        base_font = _font(fonts, prof)
        max_w = max(20, r.width)
        y = r.y
        at = getattr(fonts, "at", None)

        def seg_font(seg):
            if at is None:
                return base_font
            size = seg.size if seg.size else prof.font_size
            try:
                return at(size, seg.bold or prof.font_bold, seg.italic)
            except TypeError:       # older fonts objects: at(size, bold)
                return at(size, seg.bold or prof.font_bold)

        for align, segments in self._paragraphs():
            # split segments into word chunks that carry their style
            words: List[Tuple[str, Any]] = []
            for seg in segments:
                for piece in seg.text.split(" "):
                    if piece:
                        words.append((piece, seg))
            if not words:
                y += base_font.get_height()
                continue
            # greedy wrap
            lines: List[List[Tuple[str, Any]]] = [[]]
            line_w = 0
            for word, seg in words:
                font = seg_font(seg)
                w = font.size(word + " ")[0]
                if lines[-1] and line_w + w > max_w:
                    lines.append([])
                    line_w = 0
                lines[-1].append((word, seg))
                line_w += w
            for line in lines:
                line_h = max(seg_font(seg).get_height()
                             for _w, seg in line)
                total_w = sum(seg_font(seg).size(word + " ")[0]
                              for word, seg in line)
                if align == "center":
                    x = r.x + max(0, (r.width - total_w) // 2)
                elif align == "right":
                    x = r.x + max(0, r.width - total_w)
                else:
                    x = r.x
                for word, seg in line:
                    font = seg_font(seg)
                    color = seg.color if seg.color is not None else prof.fg
                    label = _draw_label(
                        surf, font, word, color,
                        (x, y + line_h - font.get_height()),
                        prof.text_shadow)
                    if seg.link:
                        pygame.draw.line(
                            surf, color, (x, y + line_h - 2),
                            (x + label.get_width(), y + line_h - 2))
                    x += font.size(word + " ")[0]
                y += line_h
        # autosize so ancestor scroll controls know the content extent
        self.height = max(self.height, float(y - r.y))


class GuiScrollCtrl(GuiControl):
    """Clips its children to its own rect and offsets them by
    scroll_x/scroll_y (adjusted by mouse wheel -- GS2GuiManager). Draws a
    skinned vertical scrollbar (guiblue_scroll.png: row0 = up/down arrow
    states, rows1-4 = thumb top/mid/bottom + track) when the content
    overflows and the profile's vscrollbar mode allows it."""

    CTRL_CLASS = "GuiScrollCtrl"
    SCROLLBAR_W = 17

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 120.0
        self.scroll_x = 0.0
        self.scroll_y = 0.0

    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({"scrolldelta"})

    def content_height(self) -> float:
        bottom = 0.0
        for c in self.children:
            if c.visible:
                bottom = max(bottom, c.y + c.height)
        return bottom

    def max_scroll_y(self) -> float:
        return max(0.0, self.content_height() - self.height)

    def _m_scrolldelta(self, *args) -> float:
        """scrollDelta(dx, dy): scroll BY the given amount (the wheel path
        does the same clamp; Login Mobile's gui_scroll class drives its
        touch-drag scrolling through it)."""
        dx, dy = self._coord_arg(args)
        self.scroll_x = max(0.0, self.scroll_x + dx)
        self.scroll_y = max(0.0, min(self.scroll_y + dy, self.max_scroll_y()))
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg, r)
        if prof.border_width:
            _fill_rect(surf, prof.border, r, prof.border_width)
        # vertical scrollbar on overflow
        vmode = to_str(self._members.get("vscrollbar", "dynamic")).lower()
        max_scroll = self.max_scroll_y()
        if vmode == "alwaysoff" or max_scroll <= 0 or r.height < 40:
            return
        self.scroll_y = max(0.0, min(self.scroll_y, max_scroll))
        bw = self.SCROLLBAR_W
        bar = pygame.Rect(r.right - bw, r.y, bw, r.height)
        track = pygame.Rect(bar.x, bar.y + bw, bw, max(0, bar.height - 2 * bw))
        frac = r.height / max(1.0, self.content_height())
        thumb_h = max(20, int(track.height * frac))
        thumb_y = track.y + int((track.height - thumb_h) *
                                (self.scroll_y / max_scroll))
        skin = self._skin(prof, sprite_mgr)
        if skin is not None and len(skin.rows) >= 5 and len(skin.rows[0]) >= 5:
            alpha = int(255 * prof.transparency)
            skin.blit_scaled(surf, skin.rows[0][1],
                             pygame.Rect(bar.x, bar.y, bw, bw), alpha)
            skin.blit_scaled(surf, skin.rows[0][4],
                             pygame.Rect(bar.x, bar.bottom - bw, bw, bw), alpha)
            if len(skin.rows[4]) >= 2:
                skin.blit_scaled(surf, skin.rows[4][1], track, alpha)
            cap = min(6, thumb_h // 3)
            if len(skin.rows[1]) >= 2 and len(skin.rows[2]) >= 2 \
                    and len(skin.rows[3]) >= 2:
                skin.blit_scaled(surf, skin.rows[1][1],
                                 pygame.Rect(bar.x, thumb_y, bw, cap), alpha)
                skin.blit_scaled(surf, skin.rows[2][1],
                                 pygame.Rect(bar.x, thumb_y + cap, bw,
                                             thumb_h - 2 * cap), alpha)
                skin.blit_scaled(surf, skin.rows[3][1],
                                 pygame.Rect(bar.x, thumb_y + thumb_h - cap,
                                             bw, cap), alpha)
            return
        # solid fallback
        _fill_rect(surf, (16, 32, 80, 200), bar)
        _fill_rect(surf, _BLUE_FILL,
                   pygame.Rect(bar.x + 2, thumb_y, bw - 4, thumb_h),
                   border_radius=4)


class GuiTextEditCtrl(GuiControl):
    """Single-line editable text field. Enter fires onAction (GS2GuiManager
    routes focus + key/Enter handling; `.text` is the live edit buffer)."""

    CTRL_CLASS = "GuiTextEditCtrl"
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselection", "getselection"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 22.0
        self.focused = False
        self.max_len = 256
        #: [start, end] character range, empty when start == end. Login's
        #: chat bar recalls a message and then selects all of it
        #: (`ChatBar.setSelection(0, ChatBar.text.length())`) precisely so
        #: the next keystroke REPLACES it -- see take_selection().
        self.selection: Tuple[int, int] = (0, 0)

    def _m_setselection(self, *args) -> float:
        start = int(to_num(args[0])) if args else 0
        end = int(to_num(args[1])) if len(args) > 1 else start
        limit = len(self.text)
        start = max(0, min(start, limit))
        end = max(0, min(end, limit))
        self.selection = (min(start, end), max(start, end))
        return 0.0

    def _m_getselection(self, *args) -> List[float]:
        return [float(self.selection[0]), float(self.selection[1])]

    def take_selection(self) -> bool:
        """Consume a pending selection by deleting the selected characters.
        Returns whether anything was removed (the caller then inserts)."""
        start, end = self.selection
        self.selection = (0, 0)
        if start >= end or end > len(self.text):
            return False
        self.text = self.text[:start] + self.text[end:]
        return True

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        if skin is None or not skin.draw_nine(surf, r, 0,
                                              int(255 * prof.transparency)):
            _fill_rect(surf, prof.bg if prof.bg is not None
                       else prof.title_bg, r)
            pygame.draw.rect(surf,
                             (150, 190, 255) if self.focused else prof.border,
                             r, 2 if self.focused else 1)
        elif self.focused:
            pygame.draw.rect(surf, (150, 190, 255), r, 1)
        if fonts is None:
            return
        font = _font(fonts, prof)
        label = font.render(self.text, True, prof.fg)
        surf.blit(label, (r.x + 4, r.centery - label.get_height() // 2))
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = r.x + 4 + font.size(self.text)[0]
            pygame.draw.line(surf, prof.fg, (cx, r.y + 3), (cx, r.bottom - 3), 1)


class GuiAccountPasswordCtrl(GuiTextEditCtrl):
    """The Login screen's password field (gr_LoginScreen_PassEdit). Same
    edit control, rendered masked -- the reference client never echoes the
    characters, and neither should a client whose credential surface is
    deliberately inert (see GS2ClientHost.stubbed)."""

    CTRL_CLASS = "GuiAccountPasswordCtrl"

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        shown, self.text = self.text, "*" * len(self.text)
        try:
            super()._draw_self(surf, fonts, sprite_mgr)
        finally:
            self.text = shown


class GuiMLTextEditCtrl(GuiMLTextCtrl):
    """Editable multi-line text pane (Staff's script editor). Rendered with
    GuiMLTextCtrl's markup pipeline; setLines/getLines (GuiControl) are the
    surface the scripts actually drive it through, and focus/typing route
    through GS2GuiManager exactly as for GuiTextEditCtrl."""

    CTRL_CLASS = "GuiMLTextEditCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.focused = False
        self.max_len = 65536


class GuiProgressCtrl(GuiControl):
    """Horizontal progress bar. `progress` is 0..1 (Login's IRC_Installer
    drives three of them off the update-package byte counts); the label, if
    any, is a child GuiTextCtrl, so this control only paints the bar."""

    CTRL_CLASS = "GuiProgressCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({"progress"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 20.0
        self.progress = 0.0

    def get(self, key: str) -> Any:
        if key.lower() == "progress":
            return float(self.progress)
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "progress":
            self.progress = max(0.0, min(1.0, to_num(value)))
            return
        super().set(key, value)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg if prof.bg is not None else prof.title_bg, r)
        filled = int(r.width * self.progress)
        if filled > 0:
            _fill_rect(surf, prof.title_bg,
                       pygame.Rect(r.x, r.y, filled, r.height))
        pygame.draw.rect(surf, prof.border[:3], r, 1)


class GuiCheckBoxCtrl(GuiControl):
    """Stub-but-track: rendered as a small button with a checked state.
    `value`/`checked` alias to the same boolean (real client scripts use
    either name)."""

    CTRL_CLASS = "GuiCheckBoxCtrl"
    _BOOL_KEYS = ("value", "checked")
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset(_BOOL_KEYS)

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 16.0, 16.0
        self.checked = False

    def get(self, key: str) -> Any:
        if key.lower() in self._BOOL_KEYS:
            return 1.0 if self.checked else 0.0
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() in self._BOOL_KEYS:
            self.checked = to_bool(value)
            return
        super().set(key, value)

    def toggle(self) -> None:
        self.checked = not self.checked

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        box = pygame.Rect(r.x, r.y, min(r.width, r.height) or 16, min(r.width, r.height) or 16)
        base = (prof.bg if prof.bg is not None else prof.title_bg)[:3]
        bg = _shade(base, 0.75) if self.pressed else base
        border = (150, 190, 255) if self.hovered else prof.border
        pygame.draw.rect(surf, bg, box)
        pygame.draw.rect(surf, border, box, 1)
        if self.checked:
            pygame.draw.line(surf, prof.fg, box.topleft, box.bottomright, 2)
            pygame.draw.line(surf, prof.fg, box.bottomleft, box.topright, 2)
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (box.right + 6, box.y + (box.height - label.get_height()) // 2))


class GuiRadioCtrl(GuiCheckBoxCtrl):
    """Same as GuiCheckBoxCtrl visually (a filled circle instead of a box).
    Per-group mutual-exclusion is handled by GS2GuiManager._select_radio:
    clicking a radio checks it and unchecks its siblings (the children of
    its immediate parent container -- there is no separate group-name
    property on the wire, matching the C# client's reference semantics)."""

    CTRL_CLASS = "GuiRadioCtrl"

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        d = min(r.width, r.height) or 16
        center = (r.x + d // 2, r.y + d // 2)
        base = (prof.bg if prof.bg is not None else prof.title_bg)[:3]
        bg = _shade(base, 0.75) if self.pressed else base
        border = (150, 190, 255) if self.hovered else prof.border
        pygame.draw.circle(surf, bg, center, d // 2)
        pygame.draw.circle(surf, border[:3], center, d // 2, 1)
        if self.checked:
            pygame.draw.circle(surf, prof.fg, center, max(1, d // 4))
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (r.x + d + 6, r.y + (d - label.get_height()) // 2))


class GuiBitmapCtrl(GuiControl):
    """Renders an image (by filename, resolved via the game's SpriteManager)
    stretched to fit the control's rect."""

    CTRL_CLASS = "GuiBitmapCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({"bitmap", "image"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.bitmap = ""
        self._scaled_cache: Optional[Tuple[str, Tuple[int, int]]] = None
        self._scaled_surf: Optional[pygame.Surface] = None

    def get(self, key: str) -> Any:
        if key.lower() in ("bitmap", "image"):
            return self.bitmap
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() in ("bitmap", "image"):
            self.bitmap = to_str(value)
            return
        super().set(key, value)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        r = self.rect()
        img = sprite_mgr.load_sheet(self.bitmap) if (sprite_mgr and self.bitmap) else None
        if img is not None:
            key = (self.bitmap, r.size)
            if self._scaled_cache != key:
                self._scaled_surf = (img if img.get_size() == r.size
                                     else pygame.transform.smoothscale(img, r.size))
                self._scaled_cache = key
            surf.blit(self._scaled_surf, r.topleft)
            return
        # not cached yet: fetch via the normal file-request path and draw
        # nothing meanwhile (the official client draws no placeholder --
        # scripts probe getimgwidth() themselves)
        if self.bitmap and self._manager is not None:
            self._manager.request_image(self.bitmap)


class GuiShowImgCtrl(GuiBitmapCtrl):
    """Same image control as GuiBitmapCtrl (filename via the `bitmap`/`image`
    property, resolved through the game's SpriteManager and stretched to
    fit, cached by (bitmap-name, rect-size) -- see GuiBitmapCtrl). Some GS2
    scripts spell this control's class name one way, some the other; the
    C# client renders both identically, so this subclass only changes
    CTRL_CLASS and reuses GuiBitmapCtrl's get/set/_draw_self as-is."""

    CTRL_CLASS = "GuiShowImgCtrl"


class GuiBitmapButtonCtrl(GuiButtonCtrl):
    """A button whose face is a bitmap (Login Mobile's Rescripted/IRC/
    Login2001 builds its on-screen keys this way). Clicking behaves exactly
    like GuiButtonCtrl -- only the face differs, so the profile skin/label
    path is replaced by the `bitmap` image and the text is drawn over it."""

    CTRL_CLASS = "GuiBitmapButtonCtrl"
    _TORQUE_PROPS = GuiButtonCtrl._TORQUE_PROPS | frozenset({"bitmap", "image"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.bitmap = ""

    def get(self, key: str) -> Any:
        if key.lower() in ("bitmap", "image"):
            return self.bitmap
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() in ("bitmap", "image"):
            self.bitmap = to_str(value)
            return
        super().set(key, value)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        r = self.rect()
        img = (sprite_mgr.load_sheet(self.bitmap)
               if (sprite_mgr is not None and self.bitmap) else None)
        if img is None:
            if self.bitmap and self._manager is not None:
                self._manager.request_image(self.bitmap)
            super()._draw_self(surf, fonts, sprite_mgr)
            return
        if img.get_size() != r.size:
            img = pygame.transform.smoothscale(img, r.size)
        surf.blit(img, r.topleft)
        if self.text and fonts is not None:
            prof = self.resolve_profile()
            font = _font(fonts, prof)
            width = font.size(self.text)[0]
            _draw_label(surf, font, self.text, prof.fg,
                        (r.centerx - width // 2,
                         r.centery - font.get_height() // 2),
                        prof.text_shadow)


class GuiPopUpEditCtrl(GuiControl):
    """Single-selection combo box with a manager-rendered popup list."""

    CTRL_CLASS = "GuiPopUpEditCtrl"
    # getSelectedRow/getSelectedText also reach this control by METHOD form
    # (call_builtin's obj branch), but with-scope bare calls only consult
    # get(), so they must be declared here too.
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"getselectedrow", "getselectedtext", "setselectedrow",
         "setselectedbyid", "getrowtext", "clear",
         "setselected", "findtext"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 22.0
        self.rows: List[Tuple[Any, str]] = []
        self.selected_row = -1
        self.popup_open = False
        self.hover_row = -1

    def add_row(self, row_id: Any, text: Any) -> float:
        self.rows.append((row_id, to_str(text)))
        return float(len(self.rows) - 1)

    # popup rows are (id, text) pairs with their own draw path -- keep the
    # base class's generic list-row methods from shadowing them
    def _m_addrow(self, *args):
        return self.add_row(args[0] if args else None,
                            args[1] if len(args) > 1 else "")

    def _m_clearrows(self, *args):
        return self.clear_rows()

    def clear_rows(self) -> float:
        self.rows.clear()
        self.selected_row = -1
        self.text = ""
        self.popup_open = False
        self.hover_row = -1
        return 0.0

    def get_selected_row(self) -> Any:
        if 0 <= self.selected_row < len(self.rows):
            return self.rows[self.selected_row][0]
        return -1.0

    def _m_getselectedrow(self, *args) -> Any:
        return self.get_selected_row()

    def _m_clear(self, *args) -> float:
        return self.clear_rows()

    def _m_getselectedtext(self, *args) -> str:
        """getSelectedText(): the selected row's LABEL (Login's staff
        sprite-editor weapon reads its batch-mode combo that way)."""
        if 0 <= self.selected_row < len(self.rows):
            return self.rows[self.selected_row][1]
        return ""

    def _m_getrowtext(self, *args) -> str:
        return self.get_row_text(args[0] if args else None)

    def _m_setselectedrow(self, *args) -> float:
        if args:
            self.select_row(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        if args:
            wanted = to_str(args[0])
            for index, (row_id, _text) in enumerate(self.rows):
                if to_str(row_id) == wanted:
                    self.select_row(index)
                    break
        return 0.0

    #: setSelected(id) is the reference spelling of setSelectedById: the
    #: engine's GuiPopUpMenuCtrl::setSelected resolves its argument with
    #: findEntryById, NOT as a row index (FourPlay quattroplay/src/gui/
    #: GuiPopUpMenuCtrl.cpp:316-327; binding GuiPopUpMenuCtrlProperties.cpp:74
    #: `{"setselected", false, 'v', "i"}`). Live sites construct the combo and
    #: call it in the same with-block (era weaponGraalNet.txt:106,
    #: pdamod_browser.txt:60), where row ids and indices happen to coincide.
    _m_setselected = _m_setselectedbyid

    def _m_findtext(self, *args) -> float:
        """findText(text) -> the matching row's INDEX, or -1.

        Reference: GuiPopUpMenuCtrlProperties.cpp:69 `{'i', "s"}` ->
        GuiTextListCtrl::findEntryByText, which returns the ARRAY POSITION
        (FourPlay quattroplay/src/gui/GuiTextListCtrl.cpp:747-758) -- not the
        row id, and -1 when nothing matches."""
        wanted = to_str(args[0]) if args else ""
        for index, (_row_id, text) in enumerate(self.rows):
            if to_str(text) == wanted:
                return float(index)
        return -1.0

    def get_row_text(self, row_id: Any) -> str:
        for item_id, text in self.rows:
            if item_id == row_id or to_str(item_id) == to_str(row_id):
                return text
        return ""

    def select_row(self, index: int) -> bool:
        if not 0 <= index < len(self.rows) or index == self.selected_row:
            return False
        self.selected_row = index
        row_id, self.text = self.rows[index]
        # (entryid, entrytext, entryindex) per the reference convention --
        # member closures that only declare (id, text) simply never bind the
        # extra index argument.
        self.fire_event("onselect", row_id, self.text, float(index))
        self.fire_action()
        return True

    def popup_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x, r.bottom, r.width, int(self.height) * len(self.rows))

    def popup_row_at(self, pos) -> int:
        pr = self.popup_rect()
        if not pr.collidepoint(pos) or not self.rows:
            return -1
        return min(len(self.rows) - 1,
                   (pos[1] - pr.y) // max(1, int(self.height)))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        fill = prof.bg if prof.bg is not None else prof.title_bg
        if self.pressed:
            fill = _shade(fill, 0.75)
        elif self.hovered:
            fill = _shade(fill, 1.2)
        _fill_rect(surf, fill, r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)
        arrow_w = min(r.height, 20)
        arrow = pygame.Rect(r.right - arrow_w, r.y, arrow_w, r.height)
        pygame.draw.line(surf, prof.border[:3], arrow.topleft, arrow.bottomleft, 1)
        cx, cy = arrow.center
        pygame.draw.polygon(surf, prof.fg,
                            [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 3)])
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (r.x + 4, r.centery - label.get_height() // 2))

    def draw_popup(self, surf, fonts) -> None:
        if not self.popup_open or not self.rows:
            return
        prof = self.resolve_profile()
        pr = self.popup_rect()
        row_h = max(1, int(self.height))
        _fill_rect(surf, prof.bg if prof.bg is not None else (16, 32, 96, 240), pr)
        for index, (_row_id, text) in enumerate(self.rows):
            rr = pygame.Rect(pr.x, pr.y + index * row_h, pr.width, row_h)
            if index == self.hover_row:
                _fill_rect(surf, _shade(prof.title_bg, 1.2), rr)
            if fonts is not None:
                label = _font(fonts, prof).render(text, True, prof.fg)
                surf.blit(label, (rr.x + 4, rr.centery - label.get_height() // 2))
        pygame.draw.rect(surf, prof.border[:3], pr, 1)


class GuiPopUpMenuCtrl(GuiPopUpEditCtrl):
    """The non-editable spelling of the same combo box. Login's staff
    sprite-editor weapon builds every one of its selectors as
    GuiPopUpMenuCtrl and then calls getSelectedRow()/getSelectedText() on
    them -- as an unknown class they fell back to a plain GuiControl, which
    answered neither (45 misses in the 2026-07-24 corpus run, the
    second-largest gap after gettextheight)."""

    CTRL_CLASS = "GuiPopUpMenuCtrl"


class GuiFrameSetCtrl(GuiControl):
    """A splitter: divides its own client area into `rowcount` x
    `columncount` cells and gives each child ONE cell, in the order the
    children were added (row-major).

    Divider positions come from setRowOffset(i, y) / setColumnOffset(i, x);
    dividers 0 and `count` are implicit (0 and the frameset's own extent),
    and a divider nobody set falls back to an even split. The Global Chat
    window is one row by two columns with `setColumnOffset(1, 150)` over a
    600x400 client area (Preagonal/gbf/bytecode/login/
    _Serverlist_Chat.gs2bc.gs2:570-616), i.e. a 150-wide channel list beside
    a 450-wide chat panel.

    Sizing HAS to happen when a child is added, not at render time: the
    scripts build a cell's contents in a following `with (<cell>) {...}`
    block that reads `<cell>.clientwidth`/`.clientheight` to size them
    (:617-660). Unimplemented, the class fell back to a generic GuiControl,
    both cells kept their constructor defaults stacked at (0,0) -- a 160x120
    channel scroll drawn OVER a 100x24 chat panel -- and the chat panel's
    placeholder text wrapped into a ~150px strip clipped at the bottom,
    which is exactly the reported symptom.
    """

    CTRL_CLASS = "GuiFrameSetCtrl"

    def _cell_bounds(self, count: int, span: float, key: str) -> List[float]:
        """The `count`+1 divider positions along one axis."""
        count = max(1, count)
        given = self._members.get(key) or {}
        out = [0.0]
        for i in range(1, count):
            v = given.get(i)
            out.append(to_num(v) if v is not None else span * i / count)
        out.append(span)
        # dividers must stay ordered and inside the frame
        for i in range(1, len(out)):
            out[i] = max(out[i - 1], min(out[i], span))
        return out

    def relayout(self) -> None:
        rows = max(1, int(to_num(self._members.get("rowcount") or 1)))
        cols = max(1, int(to_num(self._members.get("columncount") or 1)))
        ys = self._cell_bounds(rows, float(self.client_height()), "_row_offsets")
        xs = self._cell_bounds(cols, float(self.client_width()), "_column_offsets")
        for index, child in enumerate(self.children):
            if child.is_profile:
                continue
            r, c = divmod(index, cols)
            if r >= rows:
                break               # more children than cells: leave as-is
            child.x, child.y = xs[c], ys[r]
            child.width = max(0.0, xs[c + 1] - xs[c])
            child.height = max(0.0, ys[r + 1] - ys[r])

    def add_child(self, child: "GuiControl") -> bool:
        added = super().add_child(child)
        if added:
            self.relayout()
        return added

    def set(self, key: str, value: Any) -> None:
        super().set(key, value)
        if key.lower() in ("rowcount", "columncount", "extent", "clientextent",
                           "width", "height"):
            self.relayout()

    def _m_setcolumnoffset(self, *args) -> float:
        rv = super()._m_setcolumnoffset(*args)
        self.relayout()
        return rv

    def _m_setrowoffset(self, *args) -> float:
        rv = super()._m_setrowoffset(*args)
        self.relayout()
        return rv


class GuiContextMenuCtrl(GuiPopUpEditCtrl):
    """A right-click menu: a row list that is HIDDEN until openAtMouse().

    `m_visible = false` in the constructor (FourPlay quattroplay/src/gui/
    GuiContextMenuCtrl.cpp:35-46, GuiContextMenuCtrl::initObject) -- as an
    unknown class it fell back to a generic, VISIBLE GuiControl, so Global
    Chat's channel menu (`new GuiContextMenuCtrl("GlobalChat_ChannelMenu")`,
    width 120, three rows, Preagonal/gbf/bytecode/login/
    _Serverlist_Chat.gs2bc.gs2:697-717) drew as a stray filled rectangle at
    the canvas origin, on top of the server-list window."""

    CTRL_CLASS = "GuiContextMenuCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.visible = False
        self.width, self.height = 120.0, 22.0


class GuiDrawingPanel(GuiControl):
    """A script-driven canvas: `with (panel) { clearall(); drawline(...); }`.
    The draw calls are RECORDED (they are issued once, outside the render
    loop, and must persist across frames) and replayed every frame in the
    control's own coordinate space. Login's staff sprite-editor weapon
    draws its guidelines and sprite sheet this way."""

    CTRL_CLASS = "GuiDrawingPanel"
    _MAX_OPS = 4096          # a runaway script must not grow this forever

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.draw_ops: List[Tuple] = []

    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"drawline", "drawrect", "drawimage", "drawimagestretched",
         "drawimagerectangle"})

    def _record(self, op: Tuple) -> float:
        if len(self.draw_ops) < self._MAX_OPS:
            self.draw_ops.append(op)
        return 0.0

    def _m_clearall(self, *args) -> float:
        self.draw_ops.clear()
        return 0.0

    def _m_drawline(self, *args) -> float:
        """drawLine(x1, y1, x2, y2, thickness)."""
        values = [to_num(a) for a in args[:5]]
        while len(values) < 5:
            values.append(1.0)
        return self._record(("line", *values))

    def _m_drawrect(self, *args) -> float:
        values = [to_num(a) for a in args[:4]]
        while len(values) < 4:
            values.append(0.0)
        return self._record(("rect", *values))

    def _m_drawimage(self, *args) -> float:
        """drawImage(x, y, image)."""
        if len(args) < 3:
            return 0.0
        return self._record(("image", to_num(args[0]), to_num(args[1]),
                             to_str(args[2]), 0.0, 0.0))

    def _m_drawimagestretched(self, *args) -> float:
        """drawImageStretched(x, y, w, h, image, ...)."""
        if len(args) < 5:
            return 0.0
        return self._record(("image", to_num(args[0]), to_num(args[1]),
                             to_str(args[4]), to_num(args[2]),
                             to_num(args[3])))

    def _m_drawimagerectangle(self, *args) -> float:
        """drawImageRectangle(x, y, image, partx, party, partw, parth):
        blit ONE sub-rectangle of a sheet (the sprite editor's sheet view
        and the chat window's smilie strip both slice art this way)."""
        if len(args) < 7:
            return 0.0
        return self._record(("imagepart", to_num(args[0]), to_num(args[1]),
                             to_str(args[2]),
                             tuple(to_num(a) for a in args[3:7])))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        super()._draw_self(surf, fonts, sprite_mgr)
        prof = self.resolve_profile()
        r = self.rect()
        for op in self.draw_ops:
            if op[0] == "line":
                _, x1, y1, x2, y2, thickness = op
                pygame.draw.line(surf, prof.fg[:3],
                                 (r.x + int(x1), r.y + int(y1)),
                                 (r.x + int(x2), r.y + int(y2)),
                                 max(1, int(thickness)))
            elif op[0] == "rect":
                _, x, y, w, h = op
                pygame.draw.rect(surf, prof.fg[:3],
                                 pygame.Rect(r.x + int(x), r.y + int(y),
                                             max(0, int(w)), max(0, int(h))), 1)
            elif op[0] in ("image", "imagepart"):
                name = op[3]
                img = (sprite_mgr.load_sheet(name)
                       if (sprite_mgr is not None and name) else None)
                if img is None:
                    if name and self._manager is not None:
                        self._manager.request_image(name)
                    continue
                x, y = op[1], op[2]
                if op[0] == "imagepart":
                    px, py, pw, ph = op[4]
                    area = pygame.Rect(int(px), int(py), max(0, int(pw)),
                                       max(0, int(ph)))
                    surf.blit(img, (r.x + int(x), r.y + int(y)), area)
                    continue
                w, h = op[4], op[5]
                if w > 0 and h > 0 and img.get_size() != (int(w), int(h)):
                    img = pygame.transform.smoothscale(img, (int(w), int(h)))
                surf.blit(img, (r.x + int(x), r.y + int(y)))


class GuiTextListCtrl(GuiControl):
    """Vertical list of addRow() rows; click selects a row and fires
    onSelect(entryid, entrytext, entryindex) -- same convention as
    GuiPopUpEditCtrl. Used all over the Login UI (GlobalChat_Channels,
    start-menu rows via the GuiStartMenuCtrl subclass)."""

    CTRL_CLASS = "GuiTextListCtrl"
    ROW_H = 18

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 24.0
        self.selected_index = -1

    def _m_clearrows(self, *args) -> float:
        # clearRows() must also clear the SELECTION: Login rebuilds its tab
        # strips with clearRows + addRow + setSelectedById(sameid) on every
        # server click -- with the old index kept, re-selecting the same id
        # was treated as a no-op and onSelect (which shows the pane) never
        # fired, leaving every table panel hidden.
        self.selected_index = -1
        return super()._m_clearrows(*args)

    def content_height(self) -> int:
        return len(self.list_rows) * self.ROW_H

    def row_at(self, pos) -> int:
        r = self.rect()
        if not r.collidepoint(pos) or not self.list_rows:
            return -1
        idx = int((pos[1] - r.y) // self.ROW_H)
        return idx if 0 <= idx < len(self.list_rows) else -1

    def click_at(self, pos) -> bool:
        return self.select_index(self.row_at(pos))

    def select_index(self, index: int) -> bool:
        if not 0 <= index < len(self.list_rows):
            return False
        row = self.list_rows[index]
        text = to_str(row.get("text"))
        if text == "-":
            return False                      # separator row
        self.selected_index = index
        self.fire_event("onselect", row.get("id"), text, float(index))
        return True

    def _m_setselectedrow(self, *args) -> float:
        """setSelectedRow(index) -- Login selects its default tab this way
        (Serverlist_DescriptionTab.setSelectedRow(0))."""
        if args:
            self.select_index(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        """setSelectedById(id) -- select the row whose `id` member matches
        (Login: Serverlist_TablesTab.setSelectedById(0) right after
        addRow(0, ...))."""
        if args:
            wanted = to_str(args[0])
            for index, row in enumerate(self.list_rows):
                if to_str(row.get("id")) == wanted:
                    self.select_index(index)
                    break
        return 0.0

    def _m_getselectedrow(self, *args) -> Any:
        """getSelectedRow(): the selected row's ID (Torque returns the id,
        not the index -- Login's own setSelectedById round-trips it)."""
        if 0 <= self.selected_index < len(self.list_rows):
            return self.list_rows[self.selected_index].get("id")
        return -1.0

    def _m_getselectedtext(self, *args) -> str:
        if 0 <= self.selected_index < len(self.list_rows):
            return to_str(self.list_rows[self.selected_index].get("text"))
        return ""

    def _m_sortascending(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold())
        return 0.0

    def _m_sortdescending(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold(),
                            reverse=True)
        return 0.0

    def _m_findtext(self, *args) -> float:
        """findText(text) -> the matching row's INDEX, or -1.

        Reference: GuiTextListCtrlProperties.cpp:420 `{'i', "s"}` ->
        GuiTextListCtrl::findEntryByText (FourPlay quattroplay/src/gui/
        GuiTextListCtrl.cpp:747-758), a linear scan returning the array
        position. The sibling binding findTextId() is the one that maps that
        position to a row id -- so this must NOT return the id. Live site:
        era weaponSkyld/RC.txt:916 uses it to find its "Admins"/"Players"
        group header and insert the row after it."""
        wanted = to_str(args[0]) if args else ""
        for index, row in enumerate(self.list_rows):
            if to_str(row.get("text")) == wanted:
                return float(index)
        return -1.0

    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselectedrow", "setselectedbyid", "getselectedrow",
         "getselectedtext", "sortascending", "sortdescending", "findtext"})

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        # keep our height in sync with content so ancestor GuiScrollCtrl
        # clipping/scrolling covers every row
        self.height = max(self.height, float(self.content_height()))
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg, r)
        if fonts is None:
            return
        font = _font(fonts, prof)
        for index, row in enumerate(self.list_rows):
            rr = pygame.Rect(r.x, r.y + index * self.ROW_H, r.width, self.ROW_H)
            text = to_str(row.get("text"))
            if text == "-":
                pygame.draw.line(surf, prof.border[:3],
                                 (rr.x + 4, rr.centery), (rr.right - 4, rr.centery))
                continue
            fg = prof.fg
            if index == self.selected_index:
                _fill_rect(surf, prof.title_bg, rr)
                fg = _readable_on(prof.title_bg, prof.bg, prof.fg)
            _draw_label(surf, font, text, fg,
                        (rr.x + 4, rr.centery - font.get_height() // 2),
                        prof.text_shadow and index != self.selected_index)


class GuiTabCtrl(GuiControl):
    """Horizontal tab strip over addRow() rows. Selecting fires
    onDeselect(oldid, oldtext, oldindex) then onSelect(newid, newtext,
    newindex) -- exactly the pair Login's Serverlist_DescriptionTab /
    Serverlist_TablesTab / GlobalChat_ChatTab handlers expect (they hide
    the old tab's panel and show the new one's)."""

    CTRL_CLASS = "GuiTabCtrl"
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselectedrow", "setselectedbyid"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 200.0, 22.0
        self.selected_index = -1

    def _m_clearrows(self, *args) -> float:
        # same reset-selection-on-clearRows contract as GuiTextListCtrl
        # (Login re-selects the same row id after every rebuild)
        self.selected_index = -1
        return super()._m_clearrows(*args)

    def tab_width(self) -> float:
        w = to_num(self._members.get("tabwidth", 0))
        if w > 0:
            return w
        return self.width / max(1, len(self.list_rows))

    def tab_at(self, pos) -> int:
        r = self.rect()
        if not r.collidepoint(pos) or not self.list_rows:
            return -1
        idx = int((pos[0] - r.x) // max(1.0, self.tab_width()))
        return idx if 0 <= idx < len(self.list_rows) else -1

    def click_at(self, pos) -> bool:
        return self.select_index(self.tab_at(pos))

    def select_index(self, index: int) -> bool:
        if not 0 <= index < len(self.list_rows) or index == self.selected_index:
            return False
        old = self.selected_index
        self.selected_index = index
        if 0 <= old < len(self.list_rows):
            row = self.list_rows[old]
            self.fire_event("ondeselect", row.get("id"),
                            to_str(row.get("text")), float(old))
        row = self.list_rows[index]
        self.fire_event("onselect", row.get("id"),
                        to_str(row.get("text")), float(index))
        return True

    def _m_setselectedrow(self, *args) -> float:
        if args:
            self.select_index(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        if args:
            wanted = to_str(args[0])
            for index, row in enumerate(self.list_rows):
                if to_str(row.get("id")) == wanted:
                    self.select_index(index)
                    break
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        tw = int(max(1.0, self.tab_width()))
        base = prof.bg if prof.bg is not None else (24, 48, 112, 224)
        skin = self._skin(prof, sprite_mgr)
        # guiblue_tab.png: 9-patch group 0 = the (taller) selected tab,
        # group 1 = the shorter unselected tab, then arrow rows.
        for index, row in enumerate(self.list_rows):
            selected = index == self.selected_index
            rr = pygame.Rect(r.x + index * tw, r.y, tw, r.height)
            if not selected:
                rr = pygame.Rect(rr.x, rr.y + 3, rr.width, rr.height - 3)
            drew = False
            if skin is not None:
                drew = skin.draw_nine(surf, rr, 0 if selected else 3,
                                      int(255 * prof.transparency))
                if not drew and not selected:
                    drew = skin.draw_nine(surf, rr, 0,
                                          int(255 * prof.transparency))
            if not drew:
                fill = prof.title_bg if selected else _shade(base, 1.2)
                _fill_rect(surf, fill, rr)
                pygame.draw.rect(surf, prof.border[:3], rr, 1)
            if fonts is not None:
                font = _font(fonts, prof)
                text = to_str(row.get("text"))
                tw_px = font.size(text)[0]
                _draw_label(surf, font, text, prof.fg,
                            (rr.centerx - tw_px // 2,
                             rr.centery - font.get_height() // 2),
                            prof.text_shadow)


class _TreeNodeIcon(GS2Object):
    """A tree node's `icon` drawing surface: records the image filename the
    script paints (`node.icon.drawimage(0, 0, "graalicon_big.png")`) so the
    tree renderer can blit it; every other member is a no-op callable (same
    contract as _InertDrawable)."""

    def __init__(self, node: "GuiTreeNode"):
        super().__init__(name="node.icon")
        self._node = node

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("drawimage", "drawimagestretched"):
            def _draw(*args, _node=self._node, _k=k):
                # drawimage(x, y, image) / drawimagestretched(x,y,w,h, image, ...)
                idx = 2 if _k == "drawimage" else 4
                if len(args) > idx:
                    _node.icon_image = to_str(args[idx])
                return 0.0
            return _draw
        if k in ("clearall", "clear"):
            def _clear(*args, _node=self._node):
                _node.icon_image = ""
                return 0.0
            return _clear
        v = super().get(k)
        return v if v is not None else (lambda *a: 0.0)

    def has(self, key: str) -> bool:
        return True


class GuiTreeNode(GS2Object):
    """One GuiTreeViewCtrl entry (folder or leaf). Script-visible members:
    `text` (leaf text may carry TAB-separated columns, e.g.
    "Zelda: A Link to the Past\\t63" from Login's server list), `id`,
    `sortgroup`, `sortvalue`, `icon`, and a `select()` method."""

    def __init__(self, tree: "GuiTreeViewCtrl", text: str,
                 parent_node: Optional["GuiTreeNode"] = None):
        super().__init__(name="treenode")
        self.tree = tree
        self.text = text
        self.parent_node = parent_node
        self.child_nodes: List["GuiTreeNode"] = []
        self.icon_image = ""

    @property
    def is_folder(self) -> bool:
        return bool(self.child_nodes)

    def columns(self) -> List[str]:
        return self.text.split("\t")

    def path(self) -> str:
        parts, node = [], self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            parts.append(node.columns()[0])
            node = node.parent_node
        return "/".join(reversed(parts))

    def level(self) -> float:
        """Torque tree depth, 1-based (a root node is level 1). Login gates
        its connect handler on it -- `if (node == null || node.level <= 1)
        return;` skips the CATEGORY folder rows -- so an unanswered read
        (0) made every row look like a folder and swallowed the connect."""
        depth, node = 0, self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            depth += 1
            node = node.parent_node
        return float(depth)

    def profile_ref(self) -> Any:
        """This node's own `profile` override, if the script set one.
        Login's serverlist restyles its category folders with
        `node.profile = IRC_TreeViewProfile2;` (a different fill), which the
        renderer used to ignore -- every row drew in the tree's profile."""
        return self._members.get("profile")

    def add_node(self, *args) -> "GuiTreeNode":
        child = GuiTreeNode(self.tree, to_str(args[0]) if args else "", self)
        self.child_nodes.append(child)
        return child

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "text":
            return self.text
        if k == "level" and k not in self._members:
            return self.level()
        if k == "select" and not super().has(k):
            return lambda *a: self.tree.select_node(self)
        if k == "addnode" and not super().has(k):
            # parentNode.addNode(text) -> the new CHILD node (Staff's
            # GUIExplorer walks the control tree building one node per
            # control this way)
            return self.add_node
        if k == "icon" and k not in self._members:
            v = self._members[k] = _TreeNodeIcon(self)
            return v
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "text":
            self.text = to_str(value)
            return
        super().set(key, value)

    def has(self, key: str) -> bool:
        return True


class GuiTreeViewCtrl(GuiControl):
    """Hierarchical list built with addNodeByPath("Folder/Leaf", "/") --
    the control the Login server list actually lives in
    (Serverlist_ServerList: category folders containing one row per
    server, icon + name + player count, sorted by player count within
    category). Selection fires onSelect(node, path, dot); a double-click
    fires onDblClick(node, path, dot), which on Login connects to the
    server (checkServerConnect -> serverwarp)."""

    CTRL_CLASS = "GuiTreeViewCtrl"
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({
        "clearnodes", "addnodebypath", "getnode", "getselectednode",
        "setselectedbyid", "addnode",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 200.0, 120.0
        self.root_nodes: List[GuiTreeNode] = []
        self.selected_node: Optional[GuiTreeNode] = None

    # -- script surface ---------------------------------------------------

    def get(self, key: str) -> Any:
        if key.lower() == "nodes" and "nodes" not in self._members:
            return self.flat_nodes()
        return super().get(key)

    def _m_clearnodes(self, *args) -> float:
        self.root_nodes.clear()
        self.selected_node = None
        return 0.0

    #: clearAll() on a tree empties its NODES, not the base class's row model
    _m_clearall = _m_clearnodes

    def _m_addnode(self, *args) -> GuiTreeNode:
        """addNode(text) on the CONTROL: append a root node. (Staff's
        GUIExplorer builds its object tree with parentNode.addNode(...) --
        see GuiTreeNode's own addnode for the per-node form.)"""
        node = GuiTreeNode(self, to_str(args[0]) if args else "", None)
        self.root_nodes.append(node)
        return node

    def _m_addnodebypath(self, *args) -> Optional[GuiTreeNode]:
        if not args:
            return None
        path = to_str(args[0])
        sep = to_str(args[1]) if len(args) > 1 else "/"
        parts = path.split(sep) if sep else [path]
        parent: Optional[GuiTreeNode] = None
        siblings = self.root_nodes
        node: Optional[GuiTreeNode] = None
        for depth, part in enumerate(parts):
            last = depth == len(parts) - 1
            node = None if last else next(
                (n for n in siblings if n.columns()[0] == part), None)
            if node is None:
                node = GuiTreeNode(self, part, parent)
                siblings.append(node)
            parent, siblings = node, node.child_nodes
        return node

    def _m_getnode(self, *args) -> Optional[GuiTreeNode]:
        name = to_str(args[0]) if args else ""
        for node in self.flat_nodes():
            if node.columns()[0] == name:
                return node
        return None

    def _m_getselectednode(self, *args) -> Optional[GuiTreeNode]:
        return self.selected_node

    def _m_setselectedbyid(self, *args) -> float:
        """setSelectedById(id): select the node whose `id` member matches
        (Login's tree keeps its serverlist row index there)."""
        if args:
            wanted = to_str(args[0])
            for node in self.flat_nodes():
                if to_str(node.get("id")) == wanted:
                    self.select_node(node)
                    break
        return 0.0

    def _m_sort(self, *args) -> float:
        """Folders by their `sortgroup` ascending, leaves inside each folder
        by `sortvalue` (player count) descending -- the tree's construction
        fields on Login (sortmode="value", sortorder="descending",
        groupsortorder="ascending")."""
        self.root_nodes.sort(key=lambda n: to_num(n.get("sortgroup") or 0))
        for folder in self.root_nodes:
            folder.child_nodes.sort(
                key=lambda n: to_num(n.get("sortvalue") or 0), reverse=True)
        return 0.0

    # -- model ------------------------------------------------------------

    def flat_nodes(self) -> List[GuiTreeNode]:
        out: List[GuiTreeNode] = []
        def visit(nodes):
            for n in nodes:
                out.append(n)
                visit(n.child_nodes)
        visit(self.root_nodes)
        return out

    def select_node(self, node: Optional[GuiTreeNode], event: str = "onselect") -> None:
        self.selected_node = node
        if node is not None:
            self.fire_event(event, node, node.path(), 0.0)

    # -- render / hit-test ------------------------------------------------

    def row_height(self) -> int:
        return max(20, int(self.icon_h) + 4) if self.icon_h else 20

    def display_nodes(self) -> List[GuiTreeNode]:
        """flat_nodes minus category folders with an EMPTY label. The live
        Login lister has no name for its hidden-servers category (the wire
        rows arrive as "/Name\\t0"), which produced a blank folder row; the
        official client shows no such row, so it is dropped from display
        (children keep their indent) while staying script-visible in
        flat_nodes/`nodes`."""
        return [n for n in self.flat_nodes()
                if n.columns()[0] or not n.is_folder]

    def node_at(self, pos) -> Optional[GuiTreeNode]:
        r = self.rect()
        if not r.collidepoint(pos):
            return None
        nodes = self.display_nodes()
        idx = int((pos[1] - r.y) // self.row_height())
        return nodes[idx] if 0 <= idx < len(nodes) else None

    def column_offsets(self) -> List[float]:
        """Column x offsets: setColumnOffset calls override the `columns`
        construction field ({0, 230} on Login's server list)."""
        offsets = dict(self._members.get("_column_offsets") or {})
        cols = self._members.get("columns")
        if isinstance(cols, (list, tuple)):
            for i, v in enumerate(cols):
                offsets.setdefault(i, to_num(v))
        out = [v for _i, v in sorted(offsets.items())]
        return out or [0.0]

    def node_profile(self, node: GuiTreeNode, default: GuiProfile) -> GuiProfile:
        """The effective style for ONE row: a node's own `profile` override
        resolved through the same inheritance chain controls use, else the
        tree's profile. Login styles its category folders with
        IRC_TreeViewProfile2 (opaque, its own fill/font colour) while the
        server rows keep IRC_TreeViewProfile."""
        ref = node.profile_ref()
        if not ref:
            return default
        return _profile_from_fields(_profile_fields(ref, self._manager, set()))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        nodes = self.display_nodes()
        row_h = self.row_height()
        self.height = max(self.height, float(len(nodes) * row_h))
        tree_prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, tree_prof.bg, r)
        if fonts is None:
            return
        icon_w = int(self.icon_w) or 16
        icon_h = int(self.icon_h) or 16
        col_offsets = self.column_offsets()
        for index, node in enumerate(nodes):
            prof = self.node_profile(node, tree_prof)
            font = _font(fonts, prof)
            rr = pygame.Rect(r.x, r.y + index * row_h, r.width, row_h)
            indent = 0 if node.parent_node is None else 16
            fg = prof.fg
            if prof is not tree_prof and prof.opaque:
                # a per-node profile paints its own row background (the
                # folder-row banding the reference client shows)
                _fill_rect(surf, prof.bg, rr)
            if node is self.selected_node:
                _fill_rect(surf, prof.title_bg, rr)
                fg = _readable_on(prof.title_bg, prof.bg, prof.fg)
            cols = node.columns()
            tx = rr.x + 4 + indent
            if node.is_folder:
                icon = None
                if node.icon_image and sprite_mgr is not None:
                    icon = sprite_mgr.load_sheet(node.icon_image)
                    if icon is None and self._manager is not None:
                        self._manager.request_image(node.icon_image)
                if icon is not None:
                    ih = min(row_h - 2, icon.get_height())
                    iw = max(1, icon.get_width() * ih // max(1, icon.get_height()))
                    if icon.get_size() != (iw, ih):
                        icon = pygame.transform.smoothscale(icon, (iw, ih))
                    surf.blit(icon, (tx, rr.centery - ih // 2))
                    tx += iw + 4
                else:
                    # open-folder disclosure triangle fallback
                    cy = rr.centery
                    pygame.draw.polygon(
                        surf, fg,
                        [(tx, cy - 3), (tx + 8, cy - 3), (tx + 4, cy + 4)])
                    tx += 14
            elif node.icon_image and sprite_mgr is not None:
                img = sprite_mgr.load_sheet(node.icon_image)
                if img is None and self._manager is not None:
                    self._manager.request_image(node.icon_image)
                if img is not None:
                    if img.get_size() != (icon_w, icon_h):
                        img = pygame.transform.smoothscale(img, (icon_w, icon_h))
                    surf.blit(img, (tx, rr.centery - icon_h // 2))
                tx += icon_w + 4
            _draw_label(surf, font, cols[0], fg,
                        (tx, rr.centery - font.get_height() // 2),
                        prof.text_shadow and node is not self.selected_node)
            # extra columns at the profile's column offsets (player count)
            for ci in range(1, len(cols)):
                if not cols[ci]:
                    continue
                if ci < len(col_offsets) and col_offsets[ci] > 0:
                    cx = rr.x + int(col_offsets[ci])
                else:
                    cx = rr.right - font.size(cols[ci])[0] - 8
                cx = min(cx, rr.right - font.size(cols[ci])[0] - 4)
                _draw_label(surf, font, cols[ci], fg,
                            (cx, rr.centery - font.get_height() // 2),
                            prof.text_shadow and node is not self.selected_node)


class GuiTaskbar(GuiControl):
    """The Login taskbar strip: a plain container bar; its buttons are
    ordinary GuiButtonCtrl children (the start button opens the
    GuiStartMenuCtrl -- engine behavior, provided by GS2GuiManager's
    click routing)."""

    CTRL_CLASS = "GuiTaskbar"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 640.0, 30.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        # IRC_TaskBarProfile: bitmap = guiblue_button.png (the bar is one
        # stretched button-face 9-patch, the classic look)
        if skin is not None and skin.draw_nine(surf, r, 0,
                                               int(255 * prof.transparency)):
            return
        _fill_rect(surf, prof.bg if prof.bg is not None else prof.title_bg, r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)


class GuiStartMenuCtrl(GuiTextListCtrl):
    """The taskbar's start menu: hidden until the start button toggles it
    (see GS2GuiManager), then a vertical menu of addRow() entries whose
    selection fires onSelect(selid, seltext, selindex) and closes the menu
    -- Login's Serverlist_Taskbar_Menu opens Global Chat, the log window,
    the playerlist etc. from exactly that handler."""

    CTRL_CLASS = "GuiStartMenuCtrl"
    ROW_H = 22

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 190.0, 24.0
        self.visible = False        # engine shows it on start-button click

    _METHOD_NAMES = GuiTextListCtrl._METHOD_NAMES | frozenset({"open"})

    def select_index(self, index: int) -> bool:
        picked = super().select_index(index)
        if picked and self._manager is not None:
            self._manager.hide(self)
        return picked

    def _m_open(self, *args) -> float:
        """open(x, y): show the menu with its BOTTOM-left at the given
        canvas point -- Login opens it from the start button's own
        localToGlobalCoord({0, 0}), i.e. the button's top-left corner, and
        the reference menu grows upwards from there."""
        self.height = float(max(self.content_height(), self.ROW_H))
        x, y = self._coord_arg(args)
        self.x, self.y = x, y - self.height
        if self._manager is not None:
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        self.height = float(max(self.content_height(), self.ROW_H))
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg if prof.bg is not None else (16, 32, 96, 240), r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)
        super()._draw_self(surf, fonts, sprite_mgr)


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

    def __init__(self, ctor_arg: Any = None, parent_name: str = ""):
        super().__init__(ctor_arg)
        self.visible = False
        self.parent_profile_name = parent_name.lower()

    def has(self, key: str) -> bool:
        return True

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        return


_CONTROL_CLASSES: Dict[str, type] = {
    cls.CTRL_CLASS.lower(): cls for cls in (
        GuiControl, GuiWindowCtrl, GuiButtonCtrl, GuiTextCtrl, GuiMLTextCtrl,
        GuiScrollCtrl, GuiTextEditCtrl, GuiCheckBoxCtrl, GuiRadioCtrl,
        GuiBitmapCtrl, GuiShowImgCtrl, GuiPopUpEditCtrl, GuiControlProfile,
        GuiTextListCtrl, GuiTabCtrl, GuiTreeViewCtrl, GuiTaskbar,
        GuiStartMenuCtrl,
        # classes the 2026-07-24 Login corpus constructs that used to fall
        # back to a generic GuiControl ("unknown control class")
        GuiAccountPasswordCtrl, GuiMLTextEditCtrl, GuiProgressCtrl,
        GuiBitmapButtonCtrl, GuiPopUpMenuCtrl, GuiDrawingPanel,
        # 2026-07-25: the two remaining "unknown control class" warnings on
        # Login, both raised by -Serverlist_Chat's Global Chat window
        GuiFrameSetCtrl, GuiContextMenuCtrl,
    )
}


def control_method_names() -> frozenset:
    """Every script-callable control method across the whole class table.

    GS2ClientHost.host_surface() used to union GuiControl._METHOD_NAMES
    alone, so every SUBCLASS method (setSelectedRow, getSelectedNode,
    addNodeByPath, ...) was reported as an unimplemented gap by the deep
    crawler even though the control answers it -- which is exactly the kind
    of false gap that sends a coverage round chasing ghosts."""
    names: set = set()
    for cls in (*_CONTROL_CLASSES.values(), GuiControl):
        names |= set(getattr(cls, "_METHOD_NAMES", ()))
    return frozenset(names)


def make_control(classname: str, ctor_arg: Any) -> GuiControl:
    cls = _CONTROL_CLASSES.get(classname.lower())
    if cls is None:
        if classname.lower().endswith("profile"):
            # Torque profile-definition DERIVATION: the classname is the
            # PARENT profile (engine builtin like GuiBlueTransWindowProfile,
            # or a previously script-defined profile like IRC_WindowProfile)
            # and roots the new profile's inheritance chain. Named style
            # records, never visual controls -- Login's -Rescripted/
            # Serverlist declares ~40 of these.
            ctrl = GuiControlProfile(ctor_arg, parent_name=classname)
            ctrl.name = classname
            return ctrl
        _log_once(("class", classname.lower()),
                  "GS2 GUI: unknown control class %r, rendering generically", classname)
        ctrl = GuiControl(ctor_arg)
        ctrl.name = classname
        return ctrl
    return cls(ctor_arg)


# =============================================================================
# Manager
# =============================================================================

class GS2GuiManager:
    """Root of the GS2 GUI control tree.

    Construction (`create_control`/`addcontrol`) is driven purely by call
    order -- see module docstring point 1 for why that's sufficient to infer
    parent/child nesting without addcontrol() ever naming a parent.
    `rt2` (the owning ClientGS2) is unused today but kept for parity with the
    rest of gs2_client.py's host objects and in case a future control type
    needs client/file access (e.g. downloading a not-yet-cached bitmap)."""

    def __init__(self, rt2=None):
        self.rt2 = rt2
        self.roots: List[GuiControl] = []
        self._named: Dict[str, GuiControl] = {}
        self._construction_stack: List[GuiControl] = []
        self._focus: Optional[GuiTextEditCtrl] = None
        self._drag: Optional[Tuple[GuiWindowCtrl, float, float]] = None
        # Render-only mouse state for hover/pressed visuals (button + check-
        # box/radio) -- maintained the same way as `_focus`, via mouse
        # events already flowing through handle_event() (see input.py's
        # _gs2_gui_event, which remaps every MOUSEMOTION into virtual-canvas
        # coordinates before forwarding it here).
        self._hover: Optional[GuiControl] = None
        self._pressed: Optional[GuiControl] = None
        self._open_popup: Optional[GuiPopUpEditCtrl] = None
        # (ticks, node) of the last tree-view row click, for double-click
        # detection (onDblClick = connect on the Login server list)
        self._last_tree_click: Tuple[int, Optional[GuiTreeNode]] = (0, None)
        # skin-art cache (profile bitmap sheets, sliced) + one-shot file
        # requests for art the sprite manager doesn't have yet
        self._skins: Dict[str, _Skin] = {}
        self._requested_images: set = set()
        # last pointer position seen by handle_event, already in the
        # virtual-canvas space control x/y live in (see handle_event's
        # docstring) -- what openAtMouse() anchors to
        self.last_mouse: Optional[Tuple[int, int]] = None
        # canvas size the control tree was last laid out for; render()
        # compares against the live surface and propagates Torque-sizing
        # deltas on change (window resizes)
        self.canvas_size: Optional[Tuple[int, int]] = None
        # GuiCanvas cursor visibility (cursorOn/cursorOff/isCursorOn --
        # FourPlay quattroplay/src/gui/GuiCanvas.cpp:47-63, bindings :83-85).
        # The canvas starts with the pointer shown, which is also pygame's
        # default, so cursorOn() -- the only one of the three any corpus
        # actually calls -- is a confirmation rather than a change.
        self.cursor_on = True

    def set_cursor_on(self, on: bool) -> None:
        """cursorOn()/cursorOff(): show or hide the mouse pointer over the
        canvas. Login's serverlist calls cursorOn() when it takes over the
        screen (graal-loginserver weapon-Rescripted_Serverlist.txt:381)."""
        self.cursor_on = bool(on)
        try:
            pygame.mouse.set_visible(self.cursor_on)
        except Exception:      # no display yet / headless SDL driver
            pass

    @property
    def keyboard_captured(self) -> bool:
        """True while a text-edit control holds keyboard focus, so gameplay
        held-key movement must not run alongside typing."""
        return self._focus is not None

    # -- construction --------------------------------------------------------

    def create_control(self, classname: str, ctor_arg: Any) -> GuiControl:
        ctrl = make_control(classname, ctor_arg)
        ctrl._manager = self
        if ctrl.ctrl_name:
            self._named[ctrl.ctrl_name.lower()] = ctrl
        if ctrl.is_profile:
            # named registration only -- never in the construction stack or
            # the render tree (its auto-emitted addcontrol no-ops below)
            return ctrl
        if self._construction_stack:
            self._construction_stack[-1].add_child(ctrl)
        self._construction_stack.append(ctrl)
        return ctrl

    def addcontrol(self, ctrl: Any, owner_vm: Any = None) -> None:
        if isinstance(ctrl, str):
            # the inline-new compile shape (`Name = new ("Class") {...}`,
            # see Login's -Serverlist_Chat addChatWindowControls) passes the
            # control's NAME string to its auto-emitted addcontrol
            ctrl = self._named.get(ctrl.lower(), ctrl)
        if not isinstance(ctrl, GuiControl):
            _log_once(("addcontrol", type(ctrl).__name__),
                      "GS2 GUI: addcontrol() called on a non-control value (%r)", ctrl)
            return
        if owner_vm is not None and ctrl._owner_vm is None:
            # every new-statement emits addcontrol from the constructing
            # script's VM, so this stamps the whole tree -- fire_event's
            # dotted-handler fallback resolves against it
            ctrl._owner_vm = owner_vm
        if ctrl.is_profile:
            return
        # Pop by identity, not just the top: if a script aborted mid-`new`
        # (VM error/op budget), descendants above ctrl never saw their
        # auto-emitted addcontrol. They're already parented under ctrl, so
        # dropping them from the stack is safe.
        if ctrl in self._construction_stack:
            idx = self._construction_stack.index(ctrl)
            del self._construction_stack[idx:]
        if ctrl.parent is None and ctrl not in self.roots:
            self.roots.append(ctrl)

    def _reap_construction_leak(self) -> None:
        """Valid construction is synchronous within one VM execution, so the
        stack must be empty whenever render()/handle_event() run. Residue
        means a script aborted mid-`new` (error cap / op budget) and its
        auto-emitted addcontrol never fired — without this reset every later
        `new` from ANY script would silently parent under the dead control.
        Per the C# client's semantics the un-added outermost control never
        reaches the canvas, so it is simply dropped."""
        if self._construction_stack:
            _log_once(("construction_leak", self._construction_stack[0].name),
                      "GS2 GUI: script aborted mid-construction; dropping %d "
                      "unfinished control(s)", len(self._construction_stack))
            self._construction_stack.clear()

    def destroy(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            return
        if ctrl.parent is not None:
            ctrl.parent.remove_child(ctrl)
        elif ctrl in self.roots:
            self.roots.remove(ctrl)
        if ctrl.ctrl_name and self._named.get(ctrl.ctrl_name.lower()) is ctrl:
            del self._named[ctrl.ctrl_name.lower()]
        self._release_pointers_under(ctrl)

    def _release_pointers_under(self, ctrl: GuiControl) -> None:
        """Drop keyboard focus / an active drag / hover / pressed state held
        by ctrl OR any of its descendants. Scripts close whole windows
        (hidegui/destroy on the container), so an exact-identity check would
        leave a vanished text edit holding focus — and keyboard_captured
        would block player movement with nothing visible on screen. Same
        reasoning applies to a vanished button being left permanently
        "hovered"/"pressed"."""
        if self._focus is not None and self._is_or_descends(self._focus, ctrl):
            self._set_focus(None)
        if self._drag is not None and self._is_or_descends(self._drag[0], ctrl):
            self._drag = None
        if self._hover is not None and self._is_or_descends(self._hover, ctrl):
            self._set_hover(None)
        if self._pressed is not None and self._is_or_descends(self._pressed, ctrl):
            self._set_pressed(None)
        if (self._open_popup is not None and
                self._is_or_descends(self._open_popup, ctrl)):
            self._close_popup()

    @staticmethod
    def _is_or_descends(node: GuiControl, ancestor: GuiControl) -> bool:
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None or id(node) in visited:
                return False
            visited.add(id(node))
            if node is ancestor:
                return True
            node = node.parent
        return False

    def _resolve(self, target: Any) -> Optional[GuiControl]:
        if isinstance(target, GuiControl):
            return target
        if isinstance(target, str):
            return self._named.get(target.lower())
        return None

    def profile_by_name(self, name: str) -> Optional["GuiControlProfile"]:
        """The registered profile object for `name`, auto-vivifying
        engine-builtin profiles (GuiBlueTransWindowProfile,
        GuiDefaultProfile, ...) on first reference: the official client
        defines those natively, so both `profile = GuiBlueTransWindowProfile;`
        (bare object reference) and `with (GuiDefaultProfile) {...}`
        restyles must resolve to a live object even though no script ever
        declares one. The vivified object is seeded with the builtin field
        data, so later script writes overlay it like any derived profile."""
        key = (name or "").lower()
        obj = self._named.get(key)
        if isinstance(obj, GuiControlProfile):
            return obj
        if obj is not None:
            return None       # a real control owns this name; don't shadow
        fields = _BUILTIN_PROFILE_FIELDS.get(key)
        if fields is None:
            return None
        prof = GuiControlProfile(name)
        prof.name = name
        prof._manager = self
        prof._members.update(fields)
        self._named[key] = prof
        return prof

    # -- visibility -----------------------------------------------------

    def show(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            _log_once(("show", to_str(target)),
                      "GS2 GUI: showgui() target not found: %r", target)
            return
        ctrl.visible = True
        self.bring_to_front(ctrl)

    def hide(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            _log_once(("hide", to_str(target)),
                      "GS2 GUI: hidegui() target not found: %r", target)
            return
        ctrl.visible = False
        self._release_pointers_under(ctrl)

    def bring_to_front(self, ctrl: GuiControl) -> None:
        siblings = ctrl.parent.children if ctrl.parent is not None else self.roots
        if ctrl in siblings:
            siblings.remove(ctrl)
            siblings.append(ctrl)          # z-order = list order, last = topmost

    def add_to(self, parent: Any, child: Any) -> None:
        parent_ctrl, child_ctrl = self._resolve(parent), self._resolve(child)
        if (parent_ctrl is not None and child_ctrl is not None
                and not child_ctrl.is_profile):
            if parent_ctrl.add_child(child_ctrl) and child_ctrl in self.roots:
                self.roots.remove(child_ctrl)

    def get_child(self, parent: Any, child: Any) -> Any:
        parent_ctrl = self._resolve(parent)
        if parent_ctrl is None:
            return 0.0
        if isinstance(child, str):
            wanted = child.casefold()
            for item in parent_ctrl.children:
                if item.ctrl_name.casefold() == wanted:
                    return item
        else:
            index = int(to_num(child))
            if 0 <= index < len(parent_ctrl.children):
                return parent_ctrl.children[index]
        return 0.0

    def hide_children(self, parent: Any) -> None:
        ctrl = self._resolve(parent)
        if ctrl is not None:
            for child in ctrl.children:
                child.visible = False
                self._release_pointers_under(child)

    def focus(self, target: Any) -> None:
        ctrl = self._resolve(target)
        self._set_focus(ctrl if isinstance(ctrl, GuiTextEditCtrl) else None)

    # -- skin art / downloads --------------------------------------------

    def request_image(self, name: str) -> None:
        """Ask the server for a GUI image once (skin sheets, tree icons,
        bitmap controls) via the client's normal file-request path; the
        game's on_file callback drops it into the sprite cache."""
        key = to_str(name).lower()
        if not key or key in self._requested_images:
            return
        self._requested_images.add(key)
        client = getattr(self.rt2, "client", None)
        request = getattr(client, "request_file", None)
        if request is None:
            return
        try:
            request(name)
        except Exception:
            logger.exception("GS2 GUI: request_file(%r) failed", name)

    def skin(self, name: str, sprite_mgr) -> Optional[_Skin]:
        """The sliced skin sheet for a profile's bitmap field, fetching the
        file on first miss. Cache entries pin their source surface and are
        re-sliced when the sprite cache replaces it (download landing)."""
        if not name or sprite_mgr is None:
            return None
        key = name.lower()
        sheet = sprite_mgr.load_sheet(name)
        if sheet is None:
            self.request_image(name)
            return None
        entry = self._skins.get(key)
        if entry is not None and entry.source is sheet:
            return entry
        try:
            entry = _Skin(name, sheet)
        except Exception:
            logger.exception("GS2 GUI: skin slice failed for %r", name)
            return None
        self._skins[key] = entry
        return entry

    # -- canvas resize (Torque horizSizing/vertSizing) -------------------

    @staticmethod
    def _apply_sizing(ctrl: GuiControl, old_w: float, old_h: float,
                      new_w: float, new_h: float) -> None:
        """Torque GuiControl::parentResized: adjust one control for its
        parent's extent change, then recurse with this control's own
        old/new extent. Defaults ("right"/"bottom") anchor to the top-left
        and change nothing."""
        dx, dy = new_w - old_w, new_h - old_h
        if not dx and not dy:
            return
        old_cw, old_ch = ctrl.width, ctrl.height
        h = to_str(ctrl._members.get("horizsizing", "")).lower() or "right"
        v = to_str(ctrl._members.get("vertsizing", "")).lower() or "bottom"
        if h == "width":
            ctrl.width = max(0.0, ctrl.width + dx)
        elif h == "left":
            ctrl.x += dx
        elif h == "center":
            ctrl.x = (new_w - ctrl.width) / 2.0
        elif h == "relative" and old_w > 0:
            scale = new_w / old_w
            ctrl.x *= scale
            ctrl.width *= scale
        if v == "height":
            ctrl.height = max(0.0, ctrl.height + dy)
        elif v == "top":
            ctrl.y += dy
        elif v == "center":
            ctrl.y = (new_h - ctrl.height) / 2.0
        elif v == "relative" and old_h > 0:
            scale = new_h / old_h
            ctrl.y *= scale
            ctrl.height *= scale
        if (ctrl.width, ctrl.height) != (old_cw, old_ch):
            for child in ctrl.children:
                GS2GuiManager._apply_sizing(child, old_cw, old_ch,
                                            ctrl.width, ctrl.height)

    def canvas_object(self) -> GS2Object:
        """Live-geometry stand-in for the canvas, handed out as root
        controls' `parent` (Torque semantics)."""
        obj = getattr(self, "_canvas_obj", None)
        if obj is None:
            obj = self._canvas_obj = GS2Object(name="canvas")
        if self.canvas_size is not None:
            w, h = float(self.canvas_size[0]), float(self.canvas_size[1])
        else:
            gs1 = getattr(self.rt2, "gs1", None)
            w = float(getattr(gs1, "screen_w", 800) or 800)
            h = float(getattr(gs1, "screen_h", 600) or 600)
        obj._members.update({
            "width": w, "height": h, "clientwidth": w, "clientheight": h,
            "extent": [w, h], "clientextent": [w, h],
        })
        return obj

    def on_canvas_resize(self, new_w: int, new_h: int) -> None:
        old = self.canvas_size
        self.canvas_size = (new_w, new_h)
        if old is None or old == (new_w, new_h):
            return
        for root in self.roots:
            self._apply_sizing(root, float(old[0]), float(old[1]),
                               float(new_w), float(new_h))

    # -- render ---------------------------------------------------------

    def render(self, surf: pygame.Surface, fonts=None, sprite_mgr=None) -> None:
        self._reap_construction_leak()
        self._close_invalid_popup()
        self.on_canvas_resize(*surf.get_size())
        for root in self.roots:
            self._draw_node(root, surf, fonts, sprite_mgr, None)
        if self._open_popup is not None:
            surf.set_clip(None)
            self._open_popup.draw_popup(surf, fonts)
        surf.set_clip(None)

    def _draw_node(self, node: GuiControl, surf, fonts, sprite_mgr, clip) -> None:
        if not node.visible:
            return
        surf.set_clip(clip)
        node.draw(surf, fonts, sprite_mgr)
        child_clip = clip
        if isinstance(node, GuiScrollCtrl):
            r = node.rect()
            child_clip = r if clip is None else clip.clip(r)
        for c in node.children:
            self._draw_node(c, surf, fonts, sprite_mgr, child_clip)

    # -- hit-testing ------------------------------------------------------

    def hit_test(self, pos: Tuple[int, int]) -> Optional[GuiControl]:
        for root in reversed(self.roots):          # topmost root first
            hit = self._hit_test(root, pos)
            if hit is not None:
                return hit
        return None

    def _hit_test(self, node: GuiControl, pos) -> Optional[GuiControl]:
        if not node.visible or not node.rect().collidepoint(pos):
            return None
        for c in reversed(node.children):           # topmost child first
            hit = self._hit_test(c, pos)
            if hit is not None:
                return hit
        return node

    def _ancestor_window(self, ctrl: GuiControl) -> Optional[GuiWindowCtrl]:
        p = ctrl.parent
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if p is None or id(p) in visited:
                return None
            visited.add(id(p))
            if isinstance(p, GuiWindowCtrl):
                return p
            p = p.parent
        return None

    def _topmost_window(self) -> Optional[GuiWindowCtrl]:
        for root in reversed(self.roots):
            if isinstance(root, GuiWindowCtrl) and root.visible:
                return root
        return None

    def _set_focus(self, ctrl: Optional[GuiTextEditCtrl]) -> None:
        if self._focus is ctrl:
            return
        if self._focus is not None:
            self._focus.focused = False
        self._focus = ctrl
        if ctrl is not None:
            ctrl.focused = True

    def _set_hover(self, ctrl: Optional[GuiControl]) -> None:
        if self._hover is ctrl:
            return
        if self._hover is not None:
            self._hover.hovered = False
        self._hover = ctrl
        if ctrl is not None:
            ctrl.hovered = True

    def _set_pressed(self, ctrl: Optional[GuiControl]) -> None:
        if self._pressed is ctrl:
            return
        if self._pressed is not None:
            self._pressed.pressed = False
        self._pressed = ctrl
        if ctrl is not None:
            ctrl.pressed = True

    def _close_popup(self) -> None:
        if self._open_popup is None:
            return
        self._open_popup.popup_open = False
        self._open_popup.hover_row = -1
        self._open_popup = None
        self._set_hover(None)
        self._set_pressed(None)

    def _open_popup_for(self, ctrl: GuiPopUpEditCtrl) -> None:
        if self._open_popup is not ctrl:
            self._close_popup()
        self._open_popup = ctrl
        ctrl.popup_open = True

    def _close_invalid_popup(self) -> None:
        popup = self._open_popup
        if popup is None:
            return
        node: Optional[GuiControl] = popup
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            if id(node) in visited:
                self._close_popup()
                return
            visited.add(id(node))
            if not node.visible:
                self._close_popup()
                return
            node = node.parent
        else:
            self._close_popup()
            return
        if popup.parent is None and popup not in self.roots:
            self._close_popup()

    def _select_radio(self, radio: "GuiRadioCtrl") -> None:
        """Radio-group mutual exclusion: checking one radio unchecks its
        siblings -- the other children of the same immediate parent
        container (roots, if the radio has no parent), per the module
        docstring's "no group-name property on the wire" note. Matches real
        radio-button UX: clicking the already-checked radio is a no-op (it
        doesn't uncheck itself), and onAction only fires on an actual
        selection change, not on every click."""
        if radio.checked:
            return
        siblings = radio.parent.children if radio.parent is not None else self.roots
        for sib in siblings:
            if sib is not radio and isinstance(sib, GuiRadioCtrl) and sib.checked:
                sib.checked = False
        radio.checked = True
        radio.fire_action()

    def _shift(self, ctrl: GuiControl, dx: float, dy: float) -> None:
        ctrl.x += dx
        ctrl.y += dy
        for c in ctrl.children:
            self._shift(c, dx, dy)

    # -- events -----------------------------------------------------------

    def handle_event(self, event) -> bool:
        """True = consumed. Assumes `event.pos` is already in the same
        virtual-canvas coordinate space the control tree's x/y live in
        (the pygame_screens.py convention: the caller remaps window coords
        via viewport.window_to_virtual() before calling in)."""
        self._reap_construction_leak()
        self._close_invalid_popup()
        pos = getattr(event, "pos", None)
        if pos is not None:
            self.last_mouse = (int(pos[0]), int(pos[1]))
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._on_mouse_down(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            return self._on_mouse_up(event.pos)
        if event.type == pygame.MOUSEMOTION:
            return self._on_mouse_move(event.pos)
        if event.type == pygame.MOUSEWHEEL:
            return self._on_wheel(event)
        if event.type == pygame.KEYDOWN:
            return self._on_keydown(event)
        return False

    def _on_mouse_down(self, pos) -> bool:
        if self._open_popup is not None:
            popup = self._open_popup
            row = popup.popup_row_at(pos)
            if row >= 0:
                self._set_pressed(popup)
                popup.select_row(row)
                self._close_popup()
                return True
            self._close_popup()
            return True
        hit = self.hit_test(pos)
        if hit is None:
            self._set_focus(None)
            return False

        window = hit if isinstance(hit, GuiWindowCtrl) else self._ancestor_window(hit)
        if window is not None:
            self.bring_to_front(window)

        if isinstance(hit, GuiWindowCtrl) and hit.titlebar_rect().collidepoint(pos):
            self._drag = (hit, pos[0] - hit.x, pos[1] - hit.y)
            self._set_focus(None)
            return True

        if isinstance(hit, GuiTextEditCtrl):
            self._set_focus(hit)
            return True

        if isinstance(hit, GuiPopUpEditCtrl):
            self._set_focus(None)
            self._set_pressed(hit)
            self._open_popup_for(hit)
            return True

        self._set_focus(None)
        if isinstance(hit, GuiRadioCtrl):
            self._set_pressed(hit)
            self._select_radio(hit)
        elif isinstance(hit, GuiCheckBoxCtrl):
            self._set_pressed(hit)
            hit.toggle()
            hit.fire_action()
        elif isinstance(hit, GuiButtonCtrl):
            self._set_pressed(hit)
            if not self._toggle_start_menu(hit):
                hit.fire_action()
        elif isinstance(hit, GuiTreeViewCtrl):
            node = hit.node_at(pos)
            if node is not None:
                now = pygame.time.get_ticks()
                last_t, last_node = self._last_tree_click
                self._last_tree_click = (now, node)
                if node is last_node and now - last_t <= 400:
                    # second click of a double-click: onDblClick (Login:
                    # connect to the clicked server)
                    hit.select_node(node, event="ondblclick")
                else:
                    hit.select_node(node)
        elif isinstance(hit, (GuiTextListCtrl, GuiTabCtrl)):
            hit.click_at(pos)
        return True

    def _toggle_start_menu(self, btn: GuiButtonCtrl) -> bool:
        """Engine behavior with no script-side handler: a taskbar button
        styled as the start button (`stylesection = "Taskbar.StartButton"`,
        Login's Serverlist_TaskButton_Start) toggles the GuiStartMenuCtrl,
        anchored just above it."""
        if to_str(btn._members.get("stylesection", "")).lower() != \
                "taskbar.startbutton":
            return False
        menu = next((c for c in reversed(self.roots)
                     if isinstance(c, GuiStartMenuCtrl)), None)
        if menu is None:
            return False
        if menu.visible:
            self.hide(menu)
            return True
        br = btn.rect()
        menu.height = float(max(menu.content_height(), menu.ROW_H))
        menu.x = float(br.x)
        menu.y = float(br.y - menu.height)
        self.show(menu)
        return True

    def _on_mouse_up(self, pos) -> bool:
        self._set_pressed(None)
        if self._drag is not None:
            self._drag = None
            return True
        return self.hit_test(pos) is not None

    def _on_mouse_move(self, pos) -> bool:
        if self._open_popup is not None:
            popup = self._open_popup
            popup.hover_row = popup.popup_row_at(pos)
            self._set_hover(popup if (popup.hover_row >= 0 or
                                      popup.rect().collidepoint(pos)) else None)
            return True
        hit = self.hit_test(pos)
        self._set_hover(hit if isinstance(
            hit, (GuiButtonCtrl, GuiCheckBoxCtrl, GuiPopUpEditCtrl)) else None)
        if self._drag is None:
            return False
        win, off_x, off_y = self._drag
        # children's x/y are parent-relative (see effective_offset), so
        # moving just the window moves its whole subtree
        win.x = pos[0] - off_x
        win.y = pos[1] - off_y
        return True

    def _on_wheel(self, event) -> bool:
        pos = getattr(event, "pos", None) or pygame.mouse.get_pos()
        node = self.hit_test(pos)
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None or isinstance(node, GuiScrollCtrl):
                break
            if id(node) in visited:
                node = None
                break
            visited.add(id(node))
            node = node.parent
        else:
            node = None
        if node is None:
            return False
        node.scroll_y = max(0.0, min(node.scroll_y - event.y * 20.0,
                                     node.max_scroll_y()))
        return True

    def _on_keydown(self, event) -> bool:
        if event.key == pygame.K_ESCAPE:
            if self._open_popup is not None:
                self._close_popup()
                return True
            top = self._topmost_window()
            if top is not None:
                self.hide(top)
                return True
            return False
        if self._focus is None:
            return False
        if event.key == pygame.K_RETURN:
            # onAction(text) -- the reference passes the field's text (the
            # Login chat field's dotted handler declares a `text` param and
            # sends exactly that string)
            self._focus.fire_action(self._focus.text)
            return True
        if event.key == pygame.K_BACKSPACE:
            # a pending setSelection() range is deleted whole, exactly as
            # the reference client does for a select-all-then-edit
            if not self._focus.take_selection():
                self._focus.text = self._focus.text[:-1]
            return True
        if event.unicode and event.unicode.isprintable():
            self._focus.take_selection()
            if len(self._focus.text) < self._focus.max_len:
                self._focus.text += event.unicode
        return True
