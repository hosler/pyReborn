"""Nickname colour for an alignment-points (AP) value.

getAlignmentColorF, Preagonal/FourPlay/quattroplay/src/unsorted.cpp:1964-2037,
byte-packed by alignmentColorByte at :1944-1951; applied to the nickname at
TPlayer.cpp:3966.
"""

from typing import Tuple


def _byte(value: float) -> int:
    if value >= 1.0:
        return 255
    if value <= 0.0:
        return 0
    return int(value * 256.0)


def alignment_color(alignment) -> Tuple[int, int, int]:
    """RGB for an AP value: dark red at 0 rising to red (1-26), red to white
    (27-49), white (50-55), green (56-60), green to blue-green (61-70), blue
    to cyan (71-99), gold at 100+."""
    ap = int(alignment or 0)
    if ap <= 0:
        r, g, b = 0.25, 0.0, 0.0
    elif ap <= 26:
        step = (ap - 1) / 25.0
        r, g = 0.5 + step * 0.5, 0.25 - step * 0.25
        b = g
    elif ap <= 49:
        step = (ap - 26) / 24.0
        r, g, b = 1.0, step, step
    elif ap <= 55:
        r, g, b = 1.0, 1.0, 1.0
    elif ap <= 60:
        step = (ap - 55) / 5.0
        r = 1.0 - step * 0.5
        g, b = 1.0, r
    elif ap <= 70:
        step = (ap - 61) / 10.0
        r, g, b = 0.5 - step * 0.5, 1.0, 0.5 + step * 0.5
    elif ap <= 99:
        step = (ap - 70) / 29.0
        r, g, b = 0.0, 1.0 - step, 1.0
    else:
        r, g, b = 0.875, 0.75, 0.0
    return _byte(r), _byte(g), _byte(b)
