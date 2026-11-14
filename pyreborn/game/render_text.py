"""Entity text rendering mixin."""

from __future__ import annotations

from typing import List, Tuple

import pygame

from .assets import render_outlined_text
from .host import GameHost


class RenderTextMixin(GameHost):
    def _render_text_cached(self, font: pygame.font.Font, text: str,
                             color: Tuple[int, int, int]) -> pygame.Surface:
        """Render (and cache) a plain (unoutlined) text surface. Speech
        bubbles re-render the same handful of strings every frame otherwise;
        keying on (font identity, text, color) lets every caller share one
        cache. Cleared wholesale once it grows large so a chat-heavy session
        doesn't leak memory. Fine as-is for bubble text, which already sits on
        a solid white plate -- text drawn straight over the level (nameplates,
        showtext) wants `_render_text_outlined_cached` instead, below."""
        cache = self.render_cache.text_surf
        key = (id(font), text, color)
        surf = cache.get(key)
        if surf is None:
            surf = cache[key] = font.render(text, True, color)
        return surf

    def _render_text_outlined_cached(self, font: pygame.font.Font, text: str,
                                      color: Tuple[int, int, int],
                                      outline_color: Tuple[int, int, int] = (0, 0, 0)
                                      ) -> pygame.Surface:
        """Outlined sibling of `_render_text_cached`, for text drawn straight
        over the level (nameplates, NPC showtext) rather than inside a
        solid-colour bubble/box -- a flat fill (even with a 1px drop shadow)
        all but vanishes against busy/dark level art. See
        assets.render_outlined_text for the actual stamping."""
        cache = self.render_cache.text_outline
        key = (id(font), text, color, outline_color)
        surf = cache.get(key)
        if surf is None:
            surf = cache[key] = render_outlined_text(font, text, color, outline_color)
        return surf

    def _wrapped_lines(self, text: str) -> List[str]:
        """Word-wrap speech-bubble text into up to 3 lines under ~120px.
        Recomputing this (with a font.render() per word) every frame for the
        same message is wasteful, so cache the wrap result keyed by the full
        text - messages are static once received."""
        cache = self.render_cache.wrap
        lines = cache.get(text)
        if lines is not None:
            return lines

        max_width = 120
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_surf = self._render_text_cached(self.font_small, test_line, (0, 0, 0))
            if test_surf.get_width() > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)
        lines = lines[:3]  # Limit to 3 lines max

        cache[text] = lines
        return lines

    def _render_speech_bubble(self, x: float, y: float, text: str):
        """Render a speech bubble above an entity."""
        if not text:
            return

        lines = self._wrapped_lines(text)
        if not lines:
            # Whitespace-only text wraps to no words; nothing to show. Without
            # this guard the max() below crashes the whole render loop, which a
            # remote player sending an all-space chat could trigger for everyone.
            return

        # Calculate bubble dimensions
        line_height = 14
        padding = 4
        bubble_height = len(lines) * line_height + padding * 2
        bubble_width = max(self._render_text_cached(self.font_small, line, (0, 0, 0)).get_width()
                           for line in lines) + padding * 2

        # Position bubble above entity (centered, above head)
        bubble_x = x + 16 - bubble_width // 2
        bubble_y = y - bubble_height - 8

        # Draw bubble background (white with black border)
        pygame.draw.rect(self.screen, (255, 255, 255),
                        (bubble_x, bubble_y, bubble_width, bubble_height))
        pygame.draw.rect(self.screen, (0, 0, 0),
                        (bubble_x, bubble_y, bubble_width, bubble_height), 1)

        # Draw small triangle pointer
        pointer_x = x + 16
        pygame.draw.polygon(self.screen, (255, 255, 255), [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x + 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6)
        ])
        pygame.draw.lines(self.screen, (0, 0, 0), False, [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6),
            (pointer_x + 4, bubble_y + bubble_height)
        ], 1)

        # Draw text lines
        for i, line in enumerate(lines):
            text_surf = self._render_text_cached(self.font_small, line, (0, 0, 0))
            text_x = bubble_x + padding
            text_y = bubble_y + padding + i * line_height
            self.screen.blit(text_surf, (text_x, text_y))
