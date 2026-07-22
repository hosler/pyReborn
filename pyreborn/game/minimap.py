"""MinimapMixin — Minimap surface construction and palette.

Split from pygame_game.py; methods operate on the GameClient instance."""

from typing import List, Tuple

import pygame


def aspect_fit(source_size, bounds):
    """Largest size fitting in bounds while preserving source aspect ratio."""
    sw, sh = source_size
    bw, bh = bounds
    if sw <= 0 or sh <= 0:
        return 1, 1
    scale = min(bw / sw, bh / sh)
    return max(1, round(sw * scale)), max(1, round(sh * scale))


def map_entity_positions(client):
    """Yield local-player red and visible remote-player white map positions.

    Coordinates are normalized to the whole world on a segmented map and to
    the current 64x64 board otherwise.
    """
    is_world = client.gmap_width > 0 and client.gmap_height > 0
    span_x = client.gmap_width * 64 if is_world else 64
    span_y = client.gmap_height * 64 if is_world else 64
    yield (client.x % span_x) / span_x, (client.y % span_y) / span_y, (255, 0, 0)

    level_to_grid = {name: cell for cell, name in client.gmap_grid.items()}
    current_grid = level_to_grid.get(client._current_level_name)
    for pdata in client.players.values():
        px, py = pdata.get('world_x'), pdata.get('world_y')
        if px is None or py is None:
            px, py = pdata.get('x'), pdata.get('y')
            if px is None or py is None:
                continue
            if is_world:
                grid = level_to_grid.get(pdata.get('level')) or current_grid
                if grid is None:
                    continue
                px += grid[0] * 64
                py += grid[1] * 64
        yield (px % span_x) / span_x, (py % span_y) / span_y, (255, 255, 255)


class MinimapMixin:
    """Mixin providing the above methods for GameClient."""

    def _build_minimap_surface(self):
        """Build minimap surface from data."""
        if not self.minimap_data:
            return
        self._minimap_is_bigmap = False  # real PLO_MINIMAP data wins over a bigmap image

        # Minimap data is typically a 64x64 or 128x128 grid of color indices
        # Each byte represents a tile's color (0-255 palette index)
        data_len = len(self.minimap_data)

        # Determine minimap grid size
        if data_len >= 128 * 128:
            grid_size = 128
        elif data_len >= 64 * 64:
            grid_size = 64
        else:
            grid_size = int(data_len ** 0.5)
            if grid_size * grid_size != data_len:
                return  # Invalid data size

        # Create surface at native resolution
        self.minimap_surface = pygame.Surface((grid_size, grid_size))

        # Simple color palette for minimap
        palette = self._get_minimap_palette()

        # Fill pixels
        for y in range(grid_size):
            for x in range(grid_size):
                idx = y * grid_size + x
                if idx < len(self.minimap_data):
                    color_idx = self.minimap_data[idx]
                    color = palette[color_idx % len(palette)]
                    self.minimap_surface.set_at((x, y), color)

        # Scale to display size
        self._minimap_native_surface = self.minimap_surface
        self.minimap_surface = pygame.transform.scale(self.minimap_surface, self.minimap_size)
    def _ensure_bigmap_surface(self):
        """Tier 4b: fall back to the PLO_BIGMAP world image for the M-key map
        when there's no PLO_MINIMAP grid data (classic gmap worlds that ship a
        single big picture instead of a live per-tile minimap).

        client.py has no on_bigmap callback (PLO_BIGMAP just sets
        client.bigmap_info directly, no event fires - see client.py's
        _handle_packet), so this polls the field once per (level/image)
        change instead of reacting to an event; cheap since it's only called
        while the minimap has nothing else to show.
        """
        info = self.client.bigmap_info
        if not info or not info.get('image'):
            return
        image = info['image']
        if getattr(self, '_bigmap_image_name', None) == image and self.minimap_surface is not None:
            return  # already built for this image
        sheet = self.sprite_mgr.load_sheet(image)
        if sheet is None:
            self._request_asset(image)
            return
        self._bigmap_image_name = image
        self._minimap_is_bigmap = True
        self.bigmap_surface = sheet
        self.minimap_surface = pygame.transform.smoothscale(sheet, self.minimap_size)

    def _get_minimap_palette(self) -> List[Tuple[int, int, int]]:
        """Get color palette for minimap rendering."""
        # Common tile type colors
        palette = [(0, 0, 0)] * 256  # Default black

        # Grass/ground tones
        for i in range(0, 32):
            palette[i] = (34 + i * 2, 139 + i, 34)  # Green tones

        # Water tones
        for i in range(32, 64):
            palette[i] = (30, 100 + i, 200 + min(55, i))  # Blue tones

        # Rock/wall tones
        for i in range(64, 96):
            palette[i] = (100 + i - 64, 100 + i - 64, 100 + i - 64)  # Gray tones

        # Sand tones
        for i in range(96, 128):
            palette[i] = (194, 178, 128 + i - 96)  # Tan tones

        # Building/road tones
        for i in range(128, 160):
            palette[i] = (139 + i - 128, 90 + i - 128, 43)  # Brown tones

        # Special markers
        palette[255] = (255, 0, 0)  # Player position / important markers
        palette[254] = (255, 255, 0)  # NPCs / points of interest
        palette[253] = (0, 255, 255)  # Warps / doors

        return palette
