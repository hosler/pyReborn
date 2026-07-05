"""game/hud.py — the in-game heads-up display.

This replaces the ~200-line `_render_ui` god-method that mixed panel geometry,
status text, chat, dialogue, minimap and a hand-rolled `ui_y += 20` cursor all in
one place. The crustiest part was that vertical cursor: every conditional status
line had to remember to advance `ui_y`, so adding/removing a line meant chasing
the bookkeeping.

The fix follows the same Gui*Ctrl-composite inspiration as ui.py (the C# client):
the always-on, anchored pieces (stat panel, the status-line stack, the help hint,
the ghost-mode banner) live in a declarative widget tree, and the **vstack**
container does the vertical layout that `ui_y` used to do by hand — a hidden line
simply contributes nothing. The transient/animated pieces (the fading dialogue
box, the scrolling chat log, the minimap, the help overlay) stay as small
imperative draws because encoding fades/feeds as widgets buys nothing.

`HUD.update()` syncs widget text+visibility from game state; `HUD.draw()` paints
the tree then the imperative overlays. The tile-editor/debug overlay stays in
render.py — it is editor UI, not the play HUD.
"""

import time
from typing import Optional

import pygame

from .ui import UIManager, Panel, Label, Widget, TOPLEFT, TOPRIGHT, MIDTOP


class Badge(Widget):
    """A line of text on a translucent black plate — the old `_draw_text_with_bg`
    as a self-sizing widget so it can live in a vstack."""

    PAD_X, PAD_Y = 5, 2

    def __init__(self, text="", *, color=(255, 255, 255), role="hud",
                 bg_alpha=180, anchor=TOPLEFT, offset=(0, 0), visible=True):
        super().__init__(0, 0, anchor, offset, visible)
        self.color = color
        self.role = role
        self.bg_alpha = bg_alpha
        self._text = text
        self._fonts = None
        self._surf: Optional[pygame.Surface] = None
        self._key = None
        self._plate: Optional[pygame.Surface] = None
        self._plate_key = None

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value

    def _ensure(self):
        key = (self._text, self.role, self.color)
        if key != self._key and self._fonts is not None:
            self._surf = self._fonts.get(self.role).render(
                self._text, True, self.color)
            self.w = self._surf.get_width() + self.PAD_X * 2
            self.h = self._surf.get_height() + self.PAD_Y * 2
            self._key = key

    def layout(self, container):
        self._ensure()
        super().layout(container)

    def _draw(self, surf):
        if self._surf is None:
            return
        plate_key = (self.w, self.h, self.bg_alpha)
        if plate_key != self._plate_key:
            self._plate = pygame.Surface((self.w, self.h))
            self._plate.fill((0, 0, 0))
            self._plate.set_alpha(self.bg_alpha)
            self._plate_key = plate_key
        surf.blit(self._plate, self.rect.topleft)
        surf.blit(self._surf, (self.rect.x + self.PAD_X, self.rect.y + self.PAD_Y))


class StatsPanel(Widget):
    """Top-left core HUD: hearts row + rupee/bomb/arrow counters, drawn live from
    the player. Self-contained so the panel geometry lives in one place."""

    def __init__(self, game):
        super().__init__(0, 0, TOPLEFT, (6, 6))
        self.game = game
        self._plate: Optional[pygame.Surface] = None
        self._plate_key = None

    def _stat_icon(self, surf, x, y, kind, count):
        """Draw a consumable icon + count; returns x after the text."""
        cy = y + 8
        if kind == 'rupee':
            pts = [(x + 6, y), (x + 12, cy), (x + 6, y + 16), (x, cy)]
            pygame.draw.polygon(surf, (60, 220, 90), pts)
            pygame.draw.polygon(surf, (20, 110, 40), pts, 1)
        elif kind == 'bomb':
            pygame.draw.circle(surf, (40, 40, 50), (x + 6, cy + 1), 6)
            pygame.draw.circle(surf, (90, 90, 105), (x + 4, cy - 1), 2)
            pygame.draw.line(surf, (200, 150, 60), (x + 9, y + 2), (x + 11, y - 2), 2)
        elif kind == 'arrow':
            pygame.draw.line(surf, (210, 200, 180), (x, y + 14), (x + 12, y + 2), 2)
            pygame.draw.polygon(surf, (210, 200, 180),
                                [(x + 12, y + 2), (x + 7, y + 3), (x + 11, y + 7)])
        txt = self.game.font_small.render(str(count), True, (245, 245, 245))
        surf.blit(txt, (x + 16, y + 1))
        return x + 16 + txt.get_width()

    def _stat_bar(self, surf, x, y, w, label, value, maxvalue, color):
        """A small labeled bar for MP/AP (no icon art for these exists)."""
        h = 6
        pygame.draw.rect(surf, (40, 40, 46), (x, y, w, h), border_radius=2)
        if maxvalue > 0:
            fill_w = max(0, min(w, int(w * value / maxvalue)))
            if fill_w > 0:
                pygame.draw.rect(surf, color, (x, y, fill_w, h), border_radius=2)
        pygame.draw.rect(surf, (10, 10, 12), (x, y, w, h), 1, border_radius=2)
        txt = self.game.font_small.render(label, True, (220, 220, 220))
        surf.blit(txt, (x, y - 12))

    def _draw(self, surf):
        player = self.game.client.player
        hd = self.game.heart_display
        hearts_w = int(player.max_hearts) * (hd.HEART_SIZE + hd.HEART_SPACING)
        panel_w = max(168, hearts_w + 16)

        # Tier 3a: MP (magic) / AP (alignment) bars, from PLPROP_MAGICPOINTS(26)
        # / PLPROP_ALIGNMENT(32) via packets.py's parse_player_props ->
        # Player.mp/.ap. Both fields always exist on Player (defaults 0/50),
        # so this row shows as soon as the HUD renders, not just after the
        # server's first PLO_PLAYERPROPS - getattr keeps this tolerant of
        # any caller passing a bare object without the fields.
        mp = getattr(player, 'mp', None)
        ap = getattr(player, 'ap', None)
        show_mp_ap = mp is not None or ap is not None
        panel_h = 52 + (20 if show_mp_ap else 0)

        plate_key = (panel_w, panel_h)
        if plate_key != self._plate_key:
            self._plate = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            pygame.draw.rect(self._plate, (0, 0, 0, 130), (0, 0, panel_w, panel_h),
                             border_radius=6)
            self._plate_key = plate_key
        surf.blit(self._plate, (6, 6))

        hd.render(surf, player.hearts, player.max_hearts)

        icon_y = 32
        x = self._stat_icon(surf, 12, icon_y, 'rupee', player.rupees)
        x = self._stat_icon(surf, x + 12, icon_y, 'bomb', player.bombs)
        self._stat_icon(surf, x + 12, icon_y, 'arrow', player.arrows)

        if show_mp_ap:
            bar_y = icon_y + 30
            bar_w = (panel_w - 24 - 12) // 2
            if mp is not None:
                self._stat_bar(surf, 12, bar_y, bar_w, "MP", mp,
                               getattr(player, 'max_mp', 100) or 100, (90, 140, 255))
            if ap is not None:
                self._stat_bar(surf, 12 + bar_w + 12, bar_y, bar_w, "AP", ap,
                               getattr(player, 'max_ap', 100) or 100, (230, 200, 80))


class HUD:
    """Owns the play HUD: a declarative widget tree plus a few imperative draws."""

    HELP_LINES = [
        ("Arrow Keys", "Move"),
        ("A", "Grab / Pick up / Throw"),
        ("S or Space", "Swing sword"),
        ("D", "Use weapon"),
        ("Q", "Inventory"),
        ("Wheel / 0", "Zoom / reset"),
        ("M", "Toggle minimap"),
        ("N", "Noclip (walk through walls)"),
        ("Enter", "Chat"),
        ("F1", "Debug / tile editor"),
        ("F2", "Unstick: warp to (30,30)"),
        ("F7", "Player list / PM"),
        ("F8", "Server list"),
        ("H", "Close this help"),
    ]

    def __init__(self, game):
        self.game = game
        self.ui = UIManager(game.fonts, game.screen_w, game.screen_h)

        # Always-on stat panel.
        self.ui.root.add(StatsPanel(game))

        # Status-line stack: a vstack does the vertical layout the old `ui_y`
        # cursor did by hand. Each line is preallocated; per frame we just set
        # its text and visibility and the container reflows.
        self.status = Panel(w=420, anchor=TOPLEFT, offset=(5, 64),
                            vstack=True, align=TOPLEFT, spacing=2)
        self.badge_swim = Badge(color=(100, 200, 255), visible=False)
        self.badge_door = Badge(color=(255, 255, 100), visible=False)
        self.badge_carry = Badge(color=(100, 255, 100), visible=False)
        self.badge_sit = Badge(color=(255, 200, 100), visible=False)
        self.badge_noclip = Badge(color=(255, 120, 120), visible=False)
        self.status.add(self.badge_swim, self.badge_door,
                        self.badge_carry, self.badge_sit, self.badge_noclip)
        self.ui.root.add(self.status)

        # Top-right "H: Help" hint and centered ghost-mode banner.
        self.hint = Label("H: Help", role="small", color=(210, 210, 210),
                          anchor=TOPRIGHT, offset=(-10, 10))
        self.ghost = Badge("GHOST MODE", color=(200, 200, 255),
                           anchor=MIDTOP, offset=(0, 50), visible=False)
        self.ui.root.add(self.hint, self.ghost)

        # Per-message (text, plate) surfaces for the chat log, rebuilt only
        # when the last-5 slice of chat_messages actually changes.
        self._chat_cache = {}
        self._chat_slice = None

    # -- per-frame --------------------------------------------------------
    def update(self):
        g = self.game
        player = g.client.player

        self.badge_swim.text = "SWIMMING"
        self.badge_swim.visible = g.is_swimming

        door = g._get_non_edge_door()
        self.badge_door.visible = bool(door)
        if door:
            self.badge_door.text = f"Door -> {door.get('dest_level', '?')} (press A)"

        self.badge_carry.visible = player.is_carrying()
        if player.is_carrying():
            self.badge_carry.text = \
                f"Carrying: {player.carried_object_type.title()} (A to throw)"

        self.badge_sit.visible = player.is_sitting
        if player.is_sitting:
            self.badge_sit.text = "Sitting (press A to stand)"

        self.badge_noclip.text = "NOCLIP (N)"
        self.badge_noclip.visible = getattr(g, "noclip", False)

        self.ghost.visible = g.ghost_mode

        # The tile-editor draws its own readouts at the same left column, so hide
        # the play status stack while editing.
        self.status.visible = not g.debug_mode

        # The hint hides when typing, in the inventory, in debug mode, or when the
        # full help overlay is up.
        self.hint.visible = not (g.typing or g.inventory_ui.visible
                                 or g.debug_mode or g.show_help)

        self.ui.update(g.viewport.mouse_pos())

    def draw(self):
        surf = self.game.screen
        self.ui.draw(surf)
        self._draw_dialogue(surf)
        self._draw_chat(surf)
        self._draw_minimap(surf)
        if self.game.show_help and not (self.game.typing or self.game.debug_mode
                                        or self.game.inventory_ui.visible):
            self._draw_help_overlay(surf)
        if self.game.show_player_list:
            self._draw_player_list(surf)
        if self.game.show_server_list:
            self._draw_server_list(surf)

    # -- imperative overlays ---------------------------------------------
    def _draw_dialogue(self, surf):
        g = self.game
        if not g.dialogue_text:
            return
        elapsed = time.time() - g.dialogue_time
        if elapsed >= g.dialogue_duration:
            g.dialogue_text = None
            return
        # Fade out over the last half-second.
        alpha = 255 if elapsed < g.dialogue_duration - 0.5 \
            else int(255 * (g.dialogue_duration - elapsed) / 0.5)

        box_w = min(g.screen_w - 40, 400)
        box_h = 60
        box_x = (g.screen_w - box_w) // 2
        box_y = g.screen_h - 150
        box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(box, (0, 0, 50, min(200, alpha)), (0, 0, box_w, box_h))
        pygame.draw.rect(box, (100, 100, 200, min(255, alpha)),
                         (0, 0, box_w, box_h), 2)
        surf.blit(box, (box_x, box_y))

        font = g.font_small
        text_y = box_y + 10
        for line in self._wrap(g.dialogue_text, font, box_w - 20)[:3]:
            ts = font.render(line, True, (255, 255, 255))
            ts.set_alpha(alpha)
            surf.blit(ts, (box_x + 10, text_y))
            text_y += 18

    @staticmethod
    def _wrap(text, font, max_w):
        lines, cur = [], ""
        for word in text.split():
            test = cur + (" " if cur else "") + word
            if font.size(test)[0] < max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def _build_chat_line(self, g, msg):
        ts = g.font.render(msg[:60], True, (255, 255, 255))
        plate = pygame.Surface((ts.get_width() + 10, ts.get_height() + 4))
        plate.fill((0, 0, 0))
        plate.set_alpha(150)
        return (ts, plate)

    def _draw_chat(self, surf):
        g = self.game
        slice_ = tuple(g.chat_messages[-5:])
        if slice_ != self._chat_slice:
            old_cache = self._chat_cache
            self._chat_cache = {
                msg: old_cache[msg] if msg in old_cache else self._build_chat_line(g, msg)
                for msg in slice_
            }
            self._chat_slice = slice_

        y = g.screen_h - 60
        for msg in reversed(slice_):
            ts, plate = self._chat_cache[msg]
            surf.blit(plate, (5, y - 2))
            surf.blit(ts, (10, y))
            y -= 20

        if g.typing:
            pygame.draw.rect(surf, (0, 0, 0),
                             (5, g.screen_h - 30, g.screen_w - 10, 25))
            ts = g.font.render(f"> {g.chat_input}_", True, (255, 255, 0))
            surf.blit(ts, (10, g.screen_h - 25))

    def _draw_minimap(self, surf):
        g = self.game
        if g.minimap_visible and not g.minimap_surface and not g.minimap_data:
            # Tier 4b: no live PLO_MINIMAP data - try the PLO_BIGMAP world
            # image instead (classic gmap worlds ship one, not the other).
            g._ensure_bigmap_surface()
        if not (g.minimap_visible and g.minimap_surface):
            return
        mw, mh = g.minimap_size
        mx = g.screen_w - mw - 10
        my = 10
        border = pygame.Rect(mx - 2, my - 2, mw + 4, mh + 4)
        pygame.draw.rect(surf, (100, 100, 100), border)
        pygame.draw.rect(surf, (50, 50, 50), border, 2)
        surf.blit(g.minimap_surface, (mx, my))
        if g.client._current_level_name:
            if getattr(g, '_minimap_is_bigmap', False) and g.client.gmap_width > 0:
                # A bigmap image covers the whole gmap, so the dot is the
                # player's fractional position across the full grid, not one
                # 64x64 segment.
                span_x = g.client.gmap_width * 64
                span_y = g.client.gmap_height * 64
                frac_x = (g.client.x % span_x) / span_x if span_x else 0.0
                frac_y = (g.client.y % span_y) / span_y if span_y else 0.0
            else:
                frac_x = (g.client.x % 64) / 64
                frac_y = (g.client.y % 64) / 64
            dot_x = int(mx + frac_x * mw)
            dot_y = int(my + frac_y * mh)
            pygame.draw.circle(surf, (255, 0, 0), (dot_x, dot_y), 3)
            pygame.draw.circle(surf, (255, 255, 255), (dot_x, dot_y), 3, 1)

    def _draw_help_overlay(self, surf):
        g = self.game
        pad, line_h, w = 14, 22, 320
        h = pad * 2 + 28 + line_h * len(self.HELP_LINES)
        x = (g.screen_w - w) // 2
        y = (g.screen_h - h) // 2

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 200), (0, 0, w, h), border_radius=8)
        pygame.draw.rect(panel, (120, 120, 160, 255), (0, 0, w, h),
                         width=2, border_radius=8)
        surf.blit(panel, (x, y))

        surf.blit(g.font.render("Controls", True, (255, 255, 255)),
                  (x + pad, y + pad))
        ty = y + pad + 30
        for key, desc in self.HELP_LINES:
            surf.blit(g.font_small.render(key, True, (255, 220, 120)),
                      (x + pad, ty))
            surf.blit(g.font_small.render(desc, True, (225, 225, 225)),
                      (x + pad + 110, ty))
            ty += line_h

    # -- F7 player list / F8 server list ----------------------------------
    def _draw_list_overlay(self, surf, title, rows, sel, footer):
        """Shared modal list: title, selectable rows (highlighted at `sel`), and
        a footer hint. `rows` is a list of display strings."""
        g = self.game
        pad, line_h, w = 14, 22, 360
        body = rows if rows else ["(none)"]
        h = pad * 2 + 30 + line_h * len(body) + 24
        x = (g.screen_w - w) // 2
        y = (g.screen_h - h) // 2

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 210), (0, 0, w, h), border_radius=8)
        pygame.draw.rect(panel, (120, 120, 160, 255), (0, 0, w, h),
                         width=2, border_radius=8)
        surf.blit(panel, (x, y))

        surf.blit(g.font.render(title, True, (255, 255, 255)), (x + pad, y + pad))
        ty = y + pad + 30
        for i, row in enumerate(body):
            if rows and i == sel:
                hl = pygame.Surface((w - pad * 2, line_h), pygame.SRCALPHA)
                hl.fill((90, 90, 150, 180))
                surf.blit(hl, (x + pad, ty - 2))
            color = (255, 255, 255) if rows else (160, 160, 160)
            surf.blit(g.font_small.render(row[:48], True, color), (x + pad + 4, ty))
            ty += line_h
        surf.blit(g.font_small.render(footer, True, (180, 180, 200)),
                  (x + pad, ty + 4))

    def _draw_player_list(self, surf):
        g = self.game
        players = g._other_players()
        sel = min(g.player_list_sel, max(0, len(players) - 1))
        rows = [label for _pid, label in players]
        if g.pm_target_id is not None:
            # Composing a PM: show the input line as the footer.
            name = g._player_label(g.pm_target_id)
            footer = f"PM {name}: {g.pm_input}_"
        else:
            footer = "Up/Down select · Enter to PM · F7/Esc close"
        self._draw_list_overlay(surf, "Players", rows, sel, footer)

    def _draw_server_list(self, surf):
        g = self.game
        sel = min(g.server_list_sel, max(0, len(g.servers) - 1))
        rows = []
        for s in g.servers:
            name = getattr(s, "display_name", getattr(s, "name", "?"))
            pc = getattr(s, "player_count", "")
            rows.append(f"{name}  ({pc})" if pc != "" else str(name))
        self._draw_list_overlay(surf, "Servers", rows, sel,
                                "Up/Down select · Enter to connect · F8/Esc close")
