"""game/dev_ui.py — the F12 dev playground panel for world creators.

Companion to the F10 RC panel and the F11 level editor. Where RC administers
the SERVER, this edits the WORLD: the scripts behind NPCs, weapons and
classes, plus a console for running script code on the spot.

It owns the NC (NPC Control) connection, which is a THIRD login next to the
game and RC ones — NC is its own client type in this protocol, exactly as RC
is (see rc_link.py's module docstring for why control connections cannot ride
the game socket). `NCLink` runs it on a worker thread; the panel only ever
reads snapshots and queues commands.

Tabs:
    NPCs      the current level's NPCs: select, edit script, save, delete
    Weapons   the server's weapon list: fetch, edit, save, delete
    Classes   script classes, same cycle
    Console   type script code, run it on a scratch NPC, read the output
    Level     level list plus save/reload of the level being edited

Editing rule for every script tab: the buffer is only pushed to the server on
an explicit Ctrl+S. Selecting another entry with unsaved changes asks first —
a script here is somebody's live world content, and silently dropping an edit
is as bad as silently sending one.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import pygame
from pygame.locals import (
    K_ESCAPE, K_F12, K_RETURN, K_TAB, K_DOWN, K_UP, KMOD_CTRL, KMOD_SHIFT,
)

from . import theme
from .text_editor import TextBuffer, TextEditor
from ..nc_link import CLOSED, CONNECTING, DENIED, ERROR, READY, NCLink

TABS = ("NPCs", "Weapons", "Classes", "Console", "Level")

PANEL_MARGIN = 24
PAD = 14
LINE_H = 18
LIST_W = 200


class DevOverlay:
    """The F12 panel: script editing and the script console."""

    def __init__(self, game):
        self.game = game
        self.visible = False
        self.tab = 0
        self.selected = [0] * len(TABS)
        self.nc_link: Optional[NCLink] = None
        self.editor = TextEditor(TextBuffer(), visible_lines=20)
        self.console = TextEditor(TextBuffer(), visible_lines=8)
        self.output: List[str] = []
        self.message = ""
        self.focus_editor = False
        # What the buffer currently holds: ("npc", id) / ("weapon", name) /
        # ("class", name), or None when nothing is loaded.
        self.loaded: Optional[Tuple[str, object]] = None
        self.confirm: Optional[Tuple[str, Callable[[], None]]] = None
        self._primed = set()

    # -- lifecycle --------------------------------------------------------

    def toggle(self) -> None:
        if self.visible:
            self.close()
            return
        self.visible = True
        self._ensure_link()
        self._prime_tab()

    def close(self) -> None:
        self.visible = False
        self.focus_editor = False
        self.confirm = None

    def shutdown(self) -> None:
        if self.nc_link is not None:
            self.nc_link.close()
            self.nc_link = None

    def _ensure_link(self) -> None:
        if self.nc_link is not None:
            if self.nc_link.state != DENIED:
                self.nc_link.start()
            return
        client = self.game.client
        password = getattr(self.game, 'rc_password', None)
        if not password:
            self.message = ("No password in this session — start the client "
                            "with a login to use the dev tools.")
            return
        self.nc_link = NCLink(client.host, client.port,
                              client.player.account, password,
                              version=client.version)
        self.nc_link.start()

    @property
    def available(self) -> bool:
        return self.nc_link is not None and self.nc_link.available

    @property
    def rc(self):
        """The RC link the F10 panel owns; the console and save go through it."""
        rc_ui = getattr(self.game, 'rc_ui', None)
        link = getattr(rc_ui, 'link', None)
        return link if link is not None and link.available else None

    def _snapshot(self):
        return self.nc_link.snapshot if self.nc_link is not None else None

    def _prime_tab(self) -> None:
        link = self.nc_link
        if link is None or not link.available:
            return
        name = TABS[self.tab]
        if name in self._primed:
            return
        if name == "Weapons":
            link.get_weapon_list()
        elif name == "Level":
            link.get_level_list()
        elif name == "NPCs":
            link.get_local_npcs(self._level_name())
        else:
            return
        self._primed.add(name)

    def _level_name(self) -> str:
        return self.game.client.get_current_level_from_position()

    # -- rows -------------------------------------------------------------

    def rows(self) -> List[str]:
        snap = self._snapshot()
        name = TABS[self.tab]
        if name == "NPCs":
            return [f"{npc_id:>5}  {self._npc_label(npc_id)}"
                    for npc_id in self._npc_ids()]
        if name == "Weapons":
            return list(snap.weapons) if snap else []
        if name == "Classes":
            return list(snap.classes) if snap else []
        if name == "Level":
            return list(snap.levels) if snap else []
        return []

    def _npc_ids(self) -> List[int]:
        """NPC ids in the level being edited, from the game connection.

        The game client already tracks every NPC the server showed it, which
        is the same set a builder can see standing in the level. The NC
        level dump is a variable listing, not a roster, so it is not the
        source for this.
        """
        client = self.game.client
        level = self._level_name()
        ids = []
        for npc_id, npc in (client.npcs or {}).items():
            if not isinstance(npc, dict):
                continue
            # `_level` is the attribution handlers/entities.py stamps on each
            # NPC; `level` is a PLAYER prop that no NPC has, so a `.get(
            # 'level', level)` test silently matched NPCs from every level
            # the client had visited.
            if npc.get('_level') == level:
                ids.append(npc_id)
        return sorted(ids)

    def _npc_label(self, npc_id: int) -> str:
        npc = (self.game.client.npcs or {}).get(npc_id) or {}
        image = npc.get('image') or '(no image)'
        return f"{image} @ {npc.get('x', 0):.0f},{npc.get('y', 0):.0f}"

    def _selected_row_text(self) -> Optional[str]:
        rows = self.rows()
        if not rows:
            return None
        return rows[min(self.selected[self.tab], len(rows) - 1)]

    # -- loading and saving scripts ---------------------------------------

    def load_selected(self) -> None:
        """Fetch the highlighted entry's script into the editor."""
        link = self.nc_link
        if link is None or not link.available:
            self.message = "no NC session"
            return
        if self.editor.buffer.dirty:
            self.confirm = ("Discard unsaved script changes?", self._load_now)
            return
        self._load_now()

    def _load_now(self) -> None:
        link = self.nc_link
        name = TABS[self.tab]
        index = self.selected[self.tab]
        if name == "NPCs":
            ids = self._npc_ids()
            if not ids:
                self.message = "no NPCs in this level"
                return
            npc_id = ids[min(index, len(ids) - 1)]
            link.get_npc_script(npc_id)
            self.loaded = ("npc", npc_id)
            self.message = f"fetching script for NPC {npc_id}"
        elif name == "Weapons":
            weapon = self._selected_row_text()
            if not weapon:
                return
            link.get_weapon(weapon)
            self.loaded = ("weapon", weapon)
            self.message = f"fetching weapon {weapon}"
        elif name == "Classes":
            class_name = self._selected_row_text()
            if not class_name:
                return
            link.edit_class(class_name)
            self.loaded = ("class", class_name)
            self.message = f"fetching class {class_name}"

    def poll_fetch(self) -> None:
        """Move a completed fetch into the buffer. Called once per frame.

        The reply arrives on the NC worker thread, so the panel watches the
        snapshot for the entry it asked for instead of blocking on it.
        """
        snap = self._snapshot()
        if snap is None or self.loaded is None or self.editor.buffer.dirty:
            return
        kind, key = self.loaded
        text = None
        if kind == "npc":
            text = dict(snap.npc_scripts).get(key)
        elif kind == "weapon" and snap.last_weapon.get('name') == key:
            text = snap.last_weapon.get('script', '')
        elif kind == "class" and snap.last_class.get('name') == key:
            text = snap.last_class.get('script', '')
        if text is not None and text != self.editor.buffer.text:
            self.editor.buffer.load(text)

    def save_script(self) -> None:
        link = self.nc_link
        if link is None or not link.available or self.loaded is None:
            self.message = "nothing loaded to save"
            return
        kind, key = self.loaded
        text = self.editor.buffer.text
        if kind == "npc":
            sent = link.set_npc_script(int(key), text)
        elif kind == "weapon":
            snap = self._snapshot()
            image = (snap.last_weapon.get('image', '') if snap else '')
            # add_weapon on an existing name is the update path: the server
            # replaces the script and keeps the weapon in players' inventories.
            sent = link.add_weapon(str(key), image, text)
        elif kind == "class":
            sent = link.add_class(str(key), text)
        else:
            sent = False
        if not sent:
            self.message = "not sent — NC link not ready"
            return
        self.editor.buffer.load(text)      # clears the dirty flag
        self.message = f"saved {kind} {key}"

    def delete_selected(self) -> None:
        link = self.nc_link
        name = TABS[self.tab]
        if link is None or not link.available:
            return
        if name == "NPCs":
            ids = self._npc_ids()
            if not ids:
                return
            npc_id = ids[min(self.selected[self.tab], len(ids) - 1)]
            self.confirm = (f"Delete NPC {npc_id}?",
                            lambda: link.delete_npc(npc_id))
        elif name == "Weapons":
            weapon = self._selected_row_text()
            if weapon:
                self.confirm = (f"Delete weapon {weapon}?",
                                lambda: link.delete_weapon(weapon))
        elif name == "Classes":
            class_name = self._selected_row_text()
            if class_name:
                self.confirm = (f"Delete class {class_name}?",
                                lambda: link.delete_class(class_name))

    # -- console ----------------------------------------------------------

    def run_console(self) -> None:
        """Run the console buffer as script code on a scratch NPC.

        The server puts the code on a hidden NPC it owns for this account,
        runs it, and answers on RC chat with any compile error or output.
        That is why the console needs the RC link as well as NC: RC chat is
        the reply channel.
        """
        rc = self.rc
        code = self.console.buffer.text.strip()
        if not code:
            return
        if rc is None:
            self.message = "no RC session: open F10 and connect first"
            return
        # The server's eval handler restores this byte to a newline.
        wire_code = code.replace('\n', '\xa7')
        rc.say(f"/eval {self._level_name()} {wire_code}")
        self.output.append(f"> {code.splitlines()[0][:60]}"
                           + (" ..." if len(code.splitlines()) > 1 else ""))
        self.message = "sent to the server"

    def _console_output(self) -> List[str]:
        """The console log, followed by whatever RC chat has said back."""
        rc = self.rc
        replies = list(rc.snapshot.messages[-8:]) if rc is not None else []
        return self.output[-8:] + replies

    # -- input ------------------------------------------------------------

    def handle_key(self, event) -> None:
        if self.confirm is not None:
            if event.unicode.lower() == 'y':
                _, action = self.confirm
                self.confirm = None
                action()
            elif event.key == K_ESCAPE or event.unicode.lower() == 'n':
                self.confirm = None
            return

        ctrl = bool(event.mod & KMOD_CTRL)
        if ctrl and event.key == pygame.K_s:
            self.save_script()
            return
        if event.key == K_F12:
            self.close()
            return

        # While the caret is in a text area, only the panel's own chords are
        # taken; every other key is text. Esc leaves the text area first, so
        # typing "escape" never closes the panel.
        if self.focus_editor:
            if event.key == K_ESCAPE:
                self.focus_editor = False
                return
            if TABS[self.tab] == "Console":
                if ctrl and event.key in (K_RETURN, pygame.K_KP_ENTER):
                    self.run_console()
                    return
                self.console.handle_key(event)
            else:
                self.editor.handle_key(event)
            return

        if event.key == K_ESCAPE:
            self.close()
            return
        if event.key == K_TAB:
            self.tab = (self.tab + (-1 if event.mod & KMOD_SHIFT else 1)) % len(TABS)
            self._prime_tab()
            return
        if event.key == K_RETURN:
            if TABS[self.tab] in ("NPCs", "Weapons", "Classes"):
                self.load_selected()
            self.focus_editor = True
            return

        rows = self.rows()
        if event.key == K_UP:
            self.selected[self.tab] = max(0, self.selected[self.tab] - 1)
            return
        if event.key == K_DOWN:
            self.selected[self.tab] = min(max(0, len(rows) - 1),
                                          self.selected[self.tab] + 1)
            return

        char = event.unicode.lower()
        if char == 'r':
            self._primed.discard(TABS[self.tab])
            self._prime_tab()
        elif char == 'd':
            self.delete_selected()
        elif char == 'n' and TABS[self.tab] == "Weapons":
            self._new_weapon()
        elif char == 'n' and TABS[self.tab] == "Classes":
            self._new_class()
        elif char == 'w' and TABS[self.tab] == "NPCs":
            self._warp_npc_here()

    def _new_weapon(self) -> None:
        link = self.nc_link
        if link is None:
            return
        if not link.available:
            self.message = "NC link is not connected"
            return
        name = f"dev_{self.game.client.player.account}"
        action = lambda: self._create_weapon(name)
        if not link.snapshot.weapon_list_loaded:
            self.confirm = (f"Weapon list not loaded; overwrite {name} if it exists?",
                            action)
            return
        if name in link.snapshot.weapons:
            self.confirm = (f"Overwrite weapon {name}?", action)
            return
        action()

    def _create_weapon(self, name: str) -> None:
        link = self.nc_link
        if link is None:
            return
        if not link.add_weapon(name, "", "// new weapon\n"):
            self.message = "not sent — NC link not ready"
            return
        link.get_weapon_list()
        self.loaded = ("weapon", name)
        self.editor.buffer.load("// new weapon\n")
        self.message = f"created weapon {name}"

    def _new_class(self) -> None:
        link = self.nc_link
        if link is None:
            return
        if not link.available:
            self.message = "NC link is not connected"
            return
        name = f"dev_{self.game.client.player.account}"
        action = lambda: self._create_class(name)
        if not link.snapshot.class_list_loaded:
            self.confirm = (f"Class list not loaded; overwrite {name} if it exists?",
                            action)
            return
        if name in link.snapshot.classes:
            self.confirm = (f"Overwrite class {name}?", action)
            return
        action()

    def _create_class(self, name: str) -> None:
        link = self.nc_link
        if link is None:
            return
        if not link.add_class(name, "// new class\n"):
            self.message = "not sent — NC link not ready"
            return
        self.loaded = ("class", name)
        self.editor.buffer.load("// new class\n")
        self.message = f"created class {name}"

    def _warp_npc_here(self) -> None:
        link = self.nc_link
        ids = self._npc_ids()
        if link is None or not ids:
            return
        npc_id = ids[min(self.selected[self.tab], len(ids) - 1)]
        client = self.game.client
        if not link.warp_npc(npc_id, client.x, client.y, self._level_name()):
            self.message = "not sent — NC link not ready"
            return
        self.message = f"warped NPC {npc_id} to you"

    # -- drawing ----------------------------------------------------------

    # (key cap, wording) per tab - see theme.draw_key_hints. A pair with an
    # empty key is plain wording, for the one hint that is a sentence.
    FOOTERS = {
        "NPCs": (("Enter", "edit"), ("W", "warp to me"), ("D", "delete"),
                 ("R", "refresh"), ("Ctrl+S", "save")),
        "Weapons": (("Enter", "edit"), ("N", "new"), ("D", "delete"),
                    ("R", "refresh"), ("Ctrl+S", "save")),
        "Classes": (("Enter", "edit"), ("N", "new"), ("D", "delete"),
                    ("Ctrl+S", "save")),
        "Console": (("Enter", "focus"), ("Ctrl+Enter", "run"),
                    ("Esc", "leave the text area")),
        "Level": (("R", "refresh"), ("F11", "edit mode paints tiles"),
                  ("", "Ctrl+S saves there")),
    }

    GLOBAL_HINTS = (("Tab", "switch tab"), ("Up/Dn", "select"), ("F12", "close"))

    def draw(self, surf) -> None:
        if not self.visible:
            return
        self.poll_fetch()
        g = self.game
        rect = pygame.Rect(PANEL_MARGIN, PANEL_MARGIN,
                           max(320, g.screen_w - PANEL_MARGIN * 2),
                           max(240, g.screen_h - PANEL_MARGIN * 2))
        theme.draw_panel(surf, rect)

        snap = self._snapshot()
        state = snap.state if snap else "idle"
        status = snap.status if snap else self.message
        surf.blit(g.font.render("Dev playground", True, theme.MINT_PALE),
                  (rect.x + PAD, rect.y + PAD))
        color = {READY: theme.MINT, CONNECTING: theme.WARN, CLOSED: theme.WARN,
                 DENIED: theme.ERROR, ERROR: theme.ERROR}.get(state,
                                                              theme.TEXT_DIM)
        surf.blit(g.font_small.render(f"NC: {status}"[:70], True, color),
                  (rect.x + PAD, rect.y + PAD + 20))
        self._draw_tabs(surf, rect)

        body = pygame.Rect(
            rect.x + PAD, rect.y + PAD + 62, rect.w - PAD * 2,
            rect.h - PAD * 2 - 62 - theme.key_hints_height(
                g.fonts.get("chat"), 2))
        if TABS[self.tab] == "Console":
            self._draw_console(surf, body)
        else:
            self._draw_list_and_editor(surf, body)
        self._draw_footer(surf, rect, state)

    def _draw_tabs(self, surf, rect) -> None:
        g = self.game
        x = rect.x + PAD
        y = rect.y + PAD + 40
        for i, name in enumerate(TABS):
            label = g.font_small.render(name, True,
                                        theme.TEXT_ON_ACCENT if i == self.tab
                                        else theme.TEXT_DIM)
            box = pygame.Rect(x - 4, y - 3, label.get_width() + 12,
                              label.get_height() + 6)
            if i == self.tab:
                pygame.draw.rect(surf, theme.EMERALD, box, border_radius=4)
            surf.blit(label, (x + 2, y))
            x += box.w + 6

    def _draw_list_and_editor(self, surf, body: pygame.Rect) -> None:
        g = self.game
        rows = self.rows()
        selected = min(self.selected[self.tab], max(0, len(rows) - 1))
        capacity = max(1, body.h // LINE_H)
        start = min(max(0, selected - capacity + 1), max(0, len(rows) - capacity))

        y = body.y
        for i in range(start, min(len(rows), start + capacity)):
            if i == selected:
                hl = pygame.Surface((LIST_W, LINE_H), pygame.SRCALPHA)
                hl.fill(theme.SELECTION)
                surf.blit(hl, (body.x, y - 1))
            surf.blit(g.font_small.render(rows[i][:26], True, theme.TEXT),
                      (body.x + 4, y))
            y += LINE_H
        if not rows:
            surf.blit(g.font_small.render("(nothing here)", True,
                                          theme.TEXT_FAINT), (body.x, body.y))

        edit_rect = pygame.Rect(body.x + LIST_W + PAD, body.y,
                                body.w - LIST_W - PAD, body.h)
        title = "no script loaded"
        if self.loaded is not None:
            kind, key = self.loaded
            title = f"{kind} {key}{' *' if self.editor.buffer.dirty else ''}"
        surf.blit(g.font_small.render(title[:60], True,
                                      theme.MINT if self.focus_editor
                                      else theme.TEXT_DIM),
                  (edit_rect.x, edit_rect.y))
        self.editor.draw(surf, pygame.Rect(edit_rect.x, edit_rect.y + 18,
                                           edit_rect.w, edit_rect.h - 18),
                         g.fonts)

    def _draw_console(self, surf, body: pygame.Rect) -> None:
        g = self.game
        out_h = body.h // 2
        y = body.y
        for line in self._console_output():
            surf.blit(g.font_small.render(line[:110], True, theme.TEXT_DIM),
                      (body.x, y))
            y += LINE_H
            if y > body.y + out_h - LINE_H:
                break
        label = "script console" + (" (typing)" if self.focus_editor else "")
        surf.blit(g.font_small.render(label, True,
                                      theme.MINT if self.focus_editor
                                      else theme.TEXT_DIM),
                  (body.x, body.y + out_h))
        self.console.draw(surf, pygame.Rect(body.x, body.y + out_h + 18,
                                            body.w, body.h - out_h - 18),
                          g.fonts)

    def _draw_footer(self, surf, rect, state: str) -> None:
        g = self.game
        font = g.fonts.get("chat")
        y = rect.bottom - PAD - theme.key_hints_height(font, 2)
        if self.confirm is not None:
            line, color = f"{self.confirm[0]}  [Y/N]", theme.WARN
        elif self.message:
            line, color = self.message, theme.INFO
        else:
            line, color = None, None
        if line is not None:
            surf.blit(font.render(line[:100], True, color), (rect.x + PAD, y))
        hints = self.FOOTERS[TABS[self.tab]] if state == READY else ()
        theme.draw_key_hints(surf, font, rect.x + PAD,
                             y + theme.key_hints_height(font),
                             tuple(hints) + self.GLOBAL_HINTS,
                             width=rect.w - PAD * 2, max_lines=1)
