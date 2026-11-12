"""Classic player-colour palette (PLPROP_COLORS indices) and body recolour markers.

Pygame-free so the GS1 engine can use it; sprites.py re-exports these names.
"""

from typing import Dict, Tuple


# -- Tier 2a: player body-color recoloring (palette swap) -------------------
#
# Classic Reborn's PLPROP_COLORS carries 5 indices into a 20-color named
# palette (see the C# client's Players/ColorManager.cs AllColors)
# that get painted onto 5 marker colors baked into body*.png. packets.py
# parses PLPROP_COLORS (prop 13, fixed-width: 5 bytes classic / 8 bytes v6
# extended body colors) into Player.colors and the other-player props dict;
# this recolor path activates automatically the moment a `colors` sequence
# (>=5 ints, 0-19 for the classic palette) shows up in the equipment dict
# passed to _render_animated_entity (game/render_entities.py), and is a no-op
# (draws the sprite unmodified) when colors is absent/short.
#
# Marker colors below were read directly off body.png/body2.png/body5.png/
# body12.png with PIL (the C# client ships no reference table): all four share
# the exact same 5 non-outline, non-transparent RGB values, just in different
# pixel proportions per clothing cut, confirming they are the 5 recolor
# markers. The marker -> named-slot assignment (skin/coat/sleeves/shoes/belt,
# matching PLPROP_COLORS' index order) is this module's best-effort guess -
# it has NOT been verified against a live server's rendering of a known
# COLORS value (attempted: memory records one real capture, body12.png with
# COLORS 2,0,10,4,18, but no reference screenshot to check the result
# against). If it turns out wrong once colors actually flow, only
# BODY_COLOR_MARKERS' ordering needs correcting.
REBORN_PALETTE = [
    "white", "yellow", "orange", "pink", "red", "darkred", "lightgreen",
    "green", "darkgreen", "lightblue", "blue", "darkblue", "brown",
    "cynober", "purple", "darkpurple", "lightgray", "gray", "black",
    "transparent",
]

REBORN_PALETTE_RGB: Dict[str, Tuple[int, int, int]] = {
    "white": (255, 255, 255), "yellow": (255, 255, 0), "orange": (255, 140, 0),
    "pink": (255, 175, 175), "red": (220, 30, 30), "darkred": (139, 0, 0),
    "lightgreen": (140, 255, 140), "green": (0, 180, 0), "darkgreen": (0, 100, 0),
    "lightblue": (140, 190, 255), "blue": (30, 60, 220), "darkblue": (0, 0, 139),
    "brown": (139, 90, 43), "cynober": (227, 66, 52), "purple": (160, 32, 240),
    "darkpurple": (100, 20, 150), "lightgray": (200, 200, 200), "gray": (128, 128, 128),
    "black": (20, 20, 20), "transparent": (0, 0, 0),
    "darkgray": (64, 64, 64), "cyan": (0, 255, 255),
}

REBORN_PALETTE_ALIASES = {
    "cyan": "cynober",
    "darkgray": "gray",
}

# Marker RGB baked into body*.png, in (skin, coat, sleeves, shoes, belt) slot
# order matching PLPROP_COLORS' 5 indices.
BODY_COLOR_MARKERS: Tuple[Tuple[int, int, int], ...] = (
    (255, 173, 107),  # skin
    (255, 255, 255),  # coat (main clothing)
    (255, 0, 0),       # sleeves
    (206, 24, 41),     # shoes
    (0, 0, 255),       # belt
)


def palette_index_to_rgb(index) -> Tuple[int, int, int]:
    """Resolve a PLPROP_COLORS palette index (0-19) to an RGB triple."""
    try:
        name = REBORN_PALETTE[int(index)]
    except (IndexError, ValueError, TypeError):
        return (255, 255, 255)
    return REBORN_PALETTE_RGB.get(name, (255, 255, 255))


def palette_name_to_index(name) -> int:
    """Resolve a classic color name while preserving the fixed wire palette."""
    normalized = str(name).strip().lower()
    normalized = REBORN_PALETTE_ALIASES.get(normalized, normalized)
    try:
        return REBORN_PALETTE.index(normalized)
    except ValueError:
        return 0
