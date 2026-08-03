"""Shared constants and helpers for the pygame game client."""

import re
from pathlib import Path

# The pyreborn/ package directory. Anchored here (not via __file__ in the
# mixin modules) so asset/path resolution is independent of which game/*.py
# file a method was split into.
PACKAGE_DIR = Path(__file__).parent.parent


TILE_SIZE = 16
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480
MOVE_STEP = 0.25  # Tiles moved per step; matches Client.move()'s default step

# Classic-engine movement feel (collision.py's corner-assist, actions.py's
# push/grab/pull hold state — see their docstrings).
CORNER_ASSIST_MAX = 0.5  # tiles - max perpendicular nudge near a doorway/corner
PUSH_HOLD_TIME = 0.5     # seconds a blocked direction must be held before "push"

# Player collision geometry relative to the 3x3 sprite's top-left anchor.
PLAYER_COLLISION_LEFT = 0.5
PLAYER_COLLISION_RIGHT = 2.5
PLAYER_COLLISION_TOP = 1.0
PLAYER_COLLISION_BOTTOM = 3.0
PLAYER_BODY_CENTER_X = (PLAYER_COLLISION_LEFT + PLAYER_COLLISION_RIGHT) / 2
PLAYER_BODY_CENTER_Y = (PLAYER_COLLISION_TOP + PLAYER_COLLISION_BOTTOM) / 2
PLAYER_STAND_X = 1.5
PLAYER_STAND_Y = 2.5

# Ground sampling ("what am I standing on") uses ONE point, and the official
# client puts it at (x+1.5, y+2.0) - the collision box's centre, half a tile
# ABOVE PLAYER_STAND_Y. Every ground test in the decompiled client shares the
# pair DOUBLE_00402400 / DOUBLE_00402408 (= 1.5 / 2.0,
# Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1277-1278):
#   TPlayer.cpp:5925-5927   testSittingSleeping - the chair test
#   TPlayer.cpp:5997-5999   testForWater
#   TPlayer.cpp:5897-5899   the lava/damage-tile test
#   TServerPlayer.cpp:614-615   footstep sound position
#   TServerPlayer.cpp:1252-1253 SwampIndex
# Live server content agrees: across the Bomber/LTTP/GTA GS1 corpora the
# player's reference point is written `playerx+1.5` / `playery+2` (165/171
# occurrences of those two offsets), never `playery+2.5`.
# PLAYER_STAND_Y (2.5) came from a community description of the standing point
# and is half a tile too low for ground sampling: it shifted the chair-sit
# region half a tile up the screen, so live Bomber furniture only seated you
# on the upper part of the chair.
PLAYER_GROUND_X = 1.5
PLAYER_GROUND_Y = 2.0

# Scrollback cap for chat_messages (game/hud.py's PageUp/PageDown scrollback,
# game/input.py's chat/PM append sites, game/setup.py's server/roster/PM
# append sites). Was 10 (no scrollback existed); raised so PageUp actually has
# history to page through.
CHAT_HISTORY_CAP = 200

# GS1's keydown2(keycode, edge) builtin reports keys using the Windows
# Virtual-Key (VK) code table the real Reborn client runs on (confirmed via the
# decompiled C# client, TInput.cpp: A-Z at VK 0x41-0x5A, 0-9 at VK
# 0x30-0x39, arrows at 0x25-0x28, Enter=13, Backspace=8, ...) - NOT raw pygame
# keycodes. Bomber Arena's arenaGUI weapon calls keydown2(82,...) for its bomb
# cursor (82 = 0x52 = VK_R = the R key); other scripts use 13 (Enter), 8
# (Backspace), 38 (Up arrow). Without translating, keys_raw held pygame's own
# keycodes (e.g. pygame.K_r == 114, the ASCII lowercase code) so keydown2(82)
# could never match and R-bound script logic silently never fired.
def pygame_key_to_vk(pg_key: int) -> int:
    """Translate a pygame key constant to the Reborn-script VK-style code."""
    import pygame
    if pygame.K_a <= pg_key <= pygame.K_z:      # a-z (lowercase ASCII 97-122)
        return pg_key - 32                       # -> VK_A..VK_Z (65-90)
    if pygame.K_0 <= pg_key <= pygame.K_9:      # already VK_0..VK_9 (48-57)
        return pg_key
    _SPECIAL = {
        pygame.K_BACKSPACE: 0x08, pygame.K_TAB: 0x09, pygame.K_RETURN: 0x0D,
        pygame.K_ESCAPE: 0x1B, pygame.K_SPACE: 0x20,
        pygame.K_LEFT: 0x25, pygame.K_UP: 0x26, pygame.K_RIGHT: 0x27, pygame.K_DOWN: 0x28,
        pygame.K_LSHIFT: 0xA0, pygame.K_RSHIFT: 0xA1,
        pygame.K_LCTRL: 0xA2, pygame.K_RCTRL: 0xA3,
        pygame.K_LALT: 0xA4, pygame.K_RALT: 0xA5,
    }
    return _SPECIAL.get(pg_key, pg_key)


def parse_npc_visual_effects(script: str, image_name: str = '') -> dict:
    """Parse NPC script and image for visual effects like drawaslight and setcoloreffect.

    Note: For client version 6.037+, the server doesn't send GS1 scripts.
    We fall back to image-based detection for light NPCs.

    Returns dict with:
        - drawaslight: bool - render with additive blending
        - coloreffect: tuple (r, g, b, a) - color multiplier
        - zoom: float or None - setzoomeffect scale on the NPC image
    """
    effects = {
        'drawaslight': False,
        'coloreffect': None,
        'zoom': None,
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

            # seteffectmode 2 = additive image effect (the bomber's lamp-bulb
            # NPCs: setimgpart light2.png,... + seteffectmode 2 +
            # setcoloreffect — the truncated glow crop must ADD, or it blits
            # as an opaque near-black rectangle over the scene).
            mode_match = re.search(r'\bseteffectmode\s+(\d+)', block, re.IGNORECASE)
            if mode_match and int(mode_match.group(1)) == 2:
                effects['drawaslight'] = True

            # setzoomeffect Z — scale the NPC's image by Z when drawing.
            zoom_match = re.search(r'\bsetzoomeffect\s+([\d.]+)', block, re.IGNORECASE)
            if zoom_match:
                try:
                    effects['zoom'] = float(zoom_match.group(1))
                except ValueError:
                    pass

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
