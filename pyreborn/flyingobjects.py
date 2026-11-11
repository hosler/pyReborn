"""Flying-object rules for script-fired fireblasts and nukes.

Everything here is pure arithmetic over a projectile dict; the game layer
(game/flying.py) owns the world queries and the effects. Source:
Preagonal/FourPlay/quattroplay/src/TServerFlying.cpp (the official client's
TServerFlying::animate and its collision helpers).
"""

from .arrowflight import ARROW_SIZES, arrow_damage, overlaps_player  # noqa: F401

# TServerFlying::animate runs once per 20 Hz game tick and moves the object by
# its speed vector, which putFlyingObject sets to 1.0 tile (TServerLevel.cpp:
# 2486-2512; TServerNPCProperties.cpp:155-163). A tick is therefore 1/20 s.
FLYING_TICK_SECONDS = 0.05

# After a non-player hit the flying object keeps a counter of 3
# (TServerFlying.cpp:256) and animate() decrements it once per tick,
# retiring the object when it reaches -1 (:405-408): four more ticks.
BOUNCE_COUNTER = 3
NOT_BOUNCING = -1

# makeFlyingExplosion (TServerFlying.cpp:85-115): power > 1 raises an
# explosion of radius 2 and type 1 (the half-heart kind).
EXPLOSION_RADIUS = 2
EXPLOSION_TYPE = 1


def center(x: float, y: float, direction: int):
    """The probe point the NPC and wall tests use: the sprite's centre
    (NPC test :246-248, wall test :276-279)."""
    width, height = ARROW_SIZES[direction]
    return x + 0.5 * width, y + 0.5 * height


def explosion_origin(old_x: float, old_y: float, direction: int):
    """Where makeFlyingExplosion centres the blast: the pre-move position's
    sprite centre, less one tile (TServerFlying.cpp:102-103)."""
    cx, cy = center(old_x, old_y, direction)
    return cx - 1.0, cy - 1.0


def explodes(power: int) -> bool:
    """Only power above 1 leaves an explosion (TServerFlying.cpp:100)."""
    return power > 1


def hits_walls(power: int) -> bool:
    """handleFlyingWallCollision returns at once for power <= 1
    (TServerFlying.cpp:273)."""
    return power > 1
