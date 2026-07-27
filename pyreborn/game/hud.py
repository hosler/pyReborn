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
from typing import Optional, Tuple

import pygame

from . import theme
from .assets import render_outlined_text
from .ui import UIManager, Panel, Label, Widget, TOPLEFT, TOPRIGHT, MIDTOP
from .minimap import aspect_fit, map_entity_positions
from ..inventory_ui import resolve_weapon_indicator


# showstats bits (GServer-v2 docs, "showstats"): which default-HUD elements
# the client draws. A scripted HUD hides the built-in one with
# `showstats(allstats - <bits>)`; gs1_client.py stores the mask on
# ClientGS1.stats_mask (None = showstats never called = show everything) and
# this module gates each element on its bit. Generic: any server's script
# controls this, nothing here is server-specific.
STAT_ASD = 1          # A/S/D item slots (our weapon-slot indicator)
STAT_ICONS = 2        # gralat/bomb/arrow icons
STAT_RUPEES = 4       # gralat (rupee) count
STAT_BOMBS = 8        # bomb count
STAT_ARROWS = 16      # arrow count
STAT_HEARTS = 32      # hearts row
STAT_AP = 64          # alignment bar
STAT_MP = 128         # magic bar
STAT_MINIMAP = 256    # minimap
STAT_INVENTORY = 512  # inventory npcs (not drawn by this HUD)
STAT_PLAYERS = 1024   # players (not gated here; render_entities draws them)
ALLSTATS = 2047
_STATS_PANEL_BITS = (STAT_ASD | STAT_ICONS | STAT_RUPEES | STAT_BOMBS
                     | STAT_ARROWS | STAT_HEARTS | STAT_AP | STAT_MP)


def stats_mask(game) -> int:
    """The active showstats bitmask (ALLSTATS when no script ever called
    showstats). Reads ClientGS1.stats_mask — the single store both GS1 and
    GS2 scripts write through."""
    mask = getattr(getattr(game, "gs1", None), "stats_mask", None)
    return ALLSTATS if mask is None else int(mask)


def chat_window(total: int, scroll: int, window: int = 5) -> Tuple[int, int]:
    """[start, end) indices into chat_messages for the visible chat-log slice.

    `scroll` is messages back from the live tail (0 = tail, matching
    game/input.py's PageUp/PageDown bookkeeping). Pure function (no pygame,
    no widget state) so the scroll-window math is unit-testable on its own --
    see HUD._draw_chat, the only caller.
    """
    if scroll <= 0:
        return max(0, total - window), total
    end = max(0, total - scroll)
    start = max(0, end - window)
    return start, end


class Badge(Widget):
    """A line of text on a translucent black plate — the old `_draw_text_with_bg`
    as a self-sizing widget so it can live in a vstack."""

    PAD_X, PAD_Y = 5, 2

    def __init__(self, text="", *, color=theme.TEXT, role="hud",
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
            self._plate.fill(theme.PLATE)
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
        # Icons (rupee/bomb/arrow counters + MP/AP bars) only actually change
        # when one of the values they show changes, not every frame - cache
        # the composited result and just re-blit it otherwise.
        self._icons_surf: Optional[pygame.Surface] = None
        self._icons_key = None

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
        # Outlined so the count stays legible over bright level tiles showing
        # through the panel's semi-transparent plate, not just the dark case.
        txt = render_outlined_text(self.game.font_small, str(count), theme.TEXT)
        surf.blit(txt, (x + 16, y + 1))
        return x + 16 + txt.get_width()

    def _stat_bar(self, surf, x, y, w, label, value, maxvalue, color):
        """A small labeled bar for MP/AP (no icon art for these exists)."""
        h = 6
        pygame.draw.rect(surf, theme.BAR_TRACK, (x, y, w, h), border_radius=2)
        if maxvalue > 0:
            fill_w = max(0, min(w, int(w * value / maxvalue)))
            if fill_w > 0:
                pygame.draw.rect(surf, color, (x, y, fill_w, h), border_radius=2)
        pygame.draw.rect(surf, theme.NIGHT_DEEP, (x, y, w, h), 1, border_radius=2)
        txt = render_outlined_text(self.game.font_small, label, theme.TEXT_DIM)
        surf.blit(txt, (x, y - 12))

    def _draw(self, surf):
        mask = stats_mask(self.game)
        if not (mask & _STATS_PANEL_BITS):
            # a scripted HUD hid every element this panel draws (showstats):
            # no plate, no slot — nothing.
            return
        player = self.game.client.player
        hd = self.game.heart_display
        hearts_w = min(hd.HEARTS_PER_ROW, int(player.max_hearts)) * (hd.HEART_SIZE + hd.HEART_SPACING)
        panel_w = max(218, hearts_w + 16)
        heart_rows = max(1, (int(player.max_hearts) + hd.HEARTS_PER_ROW - 1) // hd.HEARTS_PER_ROW)

        # Tier 3a: MP (magic) / AP (alignment) bars, from PLPROP_MAGICPOINTS(26)
        # / PLPROP_ALIGNMENT(32) via packets.py's parse_player_props ->
        # Player.mp/.ap. Both fields always exist on Player (defaults 0/50),
        # so this row shows as soon as the HUD renders, not just after the
        # server's first PLO_PLAYERPROPS - getattr keeps this tolerant of
        # any caller passing a bare object without the fields.
        mp = getattr(player, 'mp', None)
        ap = getattr(player, 'ap', None)
        show_mp_ap = mp is not None or ap is not None
        panel_h = 52 + (heart_rows - 1) * (hd.HEART_SIZE + hd.HEART_SPACING) + (20 if show_mp_ap else 0)

        plate_key = (panel_w, panel_h)
        if plate_key != self._plate_key:
            self._plate = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            pygame.draw.rect(self._plate, theme.plate_rgba(150),
                             (0, 0, panel_w, panel_h), border_radius=6)
            pygame.draw.rect(self._plate, (*theme.FOREST, 200),
                             (0, 0, panel_w, panel_h), 1, border_radius=6)
            self._plate_key = plate_key
        surf.blit(self._plate, (6, 6))

        if mask & STAT_HEARTS:
            hd.render(surf, player.hearts, player.max_hearts)

        max_mp = getattr(player, 'max_mp', 100) or 100
        max_ap = getattr(player, 'max_ap', 100) or 100
        icons_key = (panel_w, panel_h, player.rupees, player.bombs,
                    player.arrows, mp, ap, max_mp, max_ap, mask)
        if icons_key != self._icons_key:
            # Drawn into a panel-local surface (same (6, 6) origin as
            # `self._plate` above) so it can be cached and blitted as one
            # unit rather than redrawn from scratch every frame.
            icons = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            icon_y = 32 + (heart_rows - 1) * (hd.HEART_SIZE + hd.HEART_SPACING)
            # Each counter is icon+count as one unit, gated on its count
            # bit (a hidden counter also frees its slot in the row).
            x = 6
            if mask & STAT_RUPEES:
                x = self._stat_icon(icons, x, icon_y - 6, 'rupee',
                                    player.rupees) + 12
            if mask & STAT_BOMBS:
                x = self._stat_icon(icons, x, icon_y - 6, 'bomb',
                                    player.bombs) + 12
            if mask & STAT_ARROWS:
                self._stat_icon(icons, x, icon_y - 6, 'arrow', player.arrows)

            if show_mp_ap:
                bar_y = icon_y + 30 - 6
                bar_w = (panel_w - 24 - 12) // 2
                if mp is not None and mask & STAT_MP:
                    self._stat_bar(icons, 6, bar_y, bar_w, "MP", mp, max_mp,
                                   (90, 140, 255))
                if ap is not None and mask & STAT_AP:
                    self._stat_bar(icons, 6 + bar_w + 12, bar_y, bar_w, "AP", ap,
                                   max_ap, (230, 200, 80))
            self._icons_surf = icons
            self._icons_key = icons_key
        surf.blit(self._icons_surf, (6, 6))

        if not (mask & STAT_ASD):
            return
        name, image, weapon = resolve_weapon_indicator(
            self.game.client.weapons,
            self.game.inventory_ui.selected_weapon_idx,
            self.game.sprite_mgr)
        if weapon is None and image:
            # The weapon HAS an icon image, it just isn't downloaded yet —
            # fetch it through the once-only asset path (on_file caches it
            # into the shared sprite cache resolve_weapon_indicator loads
            # from) so the slot upgrades from the text fallback to the real
            # art when it lands. Text stays only for weapons with no icon or
            # a server-side failed file.
            self.game._request_asset(image)
        slot = pygame.Rect(6 + panel_w - 43, 12, 36, 36)
        pygame.draw.rect(surf, theme.SLOT_BG, slot, border_radius=4)
        pygame.draw.rect(surf, theme.EMERALD_DEEP, slot, 1, border_radius=4)
        if weapon is not None:
            fit = min(30 / weapon.get_width(), 30 / weapon.get_height())
            size = (max(1, round(weapon.get_width() * fit)),
                    max(1, round(weapon.get_height() * fit)))
            icon = pygame.transform.smoothscale(weapon, size)
            surf.blit(icon, (slot.centerx - icon.get_width() // 2,
                             slot.centery - icon.get_height() // 2))
        elif name:
            label = self.game.font_small.render(name[:4], True, theme.TEXT)
            surf.blit(label, (slot.centerx - label.get_width() // 2,
                              slot.centery - label.get_height() // 2))


class HUD:
    """Owns the play HUD: a declarative widget tree plus a few imperative draws."""

    HELP_LINES = [
        ("Arrow Keys", "Move"),
        ("A", "Grab / Pick up / Throw"),
        ("S or Space", "Swing sword"),
        ("D", "Use weapon"),
        ("Q", "Inventory"),
        ("Wheel / 0", "Zoom / reset"),
        ("M", "Open map"),
        ("N", "Noclip (walk through walls)"),
        ("Enter", "Chat"),
        ("F1", "Debug / tile editor"),
        ("F2", "Unstick: warp to (30,30)"),
        ("F7", "Player list / PM"),
        ("F8", "Server list"),
        ("F9", "Settings"),
        ("PageUp/Down", "Scroll chat log"),
        ("H", "Close this help"),
    ]

    def __init__(self, game):
        self.game = game
        self.ui = UIManager(game.fonts, game.screen_w, game.screen_h)

        # Stat panel (a scripted HUD can hide it via showstats — see
        # stats_mask / update()).
        self.stats_panel = StatsPanel(game)
        self.ui.root.add(self.stats_panel)

        # Status-line stack: a vstack does the vertical layout the old `ui_y`
        # cursor did by hand. Each line is preallocated; per frame we just set
        # its text and visibility and the container reflows.
        self.status = Panel(w=420, anchor=TOPLEFT, offset=(5, 64),
                            vstack=True, align=TOPLEFT, spacing=2)
        self.badge_swim = Badge(color=theme.INFO, visible=False)
        self.badge_door = Badge(color=theme.WARN, visible=False)
        self.badge_carry = Badge(color=theme.MINT, visible=False)
        self.badge_sit = Badge(color=theme.WARN, visible=False)
        self.badge_noclip = Badge(color=theme.ERROR, visible=False)
        self.status.add(self.badge_swim, self.badge_door,
                        self.badge_carry, self.badge_sit, self.badge_noclip)
        self.ui.root.add(self.status)

        # Top-right "H: Help" hint and centered ghost-mode banner.
        self.hint = Label("H: Help", role="small", color=theme.TEXT_DIM,
                          anchor=TOPRIGHT, offset=(-10, 10), shadow=True)
        self.ghost = Badge("GHOST MODE", color=theme.MINT_PALE,
                           anchor=MIDTOP, offset=(0, 50), visible=False)
        self.ui.root.add(self.hint, self.ghost)

        # Per-message (text, plate) surfaces for the chat log, rebuilt only
        # when the visible 5-message window of chat_messages actually changes
        # (that window is the live tail normally, or a PageUp/PageDown
        # scrollback slice -- see _draw_chat).
        self._chat_cache = {}
        self._chat_slice = None
        # Cached "-- N back, M new (PageDown/Esc to resume) --" scroll
        # indicator surface, rebuilt only when its text changes.
        self._scroll_indicator_text = None
        self._scroll_indicator_surf = None

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

        # showstats: a scripted HUD hiding every panel element hides the
        # panel widget entirely (StatsPanel._draw also gates per element).
        self.stats_panel.visible = bool(stats_mask(g) & _STATS_PANEL_BITS)

        heart_rows = max(1, (int(player.max_hearts) + 9) // 10)
        self.status.offset = (5, 64 + (heart_rows - 1) * 18)

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
        presentation = getattr(self.game, 'combat_presentation', None)
        if presentation is not None and presentation.death_started is not None:
            return
        input_frozen = getattr(self.game.client, 'input_frozen', False)
        if not input_frozen:
            self.ui.draw(surf)
            self._draw_dialogue(surf)
            self._draw_chat(surf)
            self._draw_minimap(surf)
            if self.game.show_help and not (self.game.typing or self.game.debug_mode
                                            or self.game.inventory_ui.visible):
                self._draw_help_overlay(surf)
        elif self.game.typing:
            # Chat input remains modal and accepts keys during a full stop.
            self._draw_chat(surf, show_log=False)
        if getattr(self.game, 'big_map_visible', False):
            self._draw_big_map(surf)
        if self.game.show_player_list:
            self._draw_player_list(surf)
        if self.game.show_server_list:
            self._draw_server_list(surf)
        settings_ui = getattr(self.game, 'settings_ui', None)
        if settings_ui is not None and settings_ui.visible:
            self._draw_settings(surf)

    # -- imperative overlays ---------------------------------------------
    def _draw_dialogue(self, surf):
        g = self.game
        if not g.dialogue_text:
            return
        alpha = 255

        box_w = min(g.screen_w - 40, 400)
        font = g.fonts.classic() if getattr(g, 'dialogue_classic_font', False) \
            else g.font_small
        lines = g.dialogue_pager.visible_lines
        line_height = font.get_linesize()
        box_h = max(60, len(lines) * line_height + 20)
        box_x = (g.screen_w - box_w) // 2
        box_y = g.screen_h - 150
        box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg = theme.OVERLAY_BG
        pygame.draw.rect(box, (*bg[:3], min(bg[3], alpha)), (0, 0, box_w, box_h))
        pygame.draw.rect(box, (*theme.OVERLAY_BORDER, min(255, alpha)),
                         (0, 0, box_w, box_h), 2)
        surf.blit(box, (box_x, box_y))

        text_y = box_y + 10
        for line in lines:
            ts = font.render(line, True, theme.TEXT)
            ts.set_alpha(alpha)
            surf.blit(ts, (box_x + 10, text_y))
            text_y += line_height

        if g.dialogue_pager.has_more:
            chevron = font.render(">", True, theme.MINT)
            chevron.set_alpha(alpha)
            surf.blit(chevron, (box_x + box_w - chevron.get_width() - 10,
                                box_y + box_h - chevron.get_height() - 6))

    def draw_death_overlay(self, surf):
        """Draw the centered modal death message in the dialogue style."""
        g = self.game
        w, h = min(400, g.screen_w - 40), 118
        x, y = (g.screen_w - w) // 2, (g.screen_h - h) // 2
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, theme.OVERLAY_BG, panel.get_rect(), border_radius=8)
        pygame.draw.rect(panel, (*theme.ERROR_DIM, 255), panel.get_rect(), 2,
                         border_radius=8)
        surf.blit(panel, (x, y))
        font = g.fonts.classic()
        title = font.render("You died", True, theme.TEXT)
        hint = g.font_small.render("Waiting for respawn...", True, theme.TEXT_DIM)
        surf.blit(title, (x + (w - title.get_width()) // 2, y + 24))
        surf.blit(hint, (x + (w - hint.get_width()) // 2, y + 76))

    @staticmethod
    def _wrap(text, font, max_w):
        from .dialogue import wrap_dialogue
        return wrap_dialogue(text, lambda value: font.size(value)[0], max_w)

    def _build_chat_line(self, g, msg):
        ts = g.font.render(msg[:60], True, theme.TEXT)
        plate = pygame.Surface((ts.get_width() + 10, ts.get_height() + 4))
        plate.fill(theme.PLATE)
        plate.set_alpha(150)
        return (ts, plate)

    def _draw_chat(self, surf, show_log=True):
        g = self.game
        total = len(g.chat_messages)
        scroll = g.chat_scroll   # 0 = live tail; >0 = PageUp'd back that many messages
        start, end = chat_window(total, scroll)
        slice_ = tuple(g.chat_messages[start:end])

        if slice_ != self._chat_slice:
            old_cache = self._chat_cache
            self._chat_cache = {
                msg: old_cache[msg] if msg in old_cache else self._build_chat_line(g, msg)
                for msg in slice_
            }
            self._chat_slice = slice_

        y = g.screen_h - 60
        if show_log:
            for msg in reversed(slice_):
                ts, plate = self._chat_cache[msg]
                surf.blit(plate, (5, y - 2))
                surf.blit(ts, (10, y))
                y -= 20

        if show_log and scroll > 0:
            # New messages that arrived while scrolled back still get
            # appended to chat_messages (and counted here) even though
            # they're off-screen until PageDown/Esc resumes the live tail.
            new_count = max(0, g.chat_seq - g._chat_scroll_baseline)
            label = f"-- {scroll} back"
            if new_count:
                label += f", {new_count} new"
            label += " (PageDown/Esc to resume) --"
            if label != self._scroll_indicator_text:
                self._scroll_indicator_text = label
                self._scroll_indicator_surf = g.font_small.render(
                    label, True, theme.WARN)
            surf.blit(self._scroll_indicator_surf, (10, y))

        if g.typing:
            entry = pygame.Rect(5, g.screen_h - 30, g.screen_w - 10, 25)
            pygame.draw.rect(surf, theme.NIGHT_DEEP, entry)
            pygame.draw.rect(surf, theme.EMERALD_DEEP, entry, 1)
            ts = g.font.render(f"> {g.chat_input}_", True, theme.MINT)
            surf.blit(ts, (10, g.screen_h - 25))

    def _draw_minimap(self, surf):
        g = self.game
        if not (stats_mask(g) & STAT_MINIMAP):
            return          # hidden by a script's showstats call
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
        pygame.draw.rect(surf, theme.SURFACE_RAISED, border)
        pygame.draw.rect(surf, theme.MOSS, border, 2)
        surf.blit(g.minimap_surface, (mx, my))
        if g.client._current_level_name:
            for frac_x, frac_y, color in map_entity_positions(g.client):
                dot_x = int(mx + frac_x * mw)
                dot_y = int(my + frac_y * mh)
                pygame.draw.circle(surf, color, (dot_x, dot_y), 3)
                pygame.draw.circle(surf, (30, 30, 30), (dot_x, dot_y), 3, 1)

    def _draw_big_map(self, surf):
        g = self.game
        if not g.minimap_surface:
            g._ensure_bigmap_surface()
        source = g.bigmap_surface
        if source is None:
            source = g._minimap_native_surface
        if source is None:
            source = g.minimap_surface
        if source is None:
            return
        size = aspect_fit(source.get_size(), (g.screen_w - 80, g.screen_h - 80))
        view = pygame.transform.smoothscale(source, size)
        mx, my = (g.screen_w - size[0]) // 2, (g.screen_h - size[1]) // 2
        shade = pygame.Surface((g.screen_w, g.screen_h), pygame.SRCALPHA)
        shade.fill(theme.SHADE)
        surf.blit(shade, (0, 0))
        pygame.draw.rect(surf, theme.EMERALD_DEEP,
                         (mx - 3, my - 3, size[0] + 6, size[1] + 6), 3)
        surf.blit(view, (mx, my))
        for frac_x, frac_y, color in map_entity_positions(g.client):
            dot_x = int(mx + frac_x * size[0])
            dot_y = int(my + frac_y * size[1])
            pygame.draw.circle(surf, color, (dot_x, dot_y), 5)
            pygame.draw.circle(surf, (30, 30, 30), (dot_x, dot_y), 5, 1)

    def _draw_help_overlay(self, surf):
        g = self.game
        pad, line_h, w = 14, 22, 320
        h = pad * 2 + 28 + line_h * len(self.HELP_LINES)
        x = (g.screen_w - w) // 2
        y = (g.screen_h - h) // 2

        theme.draw_panel(surf, pygame.Rect(x, y, w, h))

        surf.blit(g.font.render("Controls", True, theme.MINT_PALE),
                  (x + pad, y + pad))
        ty = y + pad + 30
        for key, desc in self.HELP_LINES:
            surf.blit(g.font_small.render(key, True, theme.MINT),
                      (x + pad, ty))
            surf.blit(g.font_small.render(desc, True, theme.TEXT),
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

        theme.draw_panel(surf, pygame.Rect(x, y, w, h))

        surf.blit(g.font.render(title, True, theme.MINT_PALE), (x + pad, y + pad))
        ty = y + pad + 30
        for i, row in enumerate(body):
            if rows and i == sel:
                hl = pygame.Surface((w - pad * 2, line_h), pygame.SRCALPHA)
                hl.fill(theme.SELECTION)
                surf.blit(hl, (x + pad, ty - 2))
            color = theme.TEXT if rows else theme.TEXT_FAINT
            surf.blit(g.font_small.render(row[:48], True, color), (x + pad + 4, ty))
            ty += line_h
        surf.blit(g.font_small.render(footer, True, theme.TEXT_DIM),
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

    # -- F9 settings overlay ------------------------------------------------
    def _draw_settings(self, surf):
        g = self.game
        su = g.settings_ui
        self._draw_list_overlay(
            surf, "Settings", su.rows(), su.selected,
            "Up/Down select · Left/Right/Enter adjust · F9/Esc close")
