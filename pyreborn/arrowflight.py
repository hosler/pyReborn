"""Flying-object geometry, TServerFlying.cpp:135-205, :367-423."""

from .classic_sprites import sprite_rect

# TServerFlying.cpp:23,366-367: spritespos[107:111], pixels divided by 16.
ARROW_SIZES = tuple(tuple(size / 16.0 for size in sprite_rect(index)[2:])
                    for index in range(107, 111))


def overlaps_player(x, y, direction, px, py):
    w, h = ARROW_SIZES[direction]
    return (x + w > px + 0.5 and px + 2.5 > x
            and y + h > py + 1.0 and py + 3.0 > y)


def shield_blocks(player, direction, power):
    # A stronger shield does not block power >1. Facing is opposite motion.
    return (player.animation in ('idle', 'walk') and player.shield_power > 0
            and power <= 1 and player.direction == (direction + 2) % 4)


def arrow_damage(power):
    # TServerFlying.cpp:222: powers 1 and 3 deal one heart; others half.
    return 1.0 if power in (1, 3) else 0.5
