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


def is_hidden(player):
    return (getattr(player, "action_mode", 0) == HIDDEN_ACTION_MODE
            and bool(getattr(player, "carried_object_type", "")))
