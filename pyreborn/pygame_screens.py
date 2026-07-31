"""Pygame UI screens for pyreborn: login, server select, loading.

Built on the game.ui widget toolkit + the resolution-independent Viewport, so
these screens are resizable and share the client's look.

Both screens render **native** (viewport `native=True`): the canvas IS the
window at its real size, not a fixed 640x480 canvas letterbox-scaled into
whatever the window manager forces the window to. On tiling WMs the window
gets resized to something large by the WM itself, and the old scaled mode put
a small login box in a sea of black bars. Native mode fills the window and
re-centers content on resize via anchor layout (game/ui.py's UIManager).
Content columns (login panel, server list) are capped at a sensible max width
so they do not stretch edge-to-edge on an ultrawide window.

Public API is unchanged:
    LoginScreen().run() -> dict | None
    ServerSelectScreen(servers, username).run() -> ServerEntry | None
    show_loading_screen(message)
"""

from typing import Optional

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION, MOUSEWHEEL,
    K_ESCAPE, K_TAB, K_RETURN, K_UP, K_DOWN, K_SPACE,
)

from .listserver import ServerEntry
from .prefs import Prefs
from .game.viewport import Viewport
from .game.assets import FontManager
from .game import theme
from .game import ui

# Initial/default window size (overridden by prefs.window_w/h once saved).
DEFAULT_WINDOW_W = 1024
DEFAULT_WINDOW_H = 720
MIN_WINDOW_W = 640
MIN_WINDOW_H = 480
BG = theme.NIGHT


class _Screen:
    """Shared boilerplate: native resizable viewport, font/UI managers, event pump.

    Subclasses build their widget tree in `build()` and may set `self._result`
    (and `self._done = True`) from widget callbacks to finish the loop. Override
    `on_resize(w, h)` to re-layout anything whose size depends on window width
    (e.g. a list column layout) beyond what anchor-based UI re-centering already
    handles for free.
    """

    caption = "pyreborn"

    def __init__(self, prefs: Optional[Prefs] = None):
        if not pygame.get_init():
            pygame.init()
        self.prefs = prefs if prefs is not None else Prefs.load()
        w = max(MIN_WINDOW_W, self.prefs.window_w or DEFAULT_WINDOW_W)
        h = max(MIN_WINDOW_H, self.prefs.window_h or DEFAULT_WINDOW_H)
        self.viewport = Viewport(w, h, window_w=w, window_h=h, caption=self.caption,
                                 bg=(0, 0, 0), native=True, on_resize=self._on_viewport_resize)
        self.canvas = self.viewport.canvas
        self.fonts = FontManager()
        self.ui = ui.UIManager(self.fonts, w, h)
        self.clock = pygame.time.Clock()
        self._result = None
        self._done = False

    # subclass hooks
    def build(self):
        ...

    def on_key(self, event):
        ...

    def on_scroll(self, dy: int):
        ...

    def on_resize(self, w: int, h: int):
        ...

    # -- resize plumbing ----------------------------------------------------

    def _on_viewport_resize(self, w: int, h: int):
        """Viewport callback (native mode): re-anchor the widget tree, then let
        the subclass re-flow anything width-dependent (list columns etc.)."""
        self.ui.resize(w, h)
        self.on_resize(w, h)

    def content_width(self, w: int, *, minimum: int = 560, maximum: int = 1040,
                      margin: int = 48) -> int:
        """A sensible column width for this window size: fills most of a
        narrow window but is capped so it does not stretch edge-to-edge on an
        ultrawide monitor."""
        return max(minimum, min(maximum, w - 2 * margin))

    # mouse events carry window coords; widgets work in virtual canvas coords
    def _remap(self, event):
        if event.type in (MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION):
            vx, vy = self.viewport.window_to_virtual(*event.pos)
            return pygame.event.Event(event.type,
                                      {**event.dict, "pos": (int(vx), int(vy))})
        return event

    def run(self):
        self.build()
        while not self._done:
            for event in pygame.event.get():
                if event.type == QUIT:
                    return self._finish(None)
                if event.type == pygame.VIDEORESIZE:
                    self.viewport.handle_resize(event.w, event.h)
                    continue
                if event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return self._finish(None)
                    if event.key == K_TAB:
                        self.ui.focus_next()
                        continue
                    self.on_key(event)
                if event.type == MOUSEWHEEL:
                    self.on_scroll(event.y)
                if self.ui.handle_event(self._remap(event)):
                    continue
            self.ui.update(self.viewport.mouse_pos())
            self.canvas.fill(BG)
            self._draw_extra()
            self.ui.draw(self.canvas)
            self.viewport.present()
            self.clock.tick(60)
            if self._done:
                return self._finish(self._result)
        return self._finish(self._result)

    def _draw_extra(self):
        ...

    def _finish(self, result):
        """Persist the (possibly resized) window size on the way out, whether
        the user completed the flow or cancelled/quit."""
        try:
            w, h = self.viewport.window.get_size()
            self.prefs.remember_window_size(w, h)
        except Exception:
            pass
        return result


class LoginScreen(_Screen):
    """Credential entry with listserver/direct-connect toggle."""

    caption = "pyreborn - Login"

    def __init__(self, prefs: Optional[Prefs] = None):
        super().__init__(prefs)
        self.use_listserver = self.prefs.use_listserver

    def build(self):
        self.error = ui.Label("", role="small", color=theme.ERROR,
                              anchor=ui.MIDTOP, offset=(0, 0))

        self.user_in = ui.TextInput(w=300, placeholder="Username", max_len=30,
                                    text=self.prefs.username, on_enter=self._submit)
        self.pass_in = ui.TextInput(w=300, placeholder="Password", password=True,
                                    max_len=30, text=self.prefs.password,
                                    on_enter=self._submit)
        self.user_in.focused = True

        self.mode_btn = ui.Button(self._mode_text(), w=300, h=30,
                                  on_click=self._toggle_mode)

        self.ls_in = ui.TextInput(w=300, placeholder="Listserver host", max_len=50,
                                  text=self.prefs.listserver_host, on_enter=self._submit)
        self.host_in = ui.TextInput(w=300, placeholder="Host", max_len=50,
                                    text=self.prefs.host, on_enter=self._submit)
        self.port_in = ui.TextInput(w=300, placeholder="Port", max_len=5,
                                    text=str(self.prefs.port), on_enter=self._submit)

        connect = ui.Button("Connect", w=300, h=40, on_click=self._submit,
                            role="heading", bg=theme.PRIMARY_BG,
                            bg_hover=theme.PRIMARY_HOVER, border=None)

        panel = ui.Panel(w=380, h=460, anchor=ui.CENTER, bg=theme.PANEL_BG,
                         border=theme.PANEL_BORDER, radius=14, vstack=True,
                         padding=24, spacing=10)
        logo = theme.emblem(2)
        if logo is not None:
            panel.add(ui.Image(logo))
        panel.add(
            ui.Label("pyreborn", role="title", color=theme.MINT),
            ui.Label("Reborn Client", role="small", color=theme.TEXT_DIM),
            self.user_in,
            self.pass_in,
            self.mode_btn,
            self.ls_in,
            self.host_in,
            self.port_in,
            connect,
            self.error,
        )
        self.ui.root.add(panel)
        self.ui.root.add(ui.Label(
            "Tab: next field   Enter: connect   Esc: quit",
            role="tiny", color=theme.TEXT_FAINT,
            anchor=ui.MIDBOTTOM, offset=(0, -12)))
        self._apply_mode()

    def _mode_text(self):
        return "Mode: Listserver" if self.use_listserver else "Mode: Direct connect"

    def _toggle_mode(self):
        self.use_listserver = not self.use_listserver
        self.mode_btn.text = self._mode_text()
        self._apply_mode()

    def _apply_mode(self):
        self.ls_in.visible = self.use_listserver
        self.host_in.visible = not self.use_listserver
        self.port_in.visible = not self.use_listserver

    def _submit(self):
        if not (self.user_in.text and self.pass_in.text):
            self.error.text = "Username and password required"
            return
        port = self.port_in.text
        self._result = {
            "username": self.user_in.text,
            "password": self.pass_in.text,
            "use_listserver": self.use_listserver,
            "host": self.host_in.text or "localhost",
            "port": int(port) if port.isdigit() else 14900,
            "listserver_host": self.ls_in.text,
        }
        self._done = True


# type_prefix -> (friendly badge text, color). See listserver.py's
# _send_init_packet comment / the C++ serverlist server's ServerConnection::getType() for
# where these come from: G3D->"3 ", Gold->"P ", Bronze->"H ", Hidden->"U ".
BADGE_INFO = {
    "H ": ("BRONZE", (205, 150, 70)),
    "P ": ("GOLD", (255, 215, 0)),
    "3 ": ("3D", (110, 200, 255)),
    "U ": ("HIDDEN", (150, 150, 165)),
}


class _ServerRow(ui.Panel):
    """One row in the server list. Owns its own click handling (selects on
    first click, connects on a second click while already selected) and reads
    hover/selected state live in `_draw` so highlighting works every frame
    without rebuilding the row."""

    def __init__(self, w, h, on_click):
        super().__init__(w=w, h=h, border_w=2, radius=6)
        self.selected = False
        self.on_click = on_click
        self.unresolved = False

    def _draw(self, surf):
        if self.selected:
            self.bg, self.border = theme.BUTTON_BG, theme.MINT
        elif self.hover:
            self.bg, self.border = theme.SURFACE_RAISED, theme.MOSS
        else:
            self.bg, self.border = theme.SURFACE, None
        super()._draw(surf)

    def _handle_event(self, event) -> bool:
        if event.type == MOUSEBUTTONUP and event.button == 1 \
                and self.rect.collidepoint(event.pos):
            self.on_click()
            return True
        return False


class ServerSelectScreen(_Screen):
    """Scrollable, clickable server list backed by the listserver results.

    Shows every server the listserver returned (name + type badge, player
    count, version, truncated description), sorted by player count
    descending, with a header row and a servers/players summary line. Mouse
    wheel and Up/Down scroll. Click selects, clicking the already-selected
    row connects.
    """

    caption = "pyreborn - Server Select"
    ROW_H = 42
    ROW_SPACING = 4
    LIST_TOP_Y = 134
    BOTTOM_MARGIN = 54

    BADGE_W = 66
    PLAYERS_RIGHT = 148   # right edge of the players column, from row's right edge
    VERSION_RIGHT = 12    # right edge of the version column, from row's right edge

    def __init__(self, servers: list, username: str, prefs: Optional[Prefs] = None):
        super().__init__(prefs)
        self.username = username
        # Sort by player count descending (stable -> ties keep listserver order).
        self.servers = sorted(servers, key=lambda s: -getattr(s, "player_count", 0))
        self.selected = 0
        self.scroll = 0
        self.content_w = 800
        self.max_visible = 7
        self._preselect_last_server()

    def _preselect_last_server(self):
        """If the last-used server (from prefs) is still in this list,
        preselect it and scroll it into view instead of defaulting to row 0."""
        last = self.prefs.last_server
        if not last or not self.servers:
            return
        for i, s in enumerate(self.servers):
            if last.matches(s):
                self.selected = i
                self.scroll = max(0, i - self.max_visible // 2)
                return

    # -- layout ---------------------------------------------------------

    def _recalc_layout(self, w: int, h: int):
        self.content_w = self.content_width(w, minimum=560, maximum=1080, margin=40)
        available_h = h - self.LIST_TOP_Y - self.BOTTOM_MARGIN
        self.max_visible = max(3, available_h // (self.ROW_H + self.ROW_SPACING))
        max_scroll = max(0, len(self.servers) - self.max_visible)
        self.scroll = min(self.scroll, max_scroll)

    def on_resize(self, w, h):
        self._recalc_layout(w, h)
        if hasattr(self, "list_panel"):
            self.list_panel.w = self.content_w
            self.list_panel.h = self.max_visible * (self.ROW_H + self.ROW_SPACING)
            self.header_row.w = self.content_w
            self._refresh_rows()

    def build(self):
        w, h = self.ui.root.w, self.ui.root.h
        self._recalc_layout(w, h)

        total_players = sum(getattr(s, "player_count", 0) for s in self.servers)
        unresolved = sum(1 for s in self.servers if getattr(s, "ip", "") == "$AUTO")
        summary = f"{len(self.servers)} servers  ·  {total_players} players online"
        if unresolved:
            summary += f"  ·  {unresolved} unresolved"

        title_row = ui.Panel(w=360, h=44, anchor=ui.MIDTOP, offset=(0, 8))
        crest = theme.emblem(1)
        if crest is not None:
            title_row.add(ui.Image(crest, anchor=ui.MIDLEFT, offset=(0, 0)),
                          ui.Image(crest, anchor=ui.MIDRIGHT, offset=(0, 0)))
        title_row.add(ui.Label("Select Server", role="title", color=theme.MINT_PALE,
                               anchor=ui.MIDTOP, offset=(0, 0)))
        self.ui.root.add(
            title_row,
            ui.Label(f"Logged in as {self.username}", role="small",
                     color=theme.MINT, anchor=ui.MIDTOP, offset=(0, 58)),
            ui.Label(summary, role="tiny", color=theme.TEXT_DIM,
                     anchor=ui.MIDTOP, offset=(0, 84)),
            ui.Label("Up/Down: navigate   Wheel: scroll   Enter: connect   Esc: cancel",
                     role="tiny", color=theme.TEXT_FAINT,
                     anchor=ui.MIDBOTTOM, offset=(0, -12)),
        )

        self.header_row = ui.Panel(w=self.content_w, h=22, anchor=ui.MIDTOP,
                                   offset=(0, self.LIST_TOP_Y - 28))
        self.header_row.add(
            ui.Label("SERVER", role="tiny", color=theme.TEXT_FAINT,
                     anchor=ui.TOPLEFT, offset=(self.BADGE_W, 2)),
            ui.Label("PLAYERS", role="tiny", color=theme.TEXT_FAINT,
                     anchor=ui.TOPRIGHT, offset=(-self.PLAYERS_RIGHT, 2)),
            ui.Label("VERSION", role="tiny", color=theme.TEXT_FAINT,
                     anchor=ui.TOPRIGHT, offset=(-self.VERSION_RIGHT, 2)),
        )
        self.ui.root.add(self.header_row)

        self.list_panel = ui.Panel(w=self.content_w,
                                   h=self.max_visible * (self.ROW_H + self.ROW_SPACING),
                                   anchor=ui.MIDTOP, offset=(0, self.LIST_TOP_Y),
                                   vstack=True, padding=0, spacing=self.ROW_SPACING,
                                   align=ui.CENTER)
        self.ui.root.add(self.list_panel)

        self.scroll_hint = ui.Label("", role="tiny", color=theme.EMERALD_BRIGHT,
                                    anchor=ui.MIDBOTTOM, offset=(0, -32))
        self.ui.root.add(self.scroll_hint)
        self._refresh_rows()

    def _refresh_rows(self):
        self.list_panel.clear()
        visible = self.servers[self.scroll:self.scroll + self.max_visible]
        for i, server in enumerate(visible):
            idx = self.scroll + i
            self.list_panel.add(self._make_row(server, idx == self.selected, idx))
        above = self.scroll > 0
        below = self.scroll + self.max_visible < len(self.servers)
        self.scroll_hint.text = ("^ more above   " if above else "") + \
                                ("v more below" if below else "")

    def _truncate(self, text: str, max_w: int) -> str:
        if not text:
            return text
        font = self.fonts.get("tiny")
        if font.size(text)[0] <= max_w:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.size(text[:mid] + "...")[0] <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "..." if lo > 0 else ""

    def _make_row(self, server, selected, idx):
        def pick():                      # click selects; click-again connects
            if idx == self.selected:
                self._choose()
            else:
                self.selected = idx
                self._refresh_rows()

        row = _ServerRow(self.content_w, self.ROW_H, pick)
        row.selected = selected

        badge_text, badge_color = BADGE_INFO.get(server.type_prefix, (None, None))
        if badge_text:
            row.add(ui.Label(badge_text, role="tiny", color=badge_color,
                             anchor=ui.TOPLEFT, offset=(10, 5)))

        row.add(ui.Label(server.name, role="small", color=theme.TEXT,
                         anchor=ui.TOPLEFT, offset=(self.BADGE_W, 3)))

        unresolved = getattr(server, "ip", "") == "$AUTO"
        desc_w = self.content_w - self.BADGE_W - 20
        desc = server.description or ""
        if unresolved:
            desc = "[unresolved: $AUTO placeholder] " + desc
        row.add(ui.Label(self._truncate(desc, desc_w), role="tiny",
                         color=theme.ERROR_DIM if unresolved else theme.TEXT_DIM,
                         anchor=ui.TOPLEFT, offset=(self.BADGE_W, 23)))

        row.add(ui.Label(str(server.player_count), role="tiny",
                         color=theme.MINT if server.player_count else theme.TEXT_FAINT,
                         anchor=ui.TOPRIGHT, offset=(-self.PLAYERS_RIGHT, 3)))

        version = server.version or ""
        row.add(ui.Label(self._truncate(version, 110), role="tiny",
                         color=theme.TEXT_DIM,
                         anchor=ui.TOPRIGHT, offset=(-self.VERSION_RIGHT, 3)))

        return row

    def on_key(self, event):
        if not self.servers:
            return
        if event.key == K_UP:
            self.selected = max(0, self.selected - 1)
            if self.selected < self.scroll:
                self.scroll = self.selected
            self._refresh_rows()
        elif event.key == K_DOWN:
            self.selected = min(len(self.servers) - 1, self.selected + 1)
            if self.selected >= self.scroll + self.max_visible:
                self.scroll = self.selected - self.max_visible + 1
            self._refresh_rows()
        elif event.key in (K_RETURN, K_SPACE):
            self._choose()

    def on_scroll(self, dy: int):
        if not self.servers:
            return
        max_scroll = max(0, len(self.servers) - self.max_visible)
        # Wheel up (dy>0) scrolls the list up (toward earlier rows).
        self.scroll = max(0, min(max_scroll, self.scroll - dy))
        self._refresh_rows()

    def _choose(self):
        if self.servers:
            self._result = self.servers[self.selected]
            self.prefs.remember_server(self._result)
            self._done = True


def show_loading_screen(message: str, size=None):
    """Show a simple loading screen (transient. Not resizable)."""
    if not pygame.get_init():
        pygame.init()
    w, h = size or (DEFAULT_WINDOW_W, DEFAULT_WINDOW_H)
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("pyreborn")
    fonts = FontManager()
    screen.fill(BG)
    logo = theme.emblem(2)
    if logo is not None:
        screen.blit(logo, logo.get_rect(midbottom=(w // 2, h // 2 - 24)))
    text = fonts.at(36).render(message, True, theme.TEXT)
    screen.blit(text, text.get_rect(center=(w // 2, h // 2 + 24)))
    pygame.display.flip()
    pygame.event.pump()
