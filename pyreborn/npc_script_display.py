"""Script-driven NPC overlays: the timershow countdown and the `take` pickup.

Both are drawn by the reference client from state the GS1 commands leave on
the NPC (TServerNPC::draw, Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:
1880-1913). Kept pure so the rules test without a display.
"""

import math

from .clock import sim_passed


def timer_text(npc):
    """The countdown string for an NPC with `timershow` active, else None.

    The reference shows floor(timeout + 0.0001) (TServerNPC.cpp:1910-1913), so
    an NPC whose timeout is not pending shows nothing."""
    if not npc.get('timershow'):
        return None
    remaining = npc.get('_timeout')
    if remaining is None:
        return None
    return str(int(math.floor(float(remaining) + 0.0001)))


def take_display(npc, now):
    """(giveitems sprite index, value text or None) while an NPC that has just
    `take`n an item shows it, else None.

    The icon stays 20 ticks (1.0 s). Items 0-5 (rupees, arrows, bombs, heart)
    also show the new total; a value under 0.0001 shows "0"
    (TServerNPC.cpp:1884-1900)."""
    until = npc.get('take_until')
    if until is None:
        return None
    if sim_passed(now, until):
        return None
    index = int(npc.get('take_item', 0))
    from .ground_items import GIVE_SPRITES
    sprite = GIVE_SPRITES[index]
    value = None
    if index <= 5 and 'take_value' in npc:
        number = float(npc['take_value'])
        value = "0" if abs(number) < 0.0001 else ("%g" % number)
    return sprite, value
