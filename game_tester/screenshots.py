"""
ScreenshotCapture - Capture game state as images for reports.

Renders level tiles, player positions, and entities to images.
Uses PIL/Pillow if available, falls back to ASCII art.
"""

import io
from typing import Optional, Dict, List, Tuple, Any

# Try to import PIL for image generation
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Color palette for tiles (simplified)
TILE_COLORS = {
    # Grass tiles (0-15)
    range(0, 16): (34, 139, 34),  # Forest green
    # Water tiles (512-527)
    range(512, 528): (30, 144, 255),  # Dodger blue
    # Sand tiles (256-271)
    range(256, 272): (238, 214, 175),  # Sandy
    # Stone/rock (768-783)
    range(768, 784): (128, 128, 128),  # Gray
    # Default
    None: (100, 100, 100),  # Dark gray
}


def get_tile_color(tile_id: int) -> Tuple[int, int, int]:
    """Get color for a tile ID."""
    for tile_range, color in TILE_COLORS.items():
        if tile_range is None:
            continue
        if tile_id in tile_range:
            return color
    return TILE_COLORS[None]


class ScreenshotCapture:
    """
    Capture game state as images for reports.

    Usage:
        capture = ScreenshotCapture()
        png_bytes = capture.capture_level(client)
        minimap = capture.capture_minimap(client)
    """

    # Tile size in pixels for rendering
    TILE_SIZE = 8
    MINIMAP_TILE_SIZE = 2

    def __init__(self):
        self.has_pil = HAS_PIL

    def capture_level(self, client, scale: int = 8) -> Optional[bytes]:
        """
        Render current level to PNG image.

        Args:
            client: pyReborn Client instance
            scale: Pixels per tile (default 8)

        Returns:
            PNG image as bytes, or None if PIL not available
        """
        if not self.has_pil:
            return None

        if not client.tiles or len(client.tiles) < 64 * 64:
            return None

        # Create image
        width = 64 * scale
        height = 64 * scale
        img = Image.new('RGB', (width, height), (50, 50, 50))
        draw = ImageDraw.Draw(img)

        # Draw tiles
        for y in range(64):
            for x in range(64):
                tile_idx = y * 64 + x
                tile_id = client.tiles[tile_idx] if tile_idx < len(client.tiles) else 0
                color = get_tile_color(tile_id)

                x1, y1 = x * scale, y * scale
                x2, y2 = x1 + scale - 1, y1 + scale - 1
                draw.rectangle([x1, y1, x2, y2], fill=color)

        # Draw player position (red dot)
        px = int(client.x * scale)
        py = int(client.y * scale)
        radius = max(2, scale // 2)
        draw.ellipse([px - radius, py - radius, px + radius, py + radius],
                    fill=(255, 0, 0), outline=(255, 255, 255))

        # Draw other players (blue dots)
        for player_id, player in client.players.items():
            x = player.get('x', 0)
            y = player.get('y', 0)
            if 0 <= x <= 64 and 0 <= y <= 64:
                px = int(x * scale)
                py = int(y * scale)
                draw.ellipse([px - radius, py - radius, px + radius, py + radius],
                            fill=(0, 100, 255), outline=(255, 255, 255))

        # Draw NPCs (green dots)
        for npc_id, npc in client.npcs.items():
            x = npc.get('x', 0)
            y = npc.get('y', 0)
            if 0 <= x <= 64 and 0 <= y <= 64:
                px = int(x * scale)
                py = int(y * scale)
                draw.ellipse([px - radius, py - radius, px + radius, py + radius],
                            fill=(0, 255, 0), outline=(255, 255, 255))

        # Draw items (yellow dots)
        for (x, y), item_type in client.items.items():
            if 0 <= x <= 64 and 0 <= y <= 64:
                px = int(x * scale)
                py = int(y * scale)
                draw.rectangle([px - 2, py - 2, px + 2, py + 2],
                              fill=(255, 255, 0), outline=(200, 200, 0))

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def capture_minimap(self, client, scale: int = 2) -> Optional[bytes]:
        """
        Create a small overview minimap.

        Args:
            client: pyReborn Client instance
            scale: Pixels per tile (default 2)

        Returns:
            PNG image as bytes, or None if PIL not available
        """
        return self.capture_level(client, scale=scale)

    def capture_coverage_map(self, visited_tiles: set, player_x: float = 0,
                             player_y: float = 0, scale: int = 4) -> Optional[bytes]:
        """
        Render coverage map showing visited vs unvisited tiles.

        Args:
            visited_tiles: Set of (x, y) tuples
            player_x, player_y: Current player position
            scale: Pixels per tile

        Returns:
            PNG image as bytes, or None if PIL not available
        """
        if not self.has_pil:
            return None

        width = 64 * scale
        height = 64 * scale
        img = Image.new('RGB', (width, height), (40, 40, 40))
        draw = ImageDraw.Draw(img)

        # Draw visited tiles (green) and unvisited (dark)
        for y in range(64):
            for x in range(64):
                x1, y1 = x * scale, y * scale
                x2, y2 = x1 + scale - 1, y1 + scale - 1

                if (x, y) in visited_tiles:
                    draw.rectangle([x1, y1, x2, y2], fill=(0, 128, 0))  # Green
                else:
                    draw.rectangle([x1, y1, x2, y2], fill=(30, 30, 30))  # Dark

        # Draw current position
        if 0 <= player_x <= 64 and 0 <= player_y <= 64:
            px = int(player_x * scale)
            py = int(player_y * scale)
            radius = max(2, scale)
            draw.ellipse([px - radius, py - radius, px + radius, py + radius],
                        fill=(255, 0, 0), outline=(255, 255, 255))

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def capture_state_diagram(self, client, title: str = "Game State") -> Optional[bytes]:
        """
        Create a state diagram showing entity counts and positions.

        Args:
            client: pyReborn Client instance
            title: Title for the diagram

        Returns:
            PNG image as bytes, or None if PIL not available
        """
        if not self.has_pil:
            return None

        width = 400
        height = 300
        img = Image.new('RGB', (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Try to load a font, fall back to default
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        except (OSError, IOError):
            font = ImageFont.load_default()
            title_font = font

        # Draw title
        draw.text((10, 10), title, fill=(0, 0, 0), font=title_font)

        # Draw state info
        y = 50
        info_lines = [
            f"Level: {client._current_level_name or 'Unknown'}",
            f"Position: ({client.x:.1f}, {client.y:.1f})",
            f"Players: {len(client.players)}",
            f"NPCs: {len(client.npcs)}",
            f"Items: {len(client.items)}",
            f"Tiles: {len(client.tiles) if client.tiles else 0}",
        ]

        for line in info_lines:
            draw.text((20, y), line, fill=(0, 0, 0), font=font)
            y += 25

        # Draw mini level preview in corner
        if client.tiles and len(client.tiles) >= 64 * 64:
            preview_size = 128
            preview_x = width - preview_size - 10
            preview_y = 50

            # Draw border
            draw.rectangle([preview_x - 2, preview_y - 2,
                           preview_x + preview_size + 2, preview_y + preview_size + 2],
                          outline=(0, 0, 0))

            # Draw tiles (simplified)
            for ty in range(32):
                for tx in range(32):
                    tile_idx = (ty * 2) * 64 + (tx * 2)
                    tile_id = client.tiles[tile_idx] if tile_idx < len(client.tiles) else 0
                    color = get_tile_color(tile_id)

                    px = preview_x + tx * 4
                    py = preview_y + ty * 4
                    draw.rectangle([px, py, px + 3, py + 3], fill=color)

            # Draw player dot
            px = preview_x + int(client.x * 2)
            py = preview_y + int(client.y * 2)
            draw.ellipse([px - 3, py - 3, px + 3, py + 3],
                        fill=(255, 0, 0), outline=(255, 255, 255))

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def get_ascii_level(self, client, width: int = 64, height: int = 32) -> str:
        """
        Generate ASCII representation of level.

        Args:
            client: pyReborn Client instance
            width: Output width in characters
            height: Output height in characters

        Returns:
            ASCII string representation
        """
        if not client.tiles or len(client.tiles) < 64 * 64:
            return "No level data available"

        # Scale factors
        scale_x = 64 / width
        scale_y = 64 / height

        lines = []
        for y in range(height):
            line = ""
            for x in range(width):
                # Get tile at scaled position
                tx = int(x * scale_x)
                ty = int(y * scale_y)
                tile_idx = ty * 64 + tx

                tile_id = client.tiles[tile_idx] if tile_idx < len(client.tiles) else 0

                # Check if player is here
                px = int(client.x / scale_x)
                py = int(client.y / scale_y)
                if x == px and y == py:
                    line += "@"  # Player
                elif tile_id < 16:
                    line += "."  # Grass
                elif 512 <= tile_id < 528:
                    line += "~"  # Water
                elif 256 <= tile_id < 272:
                    line += ","  # Sand
                elif 768 <= tile_id < 784:
                    line += "#"  # Stone
                else:
                    line += " "  # Unknown/empty

            lines.append(line)

        return "\n".join(lines)

    def save_level_png(self, client, filename: str, scale: int = 8) -> bool:
        """
        Save level screenshot to file.

        Args:
            client: pyReborn Client instance
            filename: Output filename
            scale: Pixels per tile

        Returns:
            True if saved successfully
        """
        data = self.capture_level(client, scale)
        if data:
            with open(filename, 'wb') as f:
                f.write(data)
            return True
        return False
