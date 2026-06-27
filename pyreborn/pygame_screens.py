"""Pygame UI screens for pyreborn: login, server select, loading.

Rebuilt on the game.ui widget toolkit + the resolution-independent Viewport, so
these screens are resizable and share the client's look. The old version
hand-managed an `active_field` string, per-field `_handle_char`/`_handle_backspace`
branches, manual cursor blinking and a wall of magic x/y numbers; all of that is
now handled by TextInput / Button / Panel widgets with anchor-based layout.

Public API is unchanged:
    LoginScreen().run() -> dict | None
    ServerSelectScreen(servers, username).run() -> ServerEntry | None
    show_loading_screen(message)
"""

from typing import Optional

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION,
    K_ESCAPE, K_TAB, K_RETURN, K_UP, K_DOWN, K_SPACE,
)

from .listserver import ServerEntry
from .game.viewport import Viewport
from .game.assets import FontManager
from .game import ui

SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480
BG = (22, 28, 44)


class _Screen:
    """Shared boilerplate: resizable viewport, font/UI managers, event pump.

    Subclasses build their widget tree in `build()` and may set `self._result`
    (and `self._done = True`) from widget callbacks to finish the loop.
    """

    caption = "pyreborn"

    def __init__(self):
        if not pygame.get_init():
            pygame.init()
        self.viewport = Viewport(SCREEN_WIDTH, SCREEN_HEIGHT, caption=self.caption,
                                 bg=(0, 0, 0))
        self.canvas = self.viewport.canvas
        self.fonts = FontManager()
        self.ui = ui.UIManager(self.fonts, SCREEN_WIDTH, SCREEN_HEIGHT)
        self.clock = pygame.time.Clock()
        self._result = None
        self._done = False

    # subclass hooks
    def build(self):
        ...

    def on_key(self, event):
        ...

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
                    return None
                if event.type == pygame.VIDEORESIZE:
                    self.viewport.handle_resize(event.w, event.h)
                    continue
                if event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return None
                    if event.key == K_TAB:
                        self.ui.focus_next()
                        continue
                    self.on_key(event)
                if self.ui.handle_event(self._remap(event)):
                    continue
            self.ui.update(self.viewport.mouse_pos())
            self.canvas.fill(BG)
            self._draw_extra()
            self.ui.draw(self.canvas)
            self.viewport.present()
            self.clock.tick(60)
            if self._done:
                return self._result
        return self._result

    def _draw_extra(self):
        ...


class LoginScreen(_Screen):
    """Credential entry with listserver/direct-connect toggle."""

    caption = "pyreborn - Login"

    def __init__(self):
        super().__init__()
        self.use_listserver = True

    def build(self):
        self.error = ui.Label("", role="small", color=(255, 110, 110),
                              anchor=ui.MIDTOP, offset=(0, 0))

        self.user_in = ui.TextInput(w=300, placeholder="Username", max_len=30,
                                    on_enter=self._submit)
        self.pass_in = ui.TextInput(w=300, placeholder="Password", password=True,
                                    max_len=30, on_enter=self._submit)
        self.user_in.focused = True

        self.mode_btn = ui.Button(self._mode_text(), w=300, h=30,
                                  on_click=self._toggle_mode,
                                  bg=(40, 52, 78), bg_hover=(58, 74, 108))

        self.ls_in = ui.TextInput(w=300, placeholder="Listserver host", max_len=50,
                                  text="listserver.example.com", on_enter=self._submit)
        self.host_in = ui.TextInput(w=300, placeholder="Host", max_len=50,
                                    text="localhost", on_enter=self._submit)
        self.port_in = ui.TextInput(w=300, placeholder="Port", max_len=5,
                                    text="14900", on_enter=self._submit)

        connect = ui.Button("Connect", w=300, h=40, on_click=self._submit,
                            role="heading", bg=(48, 132, 92), bg_hover=(70, 176, 122))

        panel = ui.Panel(w=360, h=400, anchor=ui.CENTER, bg=(32, 40, 62, 245),
                         border=(70, 92, 134), radius=14, vstack=True,
                         padding=24, spacing=10)
        panel.add(
            ui.Label("pyreborn", role="title", color=(120, 190, 255)),
            ui.Label("Reborn Client", role="small", color=(150, 156, 184)),
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
            role="tiny", color=(110, 116, 140),
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


class ServerSelectScreen(_Screen):
    """Scrollable, clickable server list backed by the listserver results."""

    caption = "pyreborn - Server Select"
    MAX_VISIBLE = 7
    ROW_H = 40

    # type_prefix -> (badge color)
    TYPE_COLORS = {
        "H ": (205, 150, 70), "P ": (255, 215, 0),
        "3 ": (110, 200, 255), "U ": (120, 120, 130),
    }

    def __init__(self, servers: list, username: str):
        super().__init__()
        self.servers = servers
        self.username = username
        self.selected = 0
        self.scroll = 0

    def build(self):
        self.ui.root.add(
            ui.Label("Select Server", role="title", anchor=ui.MIDTOP, offset=(0, 18)),
            ui.Label(f"Logged in as {self.username}  ·  {len(self.servers)} servers",
                     role="small", color=(150, 200, 255),
                     anchor=ui.MIDTOP, offset=(0, 64)),
            ui.Label("Up/Down: navigate   Enter: connect   Esc: cancel",
                     role="tiny", color=(110, 116, 140),
                     anchor=ui.MIDBOTTOM, offset=(0, -12)),
        )
        self.list_panel = ui.Panel(w=SCREEN_WIDTH - 60, h=self.MAX_VISIBLE * (self.ROW_H + 4),
                                   anchor=ui.MIDTOP, offset=(0, 98),
                                   vstack=True, padding=0, spacing=4, align=ui.CENTER)
        self.ui.root.add(self.list_panel)
        self.scroll_hint = ui.Label("", role="tiny", color=(110, 150, 200),
                                    anchor=ui.MIDBOTTOM, offset=(0, -32))
        self.ui.root.add(self.scroll_hint)
        self._refresh_rows()

    def _refresh_rows(self):
        self.list_panel.clear()
        visible = self.servers[self.scroll:self.scroll + self.MAX_VISIBLE]
        for i, server in enumerate(visible):
            idx = self.scroll + i
            self.list_panel.add(self._make_row(server, idx == self.selected, idx))
        above = self.scroll > 0
        below = self.scroll + self.MAX_VISIBLE < len(self.servers)
        self.scroll_hint.text = ("^ more above   " if above else "") + \
                                ("v more below" if below else "")

    def _make_row(self, server, selected, idx):
        row = ui.Panel(w=SCREEN_WIDTH - 80, h=self.ROW_H,
                       bg=(48, 64, 96) if selected else (30, 40, 60),
                       border=(110, 160, 255) if selected else None,
                       border_w=2, radius=6)
        row.add(ui.Label(server.name, role="hud", color=(255, 255, 255),
                         anchor=ui.TOPLEFT, offset=(12, 5)))
        info = f"{server.player_count} players   {server.language}   {server.ip}:{server.port}"
        row.add(ui.Label(info, role="tiny", color=(160, 166, 186),
                         anchor=ui.TOPLEFT, offset=(12, 25)))
        badge = server.type_prefix.strip()
        if badge:
            color = self.TYPE_COLORS.get(server.type_prefix, (120, 120, 130))
            row.add(ui.Label(badge, role="small", color=color,
                             anchor=ui.TOPRIGHT, offset=(-12, 5)))

        def pick():                      # click selects; click-again connects
            if idx == self.selected:
                self._choose()
            else:
                self.selected = idx
                self._refresh_rows()
        row.add(_ClickCatcher(SCREEN_WIDTH - 80, self.ROW_H, pick))
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
            if self.selected >= self.scroll + self.MAX_VISIBLE:
                self.scroll = self.selected - self.MAX_VISIBLE + 1
            self._refresh_rows()
        elif event.key in (K_RETURN, K_SPACE):
            self._choose()

    def _choose(self):
        if self.servers:
            self._result = self.servers[self.selected]
            self._done = True


class _ClickCatcher(ui.Widget):
    """Transparent overlay that fires a callback when clicked (for list rows)."""

    def __init__(self, w, h, on_click):
        super().__init__(w, h, anchor=ui.TOPLEFT, offset=(0, 0))
        self.on_click = on_click

    def _handle_event(self, event) -> bool:
        if event.type == MOUSEBUTTONUP and event.button == 1 \
                and self.rect.collidepoint(event.pos):
            self.on_click()
            return True
        return False


def show_loading_screen(message: str):
    """Show a simple loading screen (transient; not resizable)."""
    if not pygame.get_init():
        pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("pyreborn")
    fonts = FontManager()
    screen.fill(BG)
    text = fonts.at(36).render(message, True, (255, 255, 255))
    screen.blit(text, text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)))
    pygame.display.flip()
    pygame.event.pump()
