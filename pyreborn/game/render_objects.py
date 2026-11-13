"""LevelObjectsRenderMixin — chests and signs (client-side level overlays).

Split from render.py; methods operate on the GameClient instance."""

from typing import Optional

import pygame

from reborn_protocol.coords import segment_origin

from ..gmap_coords import grid_of

from .. import ground_items
from ..classic_sprites import draw_sprite
from .constants import TILE_SIZE, PLAYER_STAND_X, PLAYER_STAND_Y
from .clocked import ClockedMixin


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

# TPlayer.cpp:2812-2814 putExtra(..., 0x18): 24 ticks at 20 Hz, no rise or fade.
_CHEST_REVEAL_DURATION_MS = 24 * 50


class LevelObjectsRenderMixin(ClockedMixin):
    """Mixin providing the above methods for GameClient."""

    def _current_segment_info(self):
        """Return the current segment's level name and world-tile origin."""
        level_name = self.client.current_level_name
        if self.client.in_gmap_segment:
            grid = grid_of(self.client.gmap_grid, level_name)
            if grid is not None:
                return (level_name, *segment_origin(*grid))
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
        """Return native item art, or a cached vector fallback without the sheet."""
        # PLO_ITEMADD carries an item index: TClient.cpp:5474-5487,3685-3690.
        # putExtra resolves it through giveitems (the overhead icon's table):
        # Preagonal/FourPlay/quattroplay/src/TServerLevel.cpp:1341-1347;
        # Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1197-1217.
        index = ground_items.item_index(item_type)
        if index is not None:
            sprite = draw_sprite(self.sprite_mgr, ground_items.GIVE_SPRITES[index])
            if sprite is not None:
                return sprite

        # Retry the real art before consulting this fallback cache: sprites.png
        # may arrive from the server after the first item has already appeared.
        cache = self.render_cache.item_sprite
        if item_type in cache:
            return cache[item_type]

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
        """Compatibility entry point for the render smoke harness. Ground items
        are collected by the entity pass now, so this only exists for callers
        that draw them on their own. It JOINS the frame in progress rather than
        opening one: _begin_frame() would drop whatever lights and nameplates
        that frame had already queued."""
        frame = self._frame_context()
        frame.screen_size = self.screen.get_size()
        entities = []
        self._collect_items(entities, frame)
        for entity in entities:
            self._draw_item_entity(entity, frame)

    def _sync_chest_reveals(self, now_ms: int) -> None:
        """Start a reveal when a known chest changes from closed to open."""
        level_name = self.client.current_level_name
        chests = self.client.chests_in_level(level_name)
        snapshots = getattr(self, "_chest_reveal_snapshots", None)
        if snapshots is None:
            snapshots = self._chest_reveal_snapshots = {}
        previous = snapshots.get(level_name)
        current = dict(chests)
        snapshots[level_name] = current

        # The first observation establishes a baseline. This avoids replaying
        # reveals for chests that were already open when the level arrived.
        if previous is None:
            return

        level_items = getattr(self.client, "chest_items", {}).get(level_name, {})
        reveals = getattr(self, "_chest_reveals", None)
        if reveals is None:
            reveals = self._chest_reveals = []
        for position, opened in current.items():
            if not opened or previous.get(position, False):
                continue
            item_type = level_items.get(position)
            if not item_type:
                continue
            reveals[:] = [entry for entry in reveals
                           if not (entry["level"] == level_name and
                                   entry["position"] == position)]
            reveals.append({"level": level_name, "position": position,
                            "item_type": item_type, "started_ms": now_ms})
            self.sound_mgr.play("chest.wav")

    @staticmethod
    def _chest_reveal_visual(reveal, now_ms: int):
        """Return (rise in tiles, alpha), or None once the reveal expires.

        The item sits still and opaque for its whole life (always (0.0, 255))."""
        age = max(0, now_ms - reveal["started_ms"])
        if age >= _CHEST_REVEAL_DURATION_MS:
            return None
        return 0.0, 255

    def _render_chest_reveals(self, now_ms: Optional[int] = None) -> None:
        """Update and draw short-lived item reveals above opened chests."""
        if now_ms is None:
            now_ms = self.clock.frame_now_ms()
        self._sync_chest_reveals(now_ms)
        reveals = getattr(self, "_chest_reveals", [])
        if not reveals:
            return

        level_name, origin_x, origin_y = self._current_segment_info()
        active = []
        for reveal in reveals:
            visual = self._chest_reveal_visual(reveal, now_ms)
            if visual is None:
                continue
            active.append(reveal)
            if reveal["level"] != level_name:
                continue
            rise, alpha = visual
            cx, cy = reveal["position"]
            # Chests occupy two tiles. Offset by half a tile so the one-tile
            # icon is horizontally centered, starting just above the lid.
            sx, sy = self._world_to_screen(cx + origin_x + 0.5,
                                           cy + origin_y - 1.0 - rise)
            sprite = self._get_item_sprite(reveal["item_type"])
            # Keep the existing one-tile chest reveal footprint; ground items
            # use the native dimensions returned by _get_item_sprite.
            if sprite.get_size() != (TILE_SIZE, TILE_SIZE):
                sprite = pygame.transform.scale(sprite, (TILE_SIZE, TILE_SIZE))
            if alpha < 255:
                sprite = sprite.copy()
                sprite.set_alpha(alpha)
            self.screen.blit(sprite, (int(sx), int(sy)))
        self._chest_reveals = active

    def _get_chest_sprite(self, opened: bool) -> Optional[pygame.Surface]:
        """Build (and cache) the chest sprite from tileset tiles.

        Chests are a client-side overlay (not baked into the level board), so we
        composite the chest graphic from the tileset here, using distinct tiles
        for the open vs closed state.
        """
        cache = self.render_cache.chest_sprite
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
        """Compatibility entry point for focused object-render tests. See
        _render_items above for why this joins the frame instead of opening
        one."""
        frame = self._frame_context()
        frame.screen_size = self.screen.get_size()
        entities = []
        self._collect_chests(entities, frame)
        for entity in entities:
            self._draw_chest_entity(entity, frame)
    def _check_and_render_signs(self):
        """Check if player is near a sign in the current level and show popup."""
        # The A-read dialogue box supersedes the proximity popup: drawing
        # both at once double-displayed the same sign text (live: bomber v6
        # piano sign showed the parchment popup AND the dialogue pager).
        if getattr(self, 'dialogue_text', None) is not None:
            return
        signs = self.client.signs.get(self.client.current_level_name)
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
        px = self.client.player.x + PLAYER_STAND_X - origin_x
        py = self.client.player.y + PLAYER_STAND_Y - origin_y

        for (sx, sy), text in signs.items():
            # Compare against the sign TILE CENTRE (+0.5): flush against a
            # blocking sign the feet sample sits exactly 2.0 tiles from the
            # anchor, so an anchor-based `< 2` misses at the only distance a
            # walking player can actually reach. Tolerance is 2.35, not 2.0:
            # under scripted movement (disabledefmovement — Bomber v6's
            # -Test/Movement) the script steps the player in 0.3-tile quanta
            # and stops SHORT of flush contact (rest position up to 0.29
            # tiles shy), so the feet sample sits at up to ~2.3 — an exact
            # 2.0 radius made popups unreachable there (live-measured 2.2 at
            # the bomblobby piano sign). The next tile row is a full 3.0
            # away, so 2.35 cannot false-positive across a walkway.
            if abs(px - (sx + 0.5)) <= 2.35 and abs(py - (sy + 0.5)) <= 2.35:
                self._render_sign_popup(text)
                break  # Only show one sign at a time
    def _render_sign_popup(self, text: str):
        """Render sign text as popup overlay."""
        if not text:
            return

        # Sign-code escapes (#K(nn)/#k(n)/#u/#i(...)) render as glyphs on
        # the real client — translate, don't leak raw tokens (same
        # normalization as the A-read dialogue box).
        from .dialogue import format_sign_text, layout_dialogue_line, wrap_dialogue
        text = format_sign_text(text)
        if not text:
            return

        # Render sign text in a box at bottom of screen
        font = self.fonts.classic()

        # Sign text is normally pre-wrapped by the wire decoder. Re-measure it
        # with the bundled face and only add wrapping when a decoded line would
        # exceed the available screen width.
        max_text_width = max(1, self.screen_w - 60)
        sprite_mgr = getattr(self, 'sprite_mgr', None)
        measure = lambda line: text.measure(
            line, lambda segment: font.size(segment)[0], sprite_mgr)
        lines = wrap_dialogue(text, measure, max_text_width)
        rows = [layout_dialogue_line(line, font, (0, 0, 0), text, sprite_mgr)
                for line in lines]
        max_width = max((width for _, width, _ in rows), default=0)

        # Create background box
        box_width = min(self.screen_w - 40, max_width + 20)
        box_height = sum(height for _, _, height in rows) + 20
        box_x = (self.screen_w - box_width) // 2
        box_y = self.screen_h - box_height - 60  # Above the UI bar

        # Draw box with border
        pygame.draw.rect(self.screen, (240, 230, 200), (box_x, box_y, box_width, box_height))
        pygame.draw.rect(self.screen, (100, 80, 50), (box_x, box_y, box_width, box_height), 2)

        # Draw text
        y = box_y + 10
        for runs, width, height in rows:
            x = box_x + (box_width - width) // 2
            for surface, advance in runs:
                self.screen.blit(surface, (x, y))
                x += advance
            y += height
