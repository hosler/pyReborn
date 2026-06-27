"""A small composable widget toolkit for the pygame client.

Replaces the wall of hardcoded `screen.blit(font.render(...))` calls and magic
x/y numbers that made `_render_ui` (210 lines) and the login/server screens hard
to change. Modeled on Preagonal's Gui*Ctrl composite pattern (GuiControl ->
GuiButtonCtrl/GuiTextEditCtrl/GuiScrollCtrl...): every widget is a node with a
rect, optional children, a draw step and an event step.

Layout is anchor-based. A widget pins one of its nine anchor points
(topleft..bottomright, named exactly like pygame.Rect's virtual attributes) to
the same-named point of its container, plus a pixel offset. Containers can also
auto-stack children vertically. All coordinates are *virtual* canvas pixels (see
viewport.py), so a resize never moves the layout.

Typical use:
    ui = UIManager(fonts)
    panel = Panel(w=300, h=200, anchor="center", bg=(20,24,40,230), vstack=True,
                  padding=16, spacing=8)
    panel.add(Label("Login", role="title"),
              TextInput(w=260, placeholder="account"),
              Button("Connect", on_click=do_connect))
    ui.root.add(panel)
    # per frame:
    ui.update(mouse_pos); ui.draw(canvas)
    # per event:
    ui.handle_event(event)
"""

from typing import Callable, List, Optional, Tuple

import pygame


# Anchor names double as pygame.Rect virtual attribute names.
TOPLEFT = "topleft"; MIDTOP = "midtop"; TOPRIGHT = "topright"
MIDLEFT = "midleft"; CENTER = "center"; MIDRIGHT = "midright"
BOTTOMLEFT = "bottomleft"; MIDBOTTOM = "midbottom"; BOTTOMRIGHT = "bottomright"


class Widget:
    """Base node: a rect, optional children, draw + event hooks."""

    def __init__(self, w: int = 0, h: int = 0, anchor: str = TOPLEFT,
                 offset: Tuple[int, int] = (0, 0), visible: bool = True):
        self.w = w
        self.h = h
        self.anchor = anchor
        self.offset = offset
        self.visible = visible
        self.parent: Optional["Widget"] = None
        self.children: List["Widget"] = []
        self.rect = pygame.Rect(0, 0, w, h)
        self.hover = False

    # composition -------------------------------------------------------
    def add(self, *kids: "Widget") -> "Widget":
        for k in kids:
            k.parent = self
            self.children.append(k)
        return self

    def clear(self):
        self.children.clear()

    # layout ------------------------------------------------------------
    def layout(self, container: pygame.Rect):
        """Resolve this widget's rect inside `container`, then its children."""
        r = pygame.Rect(0, 0, self.w, self.h)
        cx, cy = getattr(container, self.anchor)
        setattr(r, self.anchor, (cx + self.offset[0], cy + self.offset[1]))
        self.rect = r
        self._layout_children()

    def _layout_children(self):
        for c in self.children:
            c.layout(self.rect)

    # frame -------------------------------------------------------------
    def update(self, mouse_pos: Tuple[int, int]):
        self.hover = self.visible and self.rect.collidepoint(mouse_pos)
        for c in self.children:
            c.update(mouse_pos)

    def draw(self, surf: pygame.Surface):
        if not self.visible:
            return
        self._draw(surf)
        for c in self.children:
            c.draw(surf)

    def _draw(self, surf: pygame.Surface):
        pass

    def handle_event(self, event) -> bool:
        if not self.visible:
            return False
        for c in reversed(self.children):          # topmost child first
            if c.handle_event(event):
                return True
        return self._handle_event(event)

    def _handle_event(self, event) -> bool:
        return False


class Panel(Widget):
    """A container with optional background, border, and vertical stacking."""

    def __init__(self, w=0, h=0, anchor=TOPLEFT, offset=(0, 0), *,
                 bg=None, border=None, border_w=1, radius=0,
                 vstack=False, padding=0, spacing=4, align=CENTER, visible=True):
        super().__init__(w, h, anchor, offset, visible)
        self.bg = bg                  # (r,g,b) or (r,g,b,a) or None
        self.border = border
        self.border_w = border_w
        self.radius = radius
        self.vstack = vstack
        self.padding = padding
        self.spacing = spacing
        self.align = align            # horizontal align of stacked children

    def _layout_children(self):
        if not self.vstack:
            super()._layout_children()
            return
        y = self.rect.top + self.padding
        for c in self.children:
            if not c.visible:
                continue
            inner = pygame.Rect(self.rect.left + self.padding, y,
                                self.rect.width - 2 * self.padding, c.h)
            anchor = MIDTOP if self.align == CENTER else \
                (TOPLEFT if self.align in (TOPLEFT, MIDLEFT) else TOPRIGHT)
            saved = c.anchor
            c.anchor = anchor
            c.layout(inner)
            c.anchor = saved
            y += c.h + self.spacing

    def _draw(self, surf):
        if self.bg is not None:
            if len(self.bg) == 4:
                s = pygame.Surface(self.rect.size, pygame.SRCALPHA)
                pygame.draw.rect(s, self.bg, s.get_rect(),
                                 border_radius=self.radius)
                surf.blit(s, self.rect.topleft)
            else:
                pygame.draw.rect(surf, self.bg, self.rect,
                                 border_radius=self.radius)
        if self.border is not None:
            pygame.draw.rect(surf, self.border, self.rect, self.border_w,
                             border_radius=self.radius)


class Label(Widget):
    """A line (or block) of text rendered via FontManager."""

    def __init__(self, text="", *, role="hud", color=(255, 255, 255),
                 anchor=TOPLEFT, offset=(0, 0), align=TOPLEFT, shadow=False,
                 visible=True):
        super().__init__(0, 0, anchor, offset, visible)
        self.role = role
        self.color = color
        self.align = align
        self.shadow = shadow
        self._fonts = None             # injected by UIManager.bind()
        self._text = text
        self._surf: Optional[pygame.Surface] = None
        self._cache_key = None

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value

    def _ensure_surface(self):
        key = (self._text, self.role, self.color)
        if key != self._cache_key and self._fonts is not None:
            self._surf = self._fonts.get(self.role).render(
                self._text, True, self.color)
            self.w, self.h = self._surf.get_size()
            self._cache_key = key

    def layout(self, container):
        self._ensure_surface()
        super().layout(container)

    def _draw(self, surf):
        if self._surf is None:
            return
        if self.shadow:
            sh = self._fonts.get(self.role).render(self._text, True, (0, 0, 0))
            surf.blit(sh, (self.rect.x + 1, self.rect.y + 1))
        surf.blit(self._surf, self.rect.topleft)


class Image(Widget):
    """Blits a provided pygame.Surface (icons, sprites, panels)."""

    def __init__(self, surface: pygame.Surface, *, anchor=TOPLEFT, offset=(0, 0),
                 visible=True):
        w, h = surface.get_size() if surface else (0, 0)
        super().__init__(w, h, anchor, offset, visible)
        self.surface = surface

    def set_surface(self, surface):
        self.surface = surface
        if surface:
            self.w, self.h = surface.get_size()

    def _draw(self, surf):
        if self.surface:
            surf.blit(self.surface, self.rect.topleft)


class Button(Widget):
    """Text button with hover/press states and an on_click callback."""

    def __init__(self, text="", *, on_click: Optional[Callable] = None,
                 w=140, h=32, role="hud", anchor=TOPLEFT, offset=(0, 0),
                 bg=(50, 56, 78), bg_hover=(72, 82, 120), bg_disabled=(40, 42, 50),
                 fg=(235, 238, 245), radius=6, enabled=True, visible=True):
        super().__init__(w, h, anchor, offset, visible)
        self.text = text
        self.on_click = on_click
        self.role = role
        self.bg = bg
        self.bg_hover = bg_hover
        self.bg_disabled = bg_disabled
        self.fg = fg
        self.radius = radius
        self.enabled = enabled
        self._pressed = False
        self._fonts = None

    def _draw(self, surf):
        if not self.enabled:
            color = self.bg_disabled
        elif self._pressed and self.hover:
            color = self.bg_hover
        elif self.hover:
            color = self.bg_hover
        else:
            color = self.bg
        pygame.draw.rect(surf, color, self.rect, border_radius=self.radius)
        if self._fonts is not None and self.text:
            label = self._fonts.get(self.role).render(
                self.text, True, self.fg if self.enabled else (130, 130, 138))
            surf.blit(label, label.get_rect(center=self.rect.center))

    def _handle_event(self, event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = True
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = self._pressed
            self._pressed = False
            if was and self.rect.collidepoint(event.pos):
                if self.on_click:
                    self.on_click()
                return True
        return False


class TextInput(Widget):
    """Single-line editable text field with focus, cursor, and masking."""

    def __init__(self, *, w=240, h=32, role="hud", anchor=TOPLEFT, offset=(0, 0),
                 text="", placeholder="", password=False, max_len=64,
                 on_enter: Optional[Callable] = None,
                 bg=(28, 30, 42), bg_focus=(40, 44, 62),
                 fg=(235, 238, 245), border=(90, 96, 120),
                 border_focus=(120, 170, 255), radius=5, visible=True):
        super().__init__(w, h, anchor, offset, visible)
        self.role = role
        self.text = text
        self.placeholder = placeholder
        self.password = password
        self.max_len = max_len
        self.on_enter = on_enter
        self.bg = bg
        self.bg_focus = bg_focus
        self.fg = fg
        self.border = border
        self.border_focus = border_focus
        self.radius = radius
        self.focused = False
        self._fonts = None
        self._blink = 0.0

    @property
    def display_text(self):
        return "*" * len(self.text) if self.password else self.text

    def _draw(self, surf):
        pygame.draw.rect(surf, self.bg_focus if self.focused else self.bg,
                         self.rect, border_radius=self.radius)
        pygame.draw.rect(surf, self.border_focus if self.focused else self.border,
                         self.rect, 2 if self.focused else 1,
                         border_radius=self.radius)
        if self._fonts is None:
            return
        font = self._fonts.get(self.role)
        if self.text:
            label = font.render(self.display_text, True, self.fg)
        else:
            label = font.render(self.placeholder, True, (120, 124, 140))
        surf.blit(label, (self.rect.x + 8,
                          self.rect.centery - label.get_height() // 2))
        # blinking caret
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = self.rect.x + 8 + (font.size(self.display_text)[0]
                                    if self.text else 0)
            pygame.draw.line(surf, self.fg, (cx, self.rect.y + 6),
                             (cx, self.rect.bottom - 6), 1)

    def _handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.focused = self.rect.collidepoint(event.pos)
            return self.focused
        if not self.focused or event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_RETURN:
            if self.on_enter:
                self.on_enter()
        elif event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        elif event.key == pygame.K_TAB:
            return False                # let the manager advance focus
        elif event.unicode and event.unicode.isprintable():
            if len(self.text) < self.max_len:
                self.text += event.unicode
        return True


class UIManager:
    """Owns a root widget; binds the font manager into widgets; drives frames."""

    def __init__(self, fonts, root_w: int, root_h: int):
        self.fonts = fonts
        self.root = Widget(root_w, root_h)
        self._root_rect = pygame.Rect(0, 0, root_w, root_h)

    def _bind(self, w: Widget):
        if hasattr(w, "_fonts"):
            w._fonts = self.fonts
        for c in w.children:
            self._bind(c)

    def layout(self):
        self._bind(self.root)
        self.root.layout(self._root_rect)

    def update(self, mouse_pos):
        self.layout()                  # cheap; keeps text/anchors fresh
        self.root.update(mouse_pos)

    def draw(self, surf):
        self.root.draw(surf)

    def handle_event(self, event) -> bool:
        return self.root.handle_event(event)

    def focus_next(self):
        """Cycle keyboard focus among TextInputs (Tab support)."""
        inputs = []

        def collect(w):
            if isinstance(w, TextInput) and w.visible:
                inputs.append(w)
            for c in w.children:
                collect(c)
        collect(self.root)
        if not inputs:
            return
        idx = next((i for i, t in enumerate(inputs) if t.focused), -1)
        for t in inputs:
            t.focused = False
        inputs[(idx + 1) % len(inputs)].focused = True
