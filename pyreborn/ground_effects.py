"""Ground-driven HP ticks: lava damage (TPlayer.cpp:5887) and sleeping heal."""

import math

from .hurt import TICK_SECONDS

# testForLava :5898-5902 - tile types 2, 9 and 12 at the ground point.
LAVA_TILE_TYPES = (2, 9, 12)
LAVA_SWIM_TILE_TYPE = 12  # testForWater :6021 picks defanis[29] "lava" for it.
SWIM_ACTION_MODE = 10  # TPlayer.cpp:6018,6029
SWIM_LEAP_TYPE = 5  # TPlayer.cpp:6010-6011,6039-6040; TServerLevel.cpp:2864
# TPlayer.cpp:6010-6011,6039-6040; TInitStatics.cpp:1253,1274 (0.5, 1.0).
SWIM_LEAP_OFFSET = (0.5, 1.0)
LAVA_DAMAGE = 0.5  # DOUBLE_00402678 = -0.5, TInitStatics.cpp:1279.
SLEEP_HEAL = 0.5  # DOUBLE_00402410 = 0.5, TPlayer.cpp:7359 changePower.
HP_TICKS = 100  # Counter must exceed 100 (:5906, :7353): the 101st tick fires.
BED_TILE_TYPE = 4  # BED_UPPER, testSittingSleeping :5942-5972.
# Columns/rows sampled for a bed: x+1.0 and x+2.0, at y and y+0.5.
BED_COLUMNS = (1.0, 2.0)
BED_ROWS = (0.0, 0.5)
BED_SNAP_EPSILON = 0.0001  # DOUBLE_00402440, :6054 floorToInt(y + eps).
SLEEP_ANI = "sleep"
LAVA_ANI = "lava"


class TickCounter:
    """Counts 20 Hz ticks of an active condition; fires on the 101st.

    An inactive tick resets the count (testForLava :5902-5904, the swim/sleep
    branch :7365). Firing resets it too.
    """

    def __init__(self):
        self.count = 0
        self.elapsed = 0.0

    def reset(self):
        self.count = 0

    def advance(self, dt, active):
        """Return how many times the counter fired over `dt` seconds."""
        self.elapsed += max(0.0, dt)
        ticks = int((self.elapsed + 1e-9) / TICK_SECONDS)
        self.elapsed -= ticks * TICK_SECONDS
        fired = 0
        for _ in range(ticks):
            if not active:
                self.count = 0
                continue
            self.count += 1
            if self.count > HP_TICKS:
                self.count = 0
                fired += 1
        return fired


def is_lava_type(tile_type):
    return tile_type in LAVA_TILE_TYPES


def bed_samples(x, y):
    """The four (x, y) probes per bed column pair: [(left...), (right...)]."""
    return [[(x + col, y + row) for row in BED_ROWS] for col in BED_COLUMNS]


def bed_snap_y(y, hit_on_top_row):
    """Final y after the sleep snap (:6046-6055).

    `hit_on_top_row` is True when a bed tile was found on the y row of either
    column; otherwise only the y+0.5 samples hit and y first moves by 0.5.
    """
    if not hit_on_top_row:
        y += 0.5
    return float(math.floor(y + BED_SNAP_EPSILON))
