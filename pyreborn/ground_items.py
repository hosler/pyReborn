"""Classic ground-item rules, ported from the decompiled official client.

Pure data and functions (no pygame) so the pickup, presentation and
giveaway rules are unit-testable. Citations are in the read-only oracle
Preagonal/FourPlay/quattroplay/src/:

* TServerLevel.cpp  putExtra (1341) / animateExtras (1400): lifetime and
  walk-over collection
* TServerExtra.cpp  draw (33): bob and blink
* TPlayer.cpp       itemAvailable (6690), loseItem (6898), nextGiveItem
                    (6612), addNPCWeapon (1231), key chords (2272-2297)
* TInitStatics.cpp  itemsgiveaway / giveorder / giveitems / itemnames
                    (1183-1218)
"""

import math
from typing import Callable, Dict, Optional, Sequence, Tuple

# One oracle tick is one 20 Hz client frame (the same 0.05 s the rest of
# pyReborn uses for classic frame timing).
TICK = 0.05

# putExtra(..., 0xa4, ...): every dropped item starts at 164 ticks and
# animateExtras decrements it once per tick, deleting it below zero.
ITEM_LIFETIME_TICKS = 164
# TServerExtra::draw skips odd tick values once `time <= 0x24`.
BLINK_TICKS = 36
# animateExtras only collects while `time < 0xa0`: the first four ticks of a
# fresh drop are a grace period.
PICKUP_MIN_AGE_TIME = 160
# |player.x + 1.5 - (item.x + 1.0)| < 2.0 and |player.y + 2.0 - (item.y + 1.0)|
# < 2.0 (FLOAT_004022b8 = 2.0; DOUBLE_00402400 = 1.5, DOUBLE_00402408 = 2.0,
# DOUBLE_004023d8 = 1.0). Strict inequality. NOT the 1.25 an earlier audit read.
PICKUP_RADIUS = 2.0
PLAYER_CENTER_X, PLAYER_CENTER_Y = 1.5, 2.0
ITEM_CENTER = 1.0
# Falloff of the landing bounce: (time / 164) ** 16 once time >= 142.00885.
BOB_FALLOFF_START = 142.00885142487144
BOB_HEIGHT_TILES = 3.0

# itemsgiveaway: only these types are reported with PLI_ITEMTAKE; the others
# are removed locally without telling the server.
ITEMS_GIVEAWAY = frozenset({0, 1, 2, 3, 4, 5, 7, 8, 15, 19})

# giveorder: the S+A cycle order.
GIVE_ORDER = (0, 1, 2, 19, 3, 4, 5, 6, 16, 8, 12, 23, 7, 20, 21, 22,
              9, 15, 17, 10, 13, 18, 14, 24)

# Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1197-1201 (giveitems).
GIVE_SPRITES = (136, 137, 138, 67, 143, 139, 145, 351, 65, 350,
                314, 315, 321, 323, 322, 324, 325, 328, 329, 330,
                331, 332, 333, 334, 349)

# TGUIScriptLoader::getDefaultItemScript has a script only for these item
# indices, so only they grant a built-in weapon (addNPCWeapon): the weapon
# is the item name with its first letter upper-cased. The server owns the
# weapon list, so the client does not grant on pickup.
ITEM_NAMES = (
    "greenrupee", "bluerupee", "redrupee", "bombs", "darts",
    "heart", "glove1", "bow", "bomb", "shield",
    "sword", "fullheart", "superbomb", "battleaxe", "goldensword",
    "mirrorshield", "glove2", "lizardshield", "lizardsword", "goldrupee",
    "fireball", "fireblast", "nukeshot", "joltbomb", "spinattack",
)
WEAPON_GRANT_ITEMS = (7, 8, 12, 20, 21, 22, 23)
WEAPON_GRANTS: Dict[int, str] = {
    i: ITEM_NAMES[i][0].upper() + ITEM_NAMES[i][1:] for i in WEAPON_GRANT_ITEMS}

# layd: drop offset per facing (0 up, 1 left, 2 down, 3 right).
LAY_OFFSETS = ((0.0, -3.0), (-2.0, 0.0), (0.0, 2.0), (2.0, 0.0))
LAY_BASE = (0.5, 1.0)


def item_time(age: float) -> int:
    """Oracle `m_time` for an item first seen `age` seconds ago."""
    return ITEM_LIFETIME_TICKS - int(max(0.0, age) / TICK)


def item_expired(age: float) -> bool:
    return item_time(age) < 0


def item_blink_hidden(age: float) -> bool:
    """True on the ticks the oracle skips drawing (time <= 36 and odd)."""
    t = item_time(age)
    return 0 <= t <= BLINK_TICKS and (t & 1) == 1


def item_bob_tiles(age: float) -> float:
    """Height above the ground in tiles: |sin(t/3)| * (t/164)**16 * 3."""
    t = float(item_time(age))
    if t < BOB_FALLOFF_START:
        return 0.0
    falloff = (t / ITEM_LIFETIME_TICKS) ** 16
    return abs(math.sin(t / 3.0)) * falloff * BOB_HEIGHT_TILES


def within_pickup_range(player_x: float, player_y: float,
                        item_x: float, item_y: float) -> bool:
    """Level-local player/item positions, tiles."""
    return (abs(player_x + PLAYER_CENTER_X - (item_x + ITEM_CENTER)) < PICKUP_RADIUS
            and abs(player_y + PLAYER_CENTER_Y - (item_y + ITEM_CENTER)) < PICKUP_RADIUS)


def pickup_ready(age: float) -> bool:
    """animateExtras collects only while 0 <= time < 160."""
    t = item_time(age)
    return 0 <= t < PICKUP_MIN_AGE_TIME


def item_index(item_type) -> Optional[int]:
    """Index of an item type name in the classic item table, else None."""
    try:
        return ITEM_NAMES.index(str(item_type).lower())
    except ValueError:
        return None


def walkover_takes(player_x: float, player_y: float,
                   items: Dict[Tuple[float, float], str],
                   ages: Dict[Tuple[float, float], float]):
    """Item keys a walk-over should send PLI_ITEMTAKE for, in dict order."""
    out = []
    for key, item_type in items.items():
        idx = item_index(item_type)
        if idx is None or idx not in ITEMS_GIVEAWAY:
            continue
        age = ages.get(key, 0.0)
        if pickup_ready(age) and within_pickup_range(
                player_x, player_y, key[0], key[1]):
            out.append(key)
    return out


# --- S+A giveaway (actionMode 9) --------------------------------------------
# Only the plain stat items are modelled; the glove/shield/sword downgrade
# cases depend on the custom-image bookkeeping of the original and are left
# out (they are never offered).

def giveaway_icon_offset(sprite_size: Tuple[int, int], chat_offset_y: float = 0.0,
                         on_horse: bool = False) -> Tuple[float, float]:
    """Icon top-left offset in tiles; sprite_size is in source pixels."""
    # drawSpriteCentral places the sprite's centre at the supplied tile point:
    # Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:5385-5389.
    # That C++ transcription repeats 0.5; the assembly loads distinct constants
    # 0x78 bytes apart (0.5 and 1/16), then multiplies both dimensions by both:
    # Preagonal/FourPlay/quattroplay/asm/TPlayer/_ZN7TPlayer17drawSpriteCentralEiff.s_decomped:7-18
    # Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1223-1225.
    # The centre is player + (1.5, chatOffset.y), or y-1 on horseback:
    # Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:3975-3977,4004-4027.
    # chatOffset is script-set and defaults to (0, 0):
    # Preagonal/FourPlay/quattroplay/src/TServerPlayerProperties.cpp:104-107
    # Preagonal/FourPlay/quattroplay/src/TServerPlayer.cpp:97
    # Preagonal/FourPlay/quattroplay/include/TFloatPoint.h:16.
    width, height = sprite_size
    return 1.5 - width / 32.0, (-1.0 if on_horse else chat_offset_y) - height / 32.0


def giveaway_available(index: int, rupees: int, bombs: int, arrows: int,
                       hearts: float) -> bool:
    if index in (0,):
        return rupees > 0
    if index == 1:
        return rupees > 4
    if index == 2:
        return rupees > 29
    if index == 19:
        return rupees > 99
    if index == 3:
        return bombs > 4
    if index == 4:
        return arrows > 4
    if index == 5:
        return hearts >= 1.5
    return False


# Stat prop -> amount taken by loseItem.
GIVEAWAY_COST = {0: ('rupees', 1), 1: ('rupees', 5), 2: ('rupees', 30),
                 19: ('rupees', 100), 3: ('bombs', 5), 4: ('arrows', 5),
                 5: ('hearts', 1.0)}


def next_give_item(available: Callable[[int], bool],
                   selected: Optional[int]) -> int:
    """TPlayer::nextGiveItem. `selected` None = first press (mode != 9)."""
    count = len(GIVE_ORDER)
    start, end = 0, count - 1
    if selected is not None:
        if selected == GIVE_ORDER[0]:
            start, end = 1, count
        elif selected in GIVE_ORDER:
            start, end = GIVE_ORDER.index(selected) + 1, count
        else:
            return -1
    for index in range(start, end + 1):
        item = GIVE_ORDER[index % count]
        if available(item):
            return item
    return -1


def drop_position(local_x: float, local_y: float, direction: int
                  ) -> Tuple[float, float]:
    """Level-local drop spot, snapped down to the half-tile the wire carries."""
    dx, dy = LAY_OFFSETS[direction & 3]
    x = local_x + LAY_BASE[0] + dx
    y = local_y + LAY_BASE[1] + dy
    return math.floor(x * 2) / 2.0, math.floor(y * 2) / 2.0


# --- per-client bookkeeping -------------------------------------------------

def item_ages(owner, level_name: str, items: Dict[Tuple[float, float], str],
              now: float) -> Dict[Tuple[float, float], float]:
    """Seconds since each ground item was first seen, kept on `owner`.

    The server owns removal, so the clock starts the first frame an item shows
    up in `items` and entries for items that are gone are forgotten. The
    take-sent set is pruned the same way, which is what lets a re-dropped item
    at the same spot be taken again.
    """
    seen = owner.__dict__.setdefault('_item_first_seen', {})
    sent = owner.__dict__.setdefault('_item_take_sent', set())
    live = {(level_name, key) for key in items}
    for stale in [k for k in seen if k[0] == level_name and k not in live]:
        del seen[stale]
    sent.difference_update([k for k in sent if k[0] == level_name and k not in live])
    ages = {}
    for key in items:
        ages[key] = now - seen.setdefault((level_name, key), now)
    return ages
