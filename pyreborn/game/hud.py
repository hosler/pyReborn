"""game/hud.py — the in-game heads-up display.

This replaces the ~200-line `_render_ui` god-method that mixed panel geometry,
status text, chat, dialogue, minimap and a hand-rolled `ui_y += 20` cursor all in
one place. The crustiest part was that vertical cursor: every conditional status
line had to remember to advance `ui_y`, so adding/removing a line meant chasing
the bookkeeping.

The fix follows the same Gui*Ctrl-composite inspiration as ui.py (Preagonal):
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

from .constants import SCREEN_WIDTH, SCREEN_HEIGHT
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
        plate = pygame.Surface((self.w, self.h))
        plate.fill((0, 0, 0))
        plate.set_alpha(self.bg_alpha)
        surf.blit(plate, self.rect.topleft)
        surf.blit(self._surf, (self.rect.x + self.PAD_X, self.rect.y + self.PAD_Y))


class StatsPanel(Widget):
    """Top-left core HUD: hearts row + rupee/bomb/arrow counters, drawn live from
    the player. Self-contained so the panel geometry lives in one place."""

    def __init__(self, game):
        super().__init__(0, 0, TOPLEFT, (6, 6))
        self.game = game

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

    def _draw(self, surf):
        player = self.game.client.player
        hd = self.game.heart_display
        hearts_w = int(player.max_hearts) * (hd.HEART_SIZE + hd.HEART_SPACING)
        panel_w = max(168, hearts_w + 16)
        plate = pygame.Surface((panel_w, 52), pygame.SRCALPHA)
        pygame.draw.rect(plate, (0, 0, 0, 130), (0, 0, panel_w, 52), border_radius=6)
        surf.blit(plate, (6, 6))

        hd.render(surf, player.hearts, player.max_hearts)

        icon_y = 32
        x = self._stat_icon(surf, 12, icon_y, 'rupee', player.rupees)
        x = self._stat_icon(surf, x + 12, icon_y, 'bomb', player.bombs)
        self._stat_icon(surf, x + 12, icon_y, 'arrow', player.arrows)


class HUD:
    """Owns the play HUD: a declarative widget tree plus a few imperative draws."""

    HELP_LINES = [
        ("Arrow Keys", "Move"),
        ("A", "Grab / Pick up / Throw"),
        ("S or Space", "Swing sword"),
        ("D", "Use weapon"),
        ("Q", "Inventory"),
        ("M", "Toggle minimap"),
        ("Enter", "Chat"),
        ("F1", "Debug / tile editor"),
        ("H", "Close this help"),
    ]

    def __init__(self, game):
        self.game = game
        self.ui = UIManager(game.fonts, SCREEN_WIDTH, SCREEN_HEIGHT)

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
        self.status.add(self.badge_swim, self.badge_door,
                        self.badge_carry, self.badge_sit)
        self.ui.root.add(self.status)

        # Top-right "H: Help" hint and centered ghost-mode banner.
        self.hint = Label("H: Help", role="small", color=(210, 210, 210),
                          anchor=TOPRIGHT, offset=(-10, 10))
        self.ghost = Badge("GHOST MODE", color=(200, 200, 255),
                           anchor=MIDTOP, offset=(0, 50), visible=False)
        self.ui.root.add(self.hint, self.ghost)

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

        box_w = min(SCREEN_WIDTH - 40, 400)
        box_h = 60
        box_x = (SCREEN_WIDTH - box_w) // 2
        box_y = SCREEN_HEIGHT - 150
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

    def _draw_chat(self, surf):
        g = self.game
        y = SCREEN_HEIGHT - 60
        for msg in reversed(g.chat_messages[-5:]):
            ts = g.font.render(msg[:60], True, (255, 255, 255))
            plate = pygame.Surface((ts.get_width() + 10, ts.get_height() + 4))
            plate.fill((0, 0, 0))
            plate.set_alpha(150)
            surf.blit(plate, (5, y - 2))
            surf.blit(ts, (10, y))
            y -= 20

        if g.typing:
            pygame.draw.rect(surf, (0, 0, 0),
                             (5, SCREEN_HEIGHT - 30, SCREEN_WIDTH - 10, 25))
            ts = g.font.render(f"> {g.chat_input}_", True, (255, 255, 0))
            surf.blit(ts, (10, SCREEN_HEIGHT - 25))

    def _draw_minimap(self, surf):
        g = self.game
        if not (g.minimap_visible and g.minimap_surface):
            return
        mw, mh = g.minimap_size
        mx = SCREEN_WIDTH - mw - 10
        my = 10
        border = pygame.Rect(mx - 2, my - 2, mw + 4, mh + 4)
        pygame.draw.rect(surf, (100, 100, 100), border)
        pygame.draw.rect(surf, (50, 50, 50), border, 2)
        surf.blit(g.minimap_surface, (mx, my))
        if g.client._current_level_name:
            local_x = g.client.x % 64
            local_y = g.client.y % 64
            dot_x = int(mx + (local_x / 64) * mw)
            dot_y = int(my + (local_y / 64) * mh)
            pygame.draw.circle(surf, (255, 0, 0), (dot_x, dot_y), 3)
            pygame.draw.circle(surf, (255, 255, 255), (dot_x, dot_y), 3, 1)

    def _draw_help_overlay(self, surf):
        g = self.game
        pad, line_h, w = 14, 22, 320
        h = pad * 2 + 28 + line_h * len(self.HELP_LINES)
        x = (SCREEN_WIDTH - w) // 2
        y = (SCREEN_HEIGHT - h) // 2

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
