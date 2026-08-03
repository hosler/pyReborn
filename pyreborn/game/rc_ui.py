"""game/rc_ui.py — the F10 in-game RC (Remote Control) tools overlay.

RC is a second, separate connection (see pyreborn/rc_link.py for why), so this
overlay is also the thing that opens it: the first F10 press starts the link,
and the panel reports "connecting" / "no RC access" / the live session rather
than the key doing nothing for players without rights.

Shape follows the other modal overlays (F7 player list, F9 settings): it owns
its own `.visible` state, `game/input.py` routes KEYDOWN to `handle_key` while
it is open, and `game/hud.py` draws it last. It is bigger than those because
it carries five tabs, so it draws its own panel instead of reusing
`_draw_list_overlay`.

Every destructive action goes through a confirm step (`Y`/`N`) — kicking,
banning, deleting an account, deleting a file or folder, and writing server
flags all hit real server state, and the RC packets have no undo.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import pygame
from pygame.locals import (
    K_BACKSPACE, K_DOWN, K_ESCAPE, K_F10, K_LEFT, K_PAGEDOWN, K_PAGEUP,
    K_RETURN, K_RIGHT, K_TAB, K_UP, KMOD_SHIFT,
)

from . import theme
from ..rc_link import CLOSED, CONNECTING, DENIED, ERROR, READY, RCLink

TABS = ("Chat", "Players", "Accounts", "Server", "Files")

# Panel geometry, clamped to the window in _panel_rect.
PANEL_W, PANEL_H = 720, 500
PAD = 14
LINE_H = 22


def folder_targets(folder_rights) -> List[str]:
    """Folder names a CD will be accepted for, from the rights entries.

    A rights entry looks like ``rw world/*``: an access token, then a
    wildcard path. The server keys its folder map on the path up to and
    including the last '/', so ``world/`` is what a CD has to send - sending
    ``world`` is silently ignored.

    A bare ``rw *`` grants the WHOLE tree rather than one folder, and there
    is no directory literally named "*". Its target is therefore the root,
    which a CD sends as the empty string; ``rows()`` labels that one "[/]".
    pygserver hands out exactly this entry when an account has no explicit
    folder list, so without the special case its browser opens onto nothing.
    """
    targets = []
    for entry in folder_rights or ():
        text = str(entry).strip()
        if not text:
            continue
        parts = text.split(None, 1)
        path = parts[1] if len(parts) > 1 else parts[0]
        if path.strip('*') == '':
            folder = ''            # the root, not a folder called "*"
        elif '/' in path:
            folder = path[:path.rfind('/') + 1]
        else:
            folder = path
        if folder not in targets:
            targets.append(folder)
    return targets


class _Prompt:
    """A one-line text entry: a label, the text so far, and what to do with it."""

    def __init__(self, label: str, on_submit: Callable[[str], None],
                 text: str = ""):
        self.label = label
        self.on_submit = on_submit
        self.text = text


class RCOverlay:
    """Owns the F10 overlay: the RC link, the open tab, selection and prompts."""

    def __init__(self, game):
        self.game = game
        self.visible = False
        self.tab = 0
        self.selected = [0] * len(TABS)
        self.scroll = [0] * len(TABS)
        self.link: Optional[RCLink] = None
        self.prompt: Optional[_Prompt] = None
        self.confirm: Optional[Tuple[str, Callable[[], None]]] = None
        self.message = ""
        # Refreshing costs a round trip, so each tab pulls its data the first
        # time it is opened rather than every frame.
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
        self.prompt = None
        self.confirm = None

    def shutdown(self) -> None:
        """Drop the RC connection. Called when the game client exits."""
        if self.link is not None:
            self.link.close()
            self.link = None

    def _ensure_link(self) -> None:
        if self.link is not None:
            # start() is a no-op while the worker lives, so this doubles as
            # the reconnect: a session the server dropped (restart, kick)
            # comes back on the next F10 instead of staying dead for the rest
            # of the play session. A refusal is NOT retried - hammering a
            # server that already said no is exactly the wrong behaviour.
            if self.link.state != DENIED:
                self.link.start()
            return
        client = self.game.client
        password = getattr(self.game, 'rc_password', None)
        if not password:
            self.message = ("No password in this session — start the client "
                            "with a login to use RC tools.")
            return
        self.link = RCLink(client.host, client.port,
                           client.player.account, password,
                           version=client.version)
        self.link.start()

    @property
    def available(self) -> bool:
        return self.link is not None and self.link.available

    # -- data -------------------------------------------------------------

    def _snapshot(self):
        return self.link.snapshot if self.link is not None else None

    def _prime_tab(self) -> None:
        """Request the open tab's data once per session."""
        link = self.link
        if link is None or not link.available:
            return
        name = TABS[self.tab]
        if name in self._primed:
            return
        if name == "Accounts":
            link.refresh_accounts()
        elif name == "Server":
            link.refresh_flags()
            link.refresh_options()
            link.refresh_folder_config()
        elif name == "Files":
            link.files_start()
        else:
            return
        self._primed.add(name)

    def rows(self) -> List[str]:
        """The open tab's body lines."""
        snap = self._snapshot()
        if snap is None:
            return []
        name = TABS[self.tab]
        if name == "Chat":
            return list(snap.messages)
        if name == "Players":
            return [f"{p.get('id', '?'):>4}  {p.get('account', '?')}"
                    for p in snap.players]
        if name == "Accounts":
            return list(snap.accounts)
        if name == "Server":
            rows = [f"flag  {flag}" for flag in snap.server_flags]
            rows += [f"opt   {line}" for line in snap.option_lines]
            rows += [f"fldr  {line}" for line in snap.folder_config]
            return rows
        if name == "Files":
            if not snap.files and snap.folders:
                # Nothing has been opened yet. The reference server answers
                # FILEBROWSER_START with the account's folder RIGHTS and no
                # listing at all (GServer-v2 PlayerRCPackets.cpp:1064), and it
                # only accepts a CD whose name matches one of them - so those
                # rights are the only navigable thing on offer, and without
                # showing them the browser is a dead end on a real server.
                return [f"[{folder or '/'}]"
                        for folder in folder_targets(snap.folders)]
            rows = []
            for entry in snap.files:
                label = str(entry.get('name', '?'))
                if label.endswith('/'):
                    # A directory: the reference listing marks them by the
                    # trailing slash rather than a separate field.
                    rows.append(f"[{label[:-1]}]")
                else:
                    rows.append(f"{label}  {entry.get('size', 0)} bytes  "
                                f"{entry.get('rights', '')}")
            return rows
        return []

    def _selected_row(self) -> int:
        return self.selected[self.tab]

    def _selected_player(self) -> Optional[dict]:
        snap = self._snapshot()
        if snap is None or not snap.players:
            return None
        idx = min(self._selected_row(), len(snap.players) - 1)
        return snap.players[idx]

    def _selected_account(self) -> Optional[str]:
        snap = self._snapshot()
        if snap is None or not snap.accounts:
            return None
        idx = min(self._selected_row(), len(snap.accounts) - 1)
        return snap.accounts[idx]

    def _selected_entry(self) -> Optional[dict]:
        snap = self._snapshot()
        if snap is None or not snap.files:
            return None
        idx = min(self._selected_row(), len(snap.files) - 1)
        return snap.files[idx]

    def _selected_file(self) -> Optional[dict]:
        """The highlighted FILE, or None when the row is a directory."""
        entry = self._selected_entry()
        if entry is None or str(entry.get('name', '')).endswith('/'):
            return None
        return entry

    def _selected_folder(self) -> Optional[str]:
        """The highlighted DIRECTORY, or None when the row is a file.

        Before anything is opened the rows ARE the folder-rights targets (see
        rows()), and those are returned verbatim - the server matches a CD
        against them exactly, trailing slash included. The root target is the
        empty string, so callers must test for None, not for truth.
        """
        snap = self._snapshot()
        if snap is not None and not snap.files and snap.folders:
            targets = folder_targets(snap.folders)
            if not targets:
                return None
            return targets[min(self._selected_row(), len(targets) - 1)]
        entry = self._selected_entry()
        if entry is None:
            return None
        name = str(entry.get('name', ''))
        return name[:-1] if name.endswith('/') else None

    # -- input ------------------------------------------------------------

    def handle_key(self, event) -> None:
        if self.prompt is not None:
            self._handle_prompt_key(event)
            return
        if self.confirm is not None:
            self._handle_confirm_key(event)
            return

        key = event.key
        if key in (K_F10, K_ESCAPE):
            self.close()
            return
        if key == K_TAB:
            step = -1 if event.mod & KMOD_SHIFT else 1
            self._switch_tab(step)
            return
        if key == K_LEFT:
            self._switch_tab(-1)
            return
        if key == K_RIGHT:
            self._switch_tab(1)
            return

        rows = self.rows()
        if key == K_UP:
            self.selected[self.tab] = max(0, self._selected_row() - 1)
            return
        if key == K_DOWN:
            self.selected[self.tab] = min(max(0, len(rows) - 1),
                                          self._selected_row() + 1)
            return
        if key == K_PAGEUP:
            self.selected[self.tab] = max(0, self._selected_row() - 10)
            return
        if key == K_PAGEDOWN:
            self.selected[self.tab] = min(max(0, len(rows) - 1),
                                          self._selected_row() + 10)
            return

        if self.link is None or not self.link.available:
            return
        handler = getattr(self, f"_keys_{TABS[self.tab].lower()}")
        handler(event)

    def _switch_tab(self, step: int) -> None:
        self.tab = (self.tab + step) % len(TABS)
        self._prime_tab()

    def _handle_prompt_key(self, event) -> None:
        prompt = self.prompt
        if event.key == K_ESCAPE:
            self.prompt = None
            return
        if event.key == K_RETURN:
            self.prompt = None
            text = prompt.text.strip()
            if text:
                prompt.on_submit(text)
            return
        if event.key == K_BACKSPACE:
            prompt.text = prompt.text[:-1]
            return
        if event.unicode and event.unicode.isprintable():
            prompt.text += event.unicode

    def _handle_confirm_key(self, event) -> None:
        if event.unicode.lower() == 'y':
            _, action = self.confirm
            self.confirm = None
            action()
            return
        if event.key == K_ESCAPE or event.unicode.lower() == 'n':
            self.confirm = None

    def _ask(self, label: str, on_submit: Callable[[str], None],
             text: str = "") -> None:
        self.prompt = _Prompt(label, on_submit, text)

    def _confirm_then(self, question: str, action: Callable[[], None]) -> None:
        self.confirm = (question, action)

    # -- per-tab keys -----------------------------------------------------

    def _keys_chat(self, event) -> None:
        link = self.link
        if event.key == K_RETURN:
            self._ask("RC chat", link.say)
        elif event.unicode.lower() == 'a':
            self._ask("Broadcast to ALL players", link.admin_message)
        elif event.unicode.lower() == 'r':
            link.refresh_rcs()

    def _keys_players(self, event) -> None:
        link = self.link
        player = self._selected_player()
        char = event.unicode.lower()
        if player is None:
            return
        pid = int(player.get('id', 0))
        account = str(player.get('account', ''))

        if event.key == K_RETURN:
            link.player_props(pid)
            self.message = f"requested props for {account}"
        elif char == 'k':
            self._confirm_then(
                f"Kick {account}?", lambda: link.kick(pid))
        elif char == 'w':
            # Warp them to where we are standing — the common moderation move.
            client = self.game.client
            level = client.level
            x, y = client.x, client.y
            self._confirm_then(
                f"Warp {account} to you ({level} {x:.0f},{y:.0f})?",
                lambda: link.warp_player(pid, x, y, level))
        elif char == 'b':
            self._ask(f"Ban reason for {account}",
                      lambda text: self._confirm_then(
                          f"Ban {account}?",
                          lambda: link.ban(account, True, text)))
        elif char == 'u':
            self._confirm_then(f"Unban {account}?",
                               lambda: link.ban(account, False, ""))
        elif char == 'c':
            self._ask(f"Comment on {account}",
                      lambda text: link.set_comments(account, text))
        elif char == 'r':
            link.rights(account)
            self.message = f"requested rights for {account}"

    def _keys_accounts(self, event) -> None:
        link = self.link
        char = event.unicode.lower()
        account = self._selected_account()

        if event.key == K_RETURN and account:
            link.account_info(account)
            link.rights(account)
            link.ban_status(account)
            self.message = f"requested {account}"
        elif char == 'r':
            link.refresh_accounts()
        elif char == 'n':
            self._ask("New account as name,password,email", self._create_account)
        elif char == 'd' and account:
            self._confirm_then(
                f"DELETE account {account}? This cannot be undone.",
                lambda: link.delete_account(account))
        elif char == 'b' and account:
            self._ask(f"Ban reason for {account}",
                      lambda text: self._confirm_then(
                          f"Ban {account}?",
                          lambda: link.ban(account, True, text)))
        elif char == 'u' and account:
            self._confirm_then(f"Unban {account}?",
                               lambda: link.ban(account, False, ""))

    def _create_account(self, text: str) -> None:
        parts = [p.strip() for p in text.split(',')]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            self.message = "need at least name,password"
            return
        email = parts[2] if len(parts) > 2 else ""
        self.link.create_account(parts[0], parts[1], email)
        self.link.refresh_accounts()

    def _keys_server(self, event) -> None:
        link = self.link
        char = event.unicode.lower()
        if char == 'r':
            link.refresh_flags()
            link.refresh_options()
            link.refresh_folder_config()
        elif char == 'f':
            self._ask("Set server flag as name=value", self._set_flag)
        elif char == 'l':
            self._confirm_then("Reload all levels on the server?",
                               link.update_levels)

    def _set_flag(self, text: str) -> None:
        """Edit ONE flag without dropping the rest.

        PLI_RC_SERVERFLAGSSET replaces the whole flag set, so the edit is
        merged into the flags we last read and the full set is sent back. A
        naive "send just this one" would delete every other server flag.
        """
        name, _, value = text.partition('=')
        name = name.strip()
        if not name:
            self.message = "need name=value"
            return
        snap = self._snapshot()
        flags = {}
        for entry in (snap.server_flags if snap else ()):
            key, _, existing = entry.partition('=')
            flags[key] = existing
        flags[name] = value.strip()
        self._confirm_then(
            f"Write {len(flags)} server flags (setting {name})?",
            lambda: self.link.set_flags(flags))

    def _keys_files(self, event) -> None:
        link = self.link
        char = event.unicode.lower()
        folder = self._selected_folder()
        entry = self._selected_file()
        name = str(entry.get('name', '')) if entry else ''

        if event.key == K_RETURN and folder is not None:
            link.files_cd(folder)
            self.selected[self.tab] = 0
        elif event.key == K_BACKSPACE:
            link.files_cd("..")
            self.selected[self.tab] = 0
        elif char == 'r':
            link.files_start()
        elif char == 'd' and name:
            link.files_download(name)
            self.message = f"downloading {name}"
        elif char == 'x' and name:
            self._confirm_then(f"DELETE {name} on the server?",
                               lambda: link.files_delete(name))
        elif char == 'n' and name:
            self._ask(f"Rename {name} to",
                      lambda text: link.files_rename(name, text))
        elif char == 'm' and name:
            self._ask(f"Move {name} to folder",
                      lambda text: link.files_move(text, name))
        elif char == 'u':
            self._ask("Upload local file path", link.files_upload)
        elif char == 'o' and folder is not None:
            self._confirm_then(f"DELETE folder {folder}?",
                               lambda: link.folder_delete(folder))

    # -- rendering --------------------------------------------------------

    # (key cap, wording) per tab. Kept structured so theme.draw_key_hints can
    # draw the key as a cap - the old "K kick · B ban" run of same-size dim
    # text was the thing nobody could read.
    FOOTERS = {
        "Chat": (("Enter", "chat"), ("A", "broadcast"), ("R", "list RCs")),
        "Players": (("Enter", "props"), ("K", "kick"), ("W", "warp to me"),
                    ("B", "ban"), ("U", "unban"), ("C", "comment"),
                    ("R", "rights")),
        "Accounts": (("Enter", "details"), ("N", "new"), ("D", "delete"),
                     ("B", "ban"), ("U", "unban"), ("R", "refresh")),
        "Server": (("F", "set flag"), ("L", "reload levels"), ("R", "refresh")),
        "Files": (("Enter", "open"), ("Bksp", "up"), ("D", "download"),
                  ("U", "upload"), ("N", "rename"), ("M", "move"),
                  ("X", "delete"), ("O", "rm folder")),
    }

    # Always available, whichever tab is open.
    GLOBAL_HINTS = (("Tab", "switch tab"), ("Up/Dn", "select"),
                    ("F10", "close"))

    def _panel_rect(self) -> pygame.Rect:
        g = self.game
        w = min(PANEL_W, max(320, g.screen_w - 20))
        h = min(PANEL_H, max(240, g.screen_h - 20))
        return pygame.Rect((g.screen_w - w) // 2, (g.screen_h - h) // 2, w, h)

    def draw(self, surf) -> None:
        if not self.visible:
            return
        g = self.game
        rect = self._panel_rect()
        theme.draw_panel(surf, rect)

        snap = self._snapshot()
        state = snap.state if snap else "idle"
        status = snap.status if snap else self.message
        title = f"RC — {g.client.player.account}"
        surf.blit(g.font.render(title, True, theme.MINT_PALE),
                  (rect.x + PAD, rect.y + PAD))
        color = {READY: theme.MINT, CONNECTING: theme.WARN,
                 CLOSED: theme.WARN, DENIED: theme.ERROR,
                 ERROR: theme.ERROR}.get(state, theme.TEXT_DIM)
        surf.blit(g.font_small.render(status[:60], True, color),
                  (rect.x + PAD, rect.y + PAD + 20))

        self._draw_tabs(surf, rect)
        surf.blit(g.font_small.render(self._context_line()[:78], True,
                                      theme.TEXT_DIM),
                  (rect.x + PAD, rect.y + PAD + 62))
        body_top = rect.y + PAD + 82
        # Three hint rows' worth: the prompt/notice line plus up to two lines
        # of key caps. Reserving less overdrew the last rows.
        body_bottom = rect.bottom - PAD - theme.key_hints_height(
            g.fonts.get("chat"), 3)
        self._draw_rows(surf, rect, body_top, body_bottom)
        self._draw_footer(surf, rect, state)

    def _context_line(self) -> str:
        """What the open tab is looking at right now."""
        snap = self._snapshot()
        if snap is None:
            return ""
        name = TABS[self.tab]
        if name == "Files":
            # snap.folders is the account's folder-RIGHTS list (the reference
            # server sends it once at browser start), not the subfolders of
            # the current directory — those are rows ending in "/".
            rights = ", ".join(snap.folders) or "(no folder rights)"
            return f"/{snap.folder}   rights: {rights}"
        if name == "Players":
            return f"{len(snap.players)} online"
        if name == "Accounts":
            return f"{len(snap.accounts)} accounts"
        if name == "Server":
            return (f"{len(snap.server_flags)} flags · "
                    f"{len(snap.option_lines)} option lines")
        return f"upload limit {snap.max_upload_size} bytes" \
            if snap.max_upload_size else ""

    def _draw_tabs(self, surf, rect) -> None:
        g = self.game
        font = g.fonts.get("chat")
        x = rect.x + PAD
        y = rect.y + PAD + 38
        for i, name in enumerate(TABS):
            label = font.render(name, True,
                                        theme.TEXT_ON_ACCENT if i == self.tab
                                        else theme.TEXT_DIM)
            box = pygame.Rect(x - 4, y - 3, label.get_width() + 12,
                              label.get_height() + 6)
            if i == self.tab:
                pygame.draw.rect(surf, theme.EMERALD, box, border_radius=4)
            surf.blit(label, (x + 2, y))
            x += box.w + 6

    def _draw_rows(self, surf, rect, top: int, bottom: int) -> None:
        g = self.game
        rows = self.rows()
        capacity = max(1, (bottom - top) // LINE_H)
        selected = min(self._selected_row(), max(0, len(rows) - 1))
        self.selected[self.tab] = selected

        # Chat reads newest-last, so it parks at the bottom; the list tabs
        # follow the highlighted row instead.
        if TABS[self.tab] == "Chat":
            start = max(0, len(rows) - capacity)
        else:
            start = min(max(0, selected - capacity + 1), max(0, len(rows) - capacity))
            start = max(0, start)

        font = g.fonts.get("chat")
        if not rows:
            hint = "(nothing to show)" if self.available else "(no RC session)"
            surf.blit(font.render(hint, True, theme.TEXT_DIM),
                      (rect.x + PAD, top))
            return

        y = top
        for i in range(start, min(len(rows), start + capacity)):
            if i == selected and TABS[self.tab] != "Chat":
                hl = pygame.Surface((rect.w - PAD * 2, LINE_H), pygame.SRCALPHA)
                hl.fill(theme.SELECTION)
                surf.blit(hl, (rect.x + PAD, y - 1))
            surf.blit(font.render(rows[i][:76], True, theme.TEXT),
                      (rect.x + PAD + 4, y))
            y += LINE_H

    def _draw_footer(self, surf, rect, state: str) -> None:
        """The prompt/notice line, then the keys for the open tab.

        The keys get the readable font and a key cap each, because they are
        the only way to drive the panel - they are not decoration.
        """
        g = self.game
        font = g.fonts.get("chat")
        width = rect.w - PAD * 2
        y = rect.bottom - PAD - theme.key_hints_height(font, 3)
        snap = self._snapshot()

        line = color = None
        if self.prompt is not None:
            line, color = f"{self.prompt.label}: {self.prompt.text}_", theme.MINT
        elif self.confirm is not None:
            line, color = f"{self.confirm[0]}  [Y/N]", theme.WARN
        elif snap is not None and snap.notices:
            line, color = snap.notices[-1], theme.INFO
        elif self.message:
            line, color = self.message, theme.INFO
        if line is not None:
            surf.blit(font.render(line[:74], True, color), (rect.x + PAD, y))
        y += theme.key_hints_height(font)

        hints = self.FOOTERS[TABS[self.tab]] if state == READY else ()
        y = theme.draw_key_hints(surf, font, rect.x + PAD, y,
                                 tuple(hints) + self.GLOBAL_HINTS,
                                 width=width, max_lines=2)
