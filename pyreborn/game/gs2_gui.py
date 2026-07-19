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
   not the with-block's target. For that RHS to actually evaluate to a
   callable, `this.<generated-function-name>` member access has to resolve
   to a bound wrapper around the owning VM's own `function_100_1` -- which
   the shared VM (reborn_protocol/gs2/vm.py) does **not** do: its `this` is a
   bare GS2Object (plain dict), so `this.function_100_1` read back `None`
   (verified: this also silently breaks the plain
   `x = function(){...}; x();` lambda idiom used by
   reborn-protocol/tests/fixtures/gs2_baselines/functions/03_lambdas.gs2,
   independent of GUI). Per the task's fallback guidance, this is fixed at
   the *host* layer instead of the shared VM: gs2_client.py's `_ThisObject`
   (pyReborn's `this`-object bridge, not the shared vm.py) now falls back to
   a bound `vm.call(name, *args)` closure when a member isn't a stored value
   but *is* a function on the owning VM -- `GS2VM.has_function`/`.call`
   already recurse into joined classes, so this also covers a handler defined
   inside a joined class's own `new ... {}` block. No change to the shared
   VM's opcode semantics was made or needed; `host.create_object()` was
   already consulted for every `new` (see `_op_new_object` in vm.py) so no
   vm.py change was needed for construction either -- only gs2_client.py.

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
# =============================================================================

class GuiProfile:
    __slots__ = ("bg", "border", "fg", "title_bg", "title_fg")

    def __init__(self, bg, border, fg, title_bg, title_fg):
        self.bg = bg
        self.border = border
        self.fg = fg
        self.title_bg = title_bg
        self.title_fg = title_fg


_DEFAULT_PROFILE_NAME = "guidefaultprofile"

_PROFILES: Dict[str, GuiProfile] = {
    _DEFAULT_PROFILE_NAME: GuiProfile(
        bg=(40, 44, 62), border=(120, 124, 140), fg=(235, 238, 245),
        title_bg=(60, 64, 88), title_fg=(235, 238, 245)),
    "guibluewindowprofile": GuiProfile(
        bg=(24, 32, 64), border=(90, 130, 210), fg=(230, 235, 250),
        title_bg=(40, 70, 140), title_fg=(255, 255, 255)),
}


def _resolve_profile(name: str) -> GuiProfile:
    prof = _PROFILES.get((name or "").lower())
    if prof is None:
        _log_once(("profile", (name or "").lower()),
                  "GS2 GUI: unknown profile %r, using default", name)
        prof = _PROFILES[_DEFAULT_PROFILE_NAME]
    return prof


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


# =============================================================================
# Control tree
# =============================================================================

class GuiControl(GS2Object):
    """Base GS2 GUI control: a script-visible GS2Object (property get/set
    from bytecode) that doubles as a render/hit-test tree node.

    `x`/`y`/`width`/`height`/`text`/`visible`/`profile` are real Python
    attributes (fast, and readable from Python without going through
    GS2Object's dict); any other property a script sets (including
    `onaction`, which ends up holding a Python callable -- see module
    docstring point 2) falls through to the generic member dict."""

    CTRL_CLASS = "GuiControl"

    _NUM_ATTRS = ("x", "y", "width", "height")
    _STR_ATTRS = {"text": "text", "profile": "profile_name", "name": "ctrl_name"}

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
        self.parent: Optional["GuiControl"] = None
        self.children: List["GuiControl"] = []

    # -- GS2Object property bridge ------------------------------------------

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in self._NUM_ATTRS:
            return float(getattr(self, k))
        if k == "visible":
            return 1.0 if self.visible else 0.0
        if k in self._STR_ATTRS:
            return getattr(self, self._STR_ATTRS[k])
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in self._NUM_ATTRS:
            setattr(self, k, to_num(value))
            return
        if k == "visible":
            self.visible = to_bool(value)
            return
        if k in self._STR_ATTRS:
            setattr(self, self._STR_ATTRS[k], to_str(value))
            return
        super().set(k, value)

    # -- tree -----------------------------------------------------------

    def add_child(self, child: "GuiControl") -> None:
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: "GuiControl") -> None:
        if child in self.children:
            self.children.remove(child)
        if child.parent is self:
            child.parent = None

    def effective_offset(self) -> Tuple[float, float]:
        """Extra (dx, dy) from ancestor GuiScrollCtrl scroll state (see
        GuiScrollCtrl) -- composes across nested scroll regions."""
        ox = oy = 0.0
        p = self.parent
        while p is not None:
            if isinstance(p, GuiScrollCtrl):
                ox -= p.scroll_x
                oy -= p.scroll_y
            p = p.parent
        return ox, oy

    def rect(self) -> pygame.Rect:
        ox, oy = self.effective_offset()
        return pygame.Rect(int(self.x + ox), int(self.y + oy),
                           int(self.width), int(self.height))

    def fire_action(self, *args) -> bool:
        """Invoke the script-assigned `onAction` handler (a bound
        `vm.call(...)` closure -- see module docstring point 2). Returns
        True if a handler ran."""
        handler = self.get("onaction")
        if callable(handler):
            try:
                handler(*args)
            except Exception:
                logger.exception("GS2 GUI: onAction handler for %s raised",
                                 self.ctrl_name or self.CTRL_CLASS)
            return True
        return False

    # -- render (subclasses override _draw_self) -------------------------

    def draw(self, surf: pygame.Surface, fonts, sprite_mgr=None) -> None:
        self._draw_self(surf, fonts, sprite_mgr)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        # Generic fallback for unknown/stub control classes: a plain filled
        # rect + label, so an unimplemented control is at least visible
        # instead of invisible.
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        pygame.draw.rect(surf, prof.bg, r)
        pygame.draw.rect(surf, prof.border, r, 1)
        if self.text and fonts is not None:
            label = fonts.get("small").render(self.text, True, prof.fg)
            surf.blit(label, (r.x + 4, r.y + 4))


class GuiWindowCtrl(GuiControl):
    """Frame + title bar + draggable (drag handled by GS2GuiManager)."""

    CTRL_CLASS = "GuiWindowCtrl"
    TITLE_H = 20

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 240.0, 160.0

    def titlebar_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x, r.y, r.width, min(self.TITLE_H, r.height))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        pygame.draw.rect(surf, prof.bg, r)
        pygame.draw.rect(surf, prof.border, r, 1)
        tb = self.titlebar_rect()
        pygame.draw.rect(surf, prof.title_bg, tb)
        if self.text and fonts is not None:
            label = fonts.get("small").render(self.text, True, prof.title_fg)
            surf.blit(label, (tb.x + 4, tb.y + (tb.height - label.get_height()) // 2))


class GuiButtonCtrl(GuiControl):
    """Rect + centered text; onAction fires on click (GS2GuiManager)."""

    CTRL_CLASS = "GuiButtonCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 24.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        pygame.draw.rect(surf, prof.title_bg, r, border_radius=4)
        pygame.draw.rect(surf, prof.border, r, 1, border_radius=4)
        if self.text and fonts is not None:
            label = fonts.get("small").render(self.text, True, prof.fg)
            surf.blit(label, label.get_rect(center=r.center))


class GuiTextCtrl(GuiControl):
    """A plain (non-interactive) text label."""

    CTRL_CLASS = "GuiTextCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 16.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        label = fonts.get("small").render(self.text, True, prof.fg)
        surf.blit(label, r.topleft)


class GuiMLTextCtrl(GuiControl):
    """Stub-but-track: multi-line text, rendered word-wrapped."""

    CTRL_CLASS = "GuiMLTextCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 80.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        font = fonts.get("small")
        y = r.y
        for line in _wrap_text(font, self.text, r.width):
            if y >= r.bottom:
                break
            label = font.render(line, True, prof.fg)
            surf.blit(label, (r.x, y))
            y += label.get_height()


class GuiScrollCtrl(GuiControl):
    """Clips its children to its own rect and offsets them by
    scroll_x/scroll_y (adjusted by mouse wheel -- GS2GuiManager)."""

    CTRL_CLASS = "GuiScrollCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 120.0
        self.scroll_x = 0.0
        self.scroll_y = 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        pygame.draw.rect(surf, prof.bg, r)
        pygame.draw.rect(surf, prof.border, r, 1)


class GuiTextEditCtrl(GuiControl):
    """Single-line editable text field. Enter fires onAction (GS2GuiManager
    routes focus + key/Enter handling; `.text` is the live edit buffer)."""

    CTRL_CLASS = "GuiTextEditCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 22.0
        self.focused = False
        self.max_len = 256

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        pygame.draw.rect(surf, prof.bg, r)
        pygame.draw.rect(surf, (150, 190, 255) if self.focused else prof.border,
                         r, 2 if self.focused else 1)
        if fonts is None:
            return
        font = fonts.get("small")
        label = font.render(self.text, True, prof.fg)
        surf.blit(label, (r.x + 4, r.centery - label.get_height() // 2))
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = r.x + 4 + font.size(self.text)[0]
            pygame.draw.line(surf, prof.fg, (cx, r.y + 3), (cx, r.bottom - 3), 1)


class GuiCheckBoxCtrl(GuiControl):
    """Stub-but-track: rendered as a small button with a checked state.
    `value`/`checked` alias to the same boolean (real client scripts use
    either name)."""

    CTRL_CLASS = "GuiCheckBoxCtrl"
    _BOOL_KEYS = ("value", "checked")

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
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        box = pygame.Rect(r.x, r.y, min(r.width, r.height) or 16, min(r.width, r.height) or 16)
        pygame.draw.rect(surf, prof.bg, box)
        pygame.draw.rect(surf, prof.border, box, 1)
        if self.checked:
            pygame.draw.line(surf, prof.fg, box.topleft, box.bottomright, 2)
            pygame.draw.line(surf, prof.fg, box.bottomleft, box.topright, 2)
        if self.text and fonts is not None:
            label = fonts.get("small").render(self.text, True, prof.fg)
            surf.blit(label, (box.right + 6, box.y + (box.height - label.get_height()) // 2))


class GuiRadioCtrl(GuiCheckBoxCtrl):
    """Stub-but-track: same as GuiCheckBoxCtrl visually (a filled circle
    instead of a box); real per-group mutual-exclusion is not replicated."""

    CTRL_CLASS = "GuiRadioCtrl"

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = _resolve_profile(self.profile_name)
        r = self.rect()
        d = min(r.width, r.height) or 16
        center = (r.x + d // 2, r.y + d // 2)
        pygame.draw.circle(surf, prof.bg, center, d // 2)
        pygame.draw.circle(surf, prof.border, center, d // 2, 1)
        if self.checked:
            pygame.draw.circle(surf, prof.fg, center, max(1, d // 4))
        if self.text and fonts is not None:
            label = fonts.get("small").render(self.text, True, prof.fg)
            surf.blit(label, (r.x + d + 6, r.y + (d - label.get_height()) // 2))


class GuiBitmapCtrl(GuiControl):
    """Renders an image (by filename, resolved via the game's SpriteManager)
    stretched to fit the control's rect."""

    CTRL_CLASS = "GuiBitmapCtrl"

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
        pygame.draw.rect(surf, (60, 60, 70), r)
        pygame.draw.rect(surf, (120, 120, 130), r, 1)


class GuiShowImgCtrl(GuiControl):
    """Log-once stub: no known real-world usage exercised yet."""

    CTRL_CLASS = "GuiShowImgCtrl"

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        _log_once(("draw", self.CTRL_CLASS),
                  "GS2 GUI: %s rendering not implemented (stub)", self.CTRL_CLASS)


class GuiPopUpEditCtrl(GuiControl):
    """Log-once stub: no known real-world usage exercised yet."""

    CTRL_CLASS = "GuiPopUpEditCtrl"

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        _log_once(("draw", self.CTRL_CLASS),
                  "GS2 GUI: %s rendering not implemented (stub)", self.CTRL_CLASS)


_CONTROL_CLASSES: Dict[str, type] = {
    cls.CTRL_CLASS.lower(): cls for cls in (
        GuiWindowCtrl, GuiButtonCtrl, GuiTextCtrl, GuiMLTextCtrl,
        GuiScrollCtrl, GuiTextEditCtrl, GuiCheckBoxCtrl, GuiRadioCtrl,
        GuiBitmapCtrl, GuiShowImgCtrl, GuiPopUpEditCtrl,
    )
}


def make_control(classname: str, ctor_arg: Any) -> GuiControl:
    cls = _CONTROL_CLASSES.get(classname.lower())
    if cls is None:
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

    @property
    def keyboard_captured(self) -> bool:
        """True while a text-edit control holds keyboard focus, so gameplay
        held-key movement must not run alongside typing."""
        return self._focus is not None

    # -- construction --------------------------------------------------------

    def create_control(self, classname: str, ctor_arg: Any) -> GuiControl:
        ctrl = make_control(classname, ctor_arg)
        if ctrl.ctrl_name:
            self._named[ctrl.ctrl_name.lower()] = ctrl
        if self._construction_stack:
            self._construction_stack[-1].add_child(ctrl)
        self._construction_stack.append(ctrl)
        return ctrl

    def addcontrol(self, ctrl: Any) -> None:
        if not isinstance(ctrl, GuiControl):
            _log_once(("addcontrol", type(ctrl).__name__),
                      "GS2 GUI: addcontrol() called on a non-control value (%r)", ctrl)
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
        """Drop keyboard focus / an active drag held by ctrl OR any of its
        descendants. Scripts close whole windows (hidegui/destroy on the
        container), so an exact-identity check would leave a vanished text
        edit holding focus — and keyboard_captured would block player
        movement with nothing visible on screen."""
        if self._focus is not None and self._is_or_descends(self._focus, ctrl):
            self._set_focus(None)
        if self._drag is not None and self._is_or_descends(self._drag[0], ctrl):
            self._drag = None

    @staticmethod
    def _is_or_descends(node: GuiControl, ancestor: GuiControl) -> bool:
        while node is not None:
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

    # -- render ---------------------------------------------------------

    def render(self, surf: pygame.Surface, fonts=None, sprite_mgr=None) -> None:
        self._reap_construction_leak()
        for root in self.roots:
            self._draw_node(root, surf, fonts, sprite_mgr, None)
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
        while p is not None:
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

        self._set_focus(None)
        if isinstance(hit, GuiCheckBoxCtrl):           # covers GuiRadioCtrl too
            hit.toggle()
            hit.fire_action()
        elif isinstance(hit, GuiButtonCtrl):
            hit.fire_action()
        return True

    def _on_mouse_up(self, pos) -> bool:
        if self._drag is not None:
            self._drag = None
            return True
        return self.hit_test(pos) is not None

    def _on_mouse_move(self, pos) -> bool:
        if self._drag is None:
            return False
        win, off_x, off_y = self._drag
        dx = (pos[0] - off_x) - win.x
        dy = (pos[1] - off_y) - win.y
        self._shift(win, dx, dy)
        return True

    def _on_wheel(self, event) -> bool:
        pos = getattr(event, "pos", None) or pygame.mouse.get_pos()
        node = self.hit_test(pos)
        while node is not None and not isinstance(node, GuiScrollCtrl):
            node = node.parent
        if node is None:
            return False
        node.scroll_y = max(0.0, node.scroll_y - event.y * 20.0)
        return True

    def _on_keydown(self, event) -> bool:
        if event.key == pygame.K_ESCAPE:
            top = self._topmost_window()
            if top is not None:
                self.hide(top)
                return True
            return False
        if self._focus is None:
            return False
        if event.key == pygame.K_RETURN:
            self._focus.fire_action()
            return True
        if event.key == pygame.K_BACKSPACE:
            self._focus.text = self._focus.text[:-1]
            return True
        if event.unicode and event.unicode.isprintable():
            if len(self._focus.text) < self._focus.max_len:
                self._focus.text += event.unicode
        return True
