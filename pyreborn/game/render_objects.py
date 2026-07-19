"""LevelObjectsRenderMixin — chests and signs (client-side level overlays).

Split from render.py; methods operate on the GameClient instance."""

from typing import Optional

import pygame

from .constants import TILE_SIZE


_ITEM_COLORS = {
    'greenrupee': (60, 220, 90), 'bluerupee': (70, 140, 230), 'redrupee': (230, 70, 70),
    'goldrupee': (230, 200, 60),
    'bombs': (60, 60, 70), 'bomb': (60, 60, 70), 'superbomb': (120, 60, 140),
    'joltbomb': (230, 230, 80), 'darts': (200, 200, 200),
    'heart': (230, 60, 90), 'fullheart': (230, 60, 90),
    'glove1': (150, 110, 70), 'glove2': (110, 80, 50),
    'bow': (200, 160, 90), 'shield': (150, 150, 200), 'mirrorshield': (220, 220, 255),
    'lizardshield': (90, 200, 90), 'sword': (210, 210, 220), 'battleaxe': (180, 120, 80),
    'goldensword': (230, 200, 60), 'lizardsword': (90, 200, 90),
    'fireball': (250, 140, 40), 'fireblast': (250, 90, 20), 'nukeshot': (255, 255, 120),
    'spinattack': (200, 80, 220),
}
_DEFAULT_ITEM_COLOR = (220, 220, 100)

# item_type -> (sheet, x, y, w, h) tile-authentic pics1.png source rect for
# LevelItem ground-item icons. Deliberately empty: a research pass (2026-07)
# for the real crop table came up dry across every reference we're allowed to
# use --
#   - the C# client checkout (Preagonal) never ships pixel positions, only
#     name<->index tables (getitemindex asm) plus per-item *default GS1
#     scripts* returned by TGUIScriptLoader::getDefaultItemScript, which are
#     zlib-compressed data blobs baked into the decompiled binary (not
#     recoverable as text from the .s dumps we have)
#   - GServer-v2's server/include/level/LevelItem.h and
#     server/src/level/LevelItem.cpp only map LevelItemType <-> name/effect;
#     the server never sends or knows a sprite rect (that's purely a client
#     art concern)
#   - pyReborn's own tools/chest_picker.py precedent (chests) and the
#     funtimes GS1 level corpus have nothing for items either
#   - eyeballing pyreborn/assets/dustynewpics1.png directly (dumped as a
#     gridded contact sheet during this pass) shows a terrain/dungeon
#     tileset with no distinct icon strip to identify rupees/hearts/bombs/
#     swords/shields against, so guessing tile coordinates from that image
#     would be exactly the "invent it blind" mistake to avoid
# so every item currently falls through to the vector icon in
# _get_item_sprite(). Add verified (sheet, x, y, w, h) entries here once a
# real source turns up (e.g. a live-server capture, like chest_picker.py did
# for chests) -- _get_item_sprite() already knows how to use them.
_ITEM_SPRITE_TABLE = {}


class LevelObjectsRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _current_segment_info(self):
        """Return the current segment's level name and world-tile origin."""
        level_name = self.client._current_level_name
        if self.client.in_gmap_segment:
            grid = next((cell for cell, name in self.client.gmap_grid.items()
                         if name == level_name), None)
            if grid is not None:
                return level_name, grid[0] * 64, grid[1] * 64
        return level_name, 0, 0

    def _current_segment_origin(self):
        """World-tile (x, y) origin (top-left) of the CURRENT level segment:
        (0, 0) on a standalone level, or the gmap grid cell's origin when in
        a GMAP. Used to fold level-local (0-63) state (chests, signs) into
        world coords, or vice versa, without a %64 wraparound -- see
        _check_and_render_signs / _render_chests."""
        _, origin_x, origin_y = self._current_segment_info()
        return origin_x, origin_y

    def _get_item_sprite(self, item_type: str) -> pygame.Surface:
        """Build (and cache) a ground-item icon.

        Looks up `item_type` in _ITEM_SPRITE_TABLE and, if present, crops the
        tile-authentic pics1.png rect via sprite_mgr.get_sprite() (same path
        _get_chest_sprite uses for the tileset). _ITEM_SPRITE_TABLE is
        currently empty - see its module-level comment for the research that
        came up dry - so every item falls through to the vector icon below,
        matching the style already used for the HUD's rupee/bomb/arrow
        counters (game/hud.py StatsPanel._stat_icon). Type-correct and pop on
        pickup either way; the vector path just isn't pixel-authentic Reborn
        art."""
        cache = getattr(self, "_item_sprite_cache", None)
        if cache is None:
            cache = self._item_sprite_cache = {}
        if item_type in cache:
            return cache[item_type]

        rect = _ITEM_SPRITE_TABLE.get(item_type)
        if rect is not None:
            sheet, sx, sy, sw, sh = rect
            cropped = self.sprite_mgr.get_sprite(sheet, sx, sy, sw, sh)
            if cropped is not None:
                if cropped.get_size() != (TILE_SIZE, TILE_SIZE):
                    cropped = pygame.transform.scale(cropped, (TILE_SIZE, TILE_SIZE))
                cache[item_type] = cropped
                return cropped
            # Table entry exists but the sheet/crop isn't available (e.g. a
            # headless test with no asset search paths) - fall back to the
            # vector icon, and only warn about it once per item type instead
            # of every frame it's on the ground.
            logged = getattr(self, "_item_sprite_miss_logged", None)
            if logged is None:
                logged = self._item_sprite_miss_logged = set()
            if item_type not in logged:
                logged.add(item_type)
                print(f"Item sprite miss for '{item_type}': {sheet} unavailable, using vector fallback")

        surf = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        color = _ITEM_COLORS.get(item_type, _DEFAULT_ITEM_COLOR)
        cx, cy = TILE_SIZE // 2, TILE_SIZE // 2
        outline = tuple(max(0, c - 90) for c in color)

        if 'rupee' in item_type:
            pts = [(cx, 1), (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)]
            pygame.draw.polygon(surf, color, pts)
            pygame.draw.polygon(surf, outline, pts, 1)
        elif 'heart' in item_type:
            pygame.draw.circle(surf, color, (cx - 3, cy - 1), 4)
            pygame.draw.circle(surf, color, (cx + 3, cy - 1), 4)
            pygame.draw.polygon(surf, color, [(2, cy), (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 2)])
        elif 'bomb' in item_type or item_type == 'darts':
            pygame.draw.circle(surf, color, (cx, cy + 2), 6)
            pygame.draw.circle(surf, outline, (cx, cy + 2), 6, 1)
            pygame.draw.line(surf, (200, 150, 60), (cx + 3, cy - 3), (cx + 5, cy - 7), 2)
        elif 'sword' in item_type or item_type == 'battleaxe':
            pygame.draw.line(surf, color, (cx, 1), (cx, TILE_SIZE - 5), 3)
            pygame.draw.line(surf, outline, (3, 5), (TILE_SIZE - 3, 5), 2)
        elif 'shield' in item_type:
            pygame.draw.polygon(surf, color, [(2, 2), (TILE_SIZE - 2, 2),
                                              (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)])
            pygame.draw.polygon(surf, outline, [(2, 2), (TILE_SIZE - 2, 2),
                                                (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)], 1)
        elif item_type == 'bow':
            pygame.draw.arc(surf, color, (2, 1, TILE_SIZE - 4, TILE_SIZE - 2), -1.4, 1.4, 2)
        else:
            pygame.draw.rect(surf, color, (3, 3, TILE_SIZE - 6, TILE_SIZE - 6), border_radius=3)
            pygame.draw.rect(surf, outline, (3, 3, TILE_SIZE - 6, TILE_SIZE - 6), 1, border_radius=3)

        cache[item_type] = surf
        return surf

    def _render_items(self):
        """Draw ground items from client state (PLO_ITEMADD/PLO_ITEMDEL). Reads
        client.items live each frame, like baddies/chests - pickup already
        removes the entry client-side so it just stops being drawn."""
        items = getattr(self.client, "items", None)
        if not items:
            return
        surf_w, surf_h = self.screen.get_size()
        for (ix, iy), item_type in items.items():
            sprite = self._get_item_sprite(item_type)
            sx, sy = self._world_to_screen(ix, iy)
            if sx < -TILE_SIZE or sx > surf_w or sy < -TILE_SIZE or sy > surf_h:
                continue
            self.screen.blit(sprite, (int(sx), int(sy)))

    def _get_chest_sprite(self, opened: bool) -> Optional[pygame.Surface]:
        """Build (and cache) the chest sprite from tileset tiles.

        Chests are a client-side overlay (not baked into the level board), so we
        composite the chest graphic from the tileset here, using distinct tiles
        for the open vs closed state.
        """
        cache = getattr(self, "_chest_sprite_cache", None)
        if cache is None:
            cache = {}
            self._chest_sprite_cache = cache
        if opened in cache:
            return cache[opened]

        layout = self.CHEST_TILES_OPEN if opened else self.CHEST_TILES_CLOSED
        rows = len(layout)
        cols = len(layout[0])
        surf = pygame.Surface((cols * TILE_SIZE, rows * TILE_SIZE), pygame.SRCALPHA)

        drew_any = False
        for ry, row in enumerate(layout):
            for cx, tile_id in enumerate(row):
                tile = self.tileset_mgr.get_tile(tile_id)
                if tile:
                    surf.blit(tile, (cx * TILE_SIZE, ry * TILE_SIZE))
                    drew_any = True

        if not drew_any:
            # Tileset may not be ready yet — don't cache the miss, retry later.
            return None

        cache[opened] = surf
        return surf
    def _render_chests(self):
        """Draw level chests from client state, reflecting open/closed."""
        level_name, origin_x, origin_y = self._current_segment_info()
        chests = self.client.chests_in_level(level_name)
        if not chests:
            return

        # Cull against the actual draw surface — while zoomed that's the smaller
        # offscreen scene, not the full canvas, so SCREEN_WIDTH/HEIGHT are wrong.
        surf_w, surf_h = self.screen.get_size()
        # Chest keys are level-local (0-63; see client.py's PLO_LEVELCHEST
        # handler); _world_to_screen wants world coords, so add the current
        # segment's grid origin back on -- else every chest off the origin
        # gmap segment rendered at its bare local coordinate instead of its
        # real position.
        for (cx, cy), opened in chests.items():
            sprite = self._get_chest_sprite(bool(opened))
            if sprite is None:
                continue
            # Chest tile (cx, cy) is the top-left of its 2x2 footprint, and the
            # sprite is exactly 2 tiles wide, so it maps straight to that tile.
            sx, sy = self._world_to_screen(cx + origin_x, cy + origin_y)
            if sx < -sprite.get_width() or sx > surf_w or \
               sy < -sprite.get_height() or sy > surf_h:
                continue
            self.screen.blit(sprite, (int(sx), int(sy)))
    def _check_and_render_signs(self):
        """Check if player is near a sign in the current level and show popup."""
        signs = self.client.signs.get(self.client._current_level_name)
        if not signs:
            return

        # Sign coords are LOCAL (0-63); fold the player's world feet position
        # to the CURRENT level segment's local frame via a signed offset from
        # that segment's grid origin, not a raw %64 wrap -- wrapping snaps a
        # position just past a segment's edge (e.g. world x=64.9 in gmap
        # segment (0,0)) back to a low local value, making near-edge signs
        # look far away and signs on the level's opposite edge falsely
        # trigger.
        origin_x, origin_y = self._current_segment_origin()

        # Feet/ground-sample point matches collision.py's PLAYER_FEET_DX/DY
        # (classic-engine spec: collision-box centre, x+1.5/y+2.5).
        px = self.client.player.x + 1.5 - origin_x
        py = self.client.player.y + 2.5 - origin_y

        for (sx, sy), text in signs.items():
            # Compare against the sign TILE CENTRE (+0.5): flush against a
            # blocking sign the feet sample sits exactly 2.0 tiles from the
            # anchor, so an anchor-based `< 2` misses at the only distance a
            # walking player can actually reach.
            if abs(px - (sx + 0.5)) < 2 and abs(py - (sy + 0.5)) < 2:
                self._render_sign_popup(text)
                break  # Only show one sign at a time
    def _render_sign_popup(self, text: str):
        """Render sign text as popup overlay."""
        if not text:
            return

        # Render sign text in a box at bottom of screen
        font = getattr(self, '_sign_font', None)
        if font is None:
            try:
                self._sign_font = pygame.font.Font(None, 24)
            except:
                self._sign_font = pygame.font.SysFont('monospace', 20)
            font = self._sign_font

        # Split text into lines
        lines = text.split('\n')
        line_height = font.get_linesize()
        max_width = 0
        rendered_lines = []

        for line in lines:
            rendered = font.render(line, True, (0, 0, 0))
            rendered_lines.append(rendered)
            max_width = max(max_width, rendered.get_width())

        # Create background box
        box_width = max_width + 20
        box_height = len(rendered_lines) * line_height + 20
        box_x = (self.screen_w - box_width) // 2
        box_y = self.screen_h - box_height - 60  # Above the UI bar

        # Draw box with border
        pygame.draw.rect(self.screen, (240, 230, 200), (box_x, box_y, box_width, box_height))
        pygame.draw.rect(self.screen, (100, 80, 50), (box_x, box_y, box_width, box_height), 2)

        # Draw text
        y = box_y + 10
        for rendered in rendered_lines:
            x = box_x + (box_width - rendered.get_width()) // 2
            self.screen.blit(rendered, (x, y))
            y += line_height
