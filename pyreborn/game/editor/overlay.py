"""game/editor/overlay.py — what edit mode draws over the world.

Three layers, all screen-space and all skipped entirely while edit mode is
off: the tile grid and brush cursor, markers for the level objects that are
otherwise invisible (links, and the sign/chest tiles), and the toolbar strip.

Object markers matter more than they look: a link is a plain rectangle of
board with no art at all, so without an overlay a builder cannot see the
warps they are editing.
"""

from __future__ import annotations

from typing import Tuple

import pygame

from reborn_protocol.coords import segment_at, segment_origin

from .. import theme
from ..constants import TILE_SIZE
from .state import OBJECT, OBJECT_KINDS, PAINT, PICKER, RECT, SELECT, TOOLS

GRID_COLOR = (*theme.FOREST, 90)
BRUSH_COLOR = theme.MINT
SELECT_COLOR = (*theme.MINT, 60)
LINK_COLOR = theme.INFO
SIGN_COLOR = theme.WARN
CHEST_COLOR = theme.MINT_PALE
NPC_COLOR = theme.EMERALD_BRIGHT

TOOL_KEYS = {PAINT: "1 paint", RECT: "2 rect", PICKER: "3 pick",
             SELECT: "4 select", OBJECT: "5 object"}


class EditorOverlay:
    """Renders edit mode's world decorations and toolbar."""

    def __init__(self, game, editor):
        self.game = game
        self.editor = editor

    # -- helpers ----------------------------------------------------------

    def _screen_of_local(self, tx: int, ty: int) -> Tuple[float, float]:
        """Level-local tile -> screen pixels, via the camera.

        On a gmap the board the editor paints is one segment, and the camera
        speaks world coordinates, so the segment origin has to come back in.
        """
        client = self.game.client
        if client.in_gmap_segment:
            seg = segment_at(client.player.x, client.player.y)
            ox, oy = segment_origin(*seg)
            tx, ty = tx + ox, ty + oy
        return self.game.camera.world_to_screen(tx, ty)

    def _tile_rect(self, tx: int, ty: int, w: int = 1, h: int = 1) -> pygame.Rect:
        x, y = self._screen_of_local(tx, ty)
        scale = self.game.camera.zoom * TILE_SIZE
        return pygame.Rect(int(x), int(y), max(1, int(w * scale)),
                           max(1, int(h * scale)))

    # -- layers -----------------------------------------------------------

    def draw(self, surf) -> None:
        state = self.editor.state
        if not state.enabled:
            return
        if state.grid_visible:
            self._draw_grid(surf)
        self._draw_objects(surf)
        self._draw_cursor(surf)
        if state.selection is not None:
            x, y, w, h = state.selection
            rect = self._tile_rect(x, y, w, h)
            plate = pygame.Surface(rect.size, pygame.SRCALPHA)
            plate.fill(SELECT_COLOR)
            surf.blit(plate, rect.topleft)
            pygame.draw.rect(surf, theme.MINT, rect, width=1)
        self._draw_toolbar(surf)

    def _draw_grid(self, surf) -> None:
        """A one-tile grid over the level the editor is painting."""
        scale = self.game.camera.zoom * TILE_SIZE
        if scale < 6:
            return                     # unreadable when zoomed far out
        top_left = self._tile_rect(0, 0)
        grid = pygame.Surface((surf.get_width(), surf.get_height()),
                              pygame.SRCALPHA)
        for i in range(65):
            x = top_left.x + i * scale
            y = top_left.y + i * scale
            if 0 <= x <= surf.get_width():
                pygame.draw.line(grid, GRID_COLOR, (x, top_left.y),
                                 (x, top_left.y + 64 * scale))
            if 0 <= y <= surf.get_height():
                pygame.draw.line(grid, GRID_COLOR, (top_left.x, y),
                                 (top_left.x + 64 * scale, y))
        surf.blit(grid, (0, 0))

    def _draw_objects(self, surf) -> None:
        client = self.game.client
        level = self.editor.level_name

        for link in client.links.get(level, ()) or ():
            rect = self._tile_rect(int(link.get('x', 0)), int(link.get('y', 0)),
                                   int(link.get('width', 1)),
                                   int(link.get('height', 1)))
            pygame.draw.rect(surf, LINK_COLOR, rect, width=1)
            self._tag(surf, rect, str(link.get('dest_level', '?')), LINK_COLOR)

        for (sx, sy) in (client.signs.get(level, {}) or {}):
            rect = self._tile_rect(int(sx), int(sy))
            pygame.draw.rect(surf, SIGN_COLOR, rect, width=1)

        for (cx, cy) in (client.chests_in_level(level) or {}):
            rect = self._tile_rect(int(cx), int(cy))
            pygame.draw.rect(surf, CHEST_COLOR, rect, width=1)

        for npc in (client.npcs or {}).values():
            if (not isinstance(npc, dict)
                    or npc.get('_level') != level):
                continue
            tx, ty = self.game._world_to_level_local(npc.get('x', 0),
                                                     npc.get('y', 0))
            pygame.draw.rect(surf, NPC_COLOR, self._tile_rect(tx, ty), width=1)

    def _tag(self, surf, rect: pygame.Rect, text: str, color) -> None:
        label = self.game.font_small.render(text[:18], True, color)
        surf.blit(label, (rect.x + 2, rect.y - label.get_height()))

    def _draw_cursor(self, surf) -> None:
        """The brush footprint under the mouse."""
        state = self.editor.state
        mouse = self.game.viewport.mouse_pos()
        world_x, world_y = self.game.camera.screen_to_world(*mouse)
        tx, ty = self.game._world_to_level_local(world_x, world_y)
        tiles = (state.brush_tiles(tx, ty) if state.tool in (PAINT, RECT)
                 else [(tx, ty)])
        for x, y in tiles:
            pygame.draw.rect(surf, BRUSH_COLOR, self._tile_rect(x, y), width=1)

    # The keys edit mode answers to, drawn as caps so they read at a glance
    # (see theme.draw_key_hints). The tool keys are drawn separately above,
    # with the active one highlighted.
    HINTS = (("LMB", "paint"), ("RMB", "pick"), ("P", "palette"),
             ("G", "grid"), ("[ ]", "brush size"), ("Ctrl+Z/Y", "undo/redo"),
             ("Ctrl+S", "save"), ("Ctrl+Shift+S", "export"), ("F11", "exit"))

    def _draw_toolbar(self, surf) -> None:
        g = self.game
        state = self.editor.state
        font = g.fonts.get("chat")
        parts = [TOOL_KEYS[t].upper() if t == state.tool else TOOL_KEYS[t]
                 for t in TOOLS]
        line = "  ".join(parts)
        if state.tool == OBJECT:
            kinds = " ".join(k.upper() if k == state.object_kind else k
                             for k in OBJECT_KINDS)
            line += f"   [{kinds}]  O cycles"
        line += f"   tile {state.tile}  brush {state.brush}"

        bar_w = min(g.screen_w - 16, 860)
        # tools, the status line when there is one, then up to two hint rows.
        rows = 3 + (1 if state.status else 0)
        bar = pygame.Rect(8, 8, bar_w, 12 + theme.key_hints_height(font, rows))
        theme.draw_panel(surf, bar)
        surf.blit(font.render(line[:96], True, theme.TEXT),
                  (bar.x + 8, bar.y + 6))
        y = bar.y + 6 + theme.key_hints_height(font)
        if state.status:
            surf.blit(font.render(state.status[:96], True, theme.MINT),
                      (bar.x + 8, y))
            y += theme.key_hints_height(font)
        theme.draw_key_hints(surf, font, bar.x + 8, y, self.HINTS,
                             width=bar_w - 16, max_lines=2)
