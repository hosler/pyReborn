"""Hiding under a carried bush or stone (TPlayer actionMode 14)."""

from .liftobjects import LIFT_NAMES, LIFT_SPRITES

HIDDEN_ACTION_MODE = 14  # TPlayer.cpp:2131 setActionMode(14).
HIDDEN_STILL_ANI = "hiddenstill"  # defanis[12], TInitStatics.cpp:1472.
HIDDEN_MOVE_ANI = "hidden"  # defanis[14], TInitStatics.cpp:1474.
# TInitStatics.cpp:1143: hidablesprites = bush, stone, blackstone, matched
# against the carry sprite (liftobjects.LIFT_SPRITES).
HIDABLE_SPRITES = (0x105, 0x107, 0x0ef)
HIDABLE_OBJECTS = tuple(name for name, sprite in zip(LIFT_NAMES, LIFT_SPRITES)
                        if sprite in HIDABLE_SPRITES)
# TPlayer.cpp:7447 sets speed = <literal> in mode 14 instead of the 0.5
# tiles/tick (10 tiles/s) walk speed. The decompiled C++ prints 2.0, but the
# asm loads it from rodata 0x402660 (movementAction+0x1b7), which no source
# names; 2.0 would be 4x faster than walking, so the audit's 0.1 tiles/tick
# (2 tiles/s) is used. Unverified against the binary.
HIDDEN_SPEED = 2.0  # tiles per second


def can_hide(carried_object_type):
    return carried_object_type in HIDABLE_OBJECTS


def unhide_leap(carried_object_type, x, y):
    # TPlayer.cpp:6415-6422: only the carried bush sprite throws leaves.
    sprite = dict(zip(LIFT_NAMES, LIFT_SPRITES)).get(carried_object_type)
    if sprite != HIDABLE_SPRITES[0]:
        return None
    # TPlayer.cpp:6421 reads x + 5.0; a burst five tiles to the right of a
    # two-tile-wide sprite is a decompiler artifact. Use x + 0.5, as in the
    # companion water burst (TPlayer.cpp:6039; TInitStatics.cpp:1253).
    return 0, x + 0.5, y + 0.3125  # TPlayer.cpp:6420-6422


def is_hidden(player):
    return (getattr(player, "action_mode", 0) == HIDDEN_ACTION_MODE
            and bool(getattr(player, "carried_object_type", "")))
