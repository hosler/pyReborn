"""Shared constants and helpers for the pygame game client."""

import re
from pathlib import Path

# The pyreborn/ package directory. Anchored here (not via __file__ in the
# mixin modules) so asset/path resolution is independent of which game/*.py
# file a method was split into.
PACKAGE_DIR = Path(__file__).parent.parent

TILE_CORRECTIONS_FILE = PACKAGE_DIR / "tile_corrections.json"

TILE_SIZE = 16
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480
TILESET_COLS = 128
TILESET_ROWS = 32
MOVE_STEP = 0.25  # Tiles moved per step; matches Client.move()'s default step


def parse_npc_visual_effects(script: str, image_name: str = '') -> dict:
    """Parse NPC script and image for visual effects like drawaslight and setcoloreffect.

    Note: For client version 6.037+, the server doesn't send GS1 scripts.
    We fall back to image-based detection for light NPCs.

    Returns dict with:
        - drawaslight: bool - render with additive blending
        - coloreffect: tuple (r, g, b, a) - color multiplier
    """
    effects = {
        'drawaslight': False,
        'coloreffect': None,
    }

    # Image-based light detection (for modern clients that don't receive scripts)
    # Light NPCs typically use images like "light2.png", "light.png", "lightblue.png"
    if image_name:
        img_lower = image_name.lower()
        if img_lower.startswith('light') and img_lower.endswith('.png'):
            effects['drawaslight'] = True
            # Default light color effect (semi-transparent for glow)
            effects['coloreffect'] = (1.0, 1.0, 1.0, 0.99)

    # If we have a script, parse it (for older client versions)
    if script:
        # Check for CLIENTSIDE section (the rendering effects are client-side)
        clientside_match = re.search(r'//#CLIENTSIDE(.*)$', script, re.DOTALL | re.IGNORECASE)
        clientside_code = clientside_match.group(1) if clientside_match else script

        # Check for playerenters block
        playerenters_match = re.search(r'if\s*\(\s*playerenters\s*\)\s*\{([^}]*)\}', clientside_code, re.DOTALL)
        if playerenters_match:
            block = playerenters_match.group(1)

            # Check for drawaslight
            if re.search(r'\bdrawaslight\s*;', block, re.IGNORECASE):
                effects['drawaslight'] = True

            # Check for setcoloreffect r,g,b,a
            color_match = re.search(
                r'setcoloreffect\s+([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)',
                block, re.IGNORECASE
            )
            if color_match:
                r, g, b, a = float(color_match.group(1)), float(color_match.group(2)), \
                             float(color_match.group(3)), float(color_match.group(4))
                effects['coloreffect'] = (r, g, b, a)

    return effects

