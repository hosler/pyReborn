"""The heart row never runs under the weapon box.

The reference client draws no HUD (its decompile has no heart row or weapon
box), so this layout is our own: hearts wrap into rows of ten and the plate
widens so that the weapon box sits right of a full row.
"""

import pygame
import pytest
from offline_checks import (
    HEART_EMPTY, HEART_FULL, HEART_PITCH, HEART_X0, HEART_Y0, read_hearts,
    settle,
)
import offline_expect as ex
from pyreborn.game import theme
from pyreborn.game.hud import StatsPanel
from pyreborn.inventory_ui import HeartDisplay


def _heart_rects(maximum):
    size = HeartDisplay.HEART_SIZE
    return [pygame.Rect(HEART_X0 + (i % 10) * HEART_PITCH,
                        HEART_Y0 + (i // 10) * HEART_PITCH, size, size)
            for i in range(maximum)]


def _panel_w(maximum):
    columns = min(HeartDisplay.HEARTS_PER_ROW, maximum)
    return StatsPanel.panel_width(columns * (HeartDisplay.HEART_SIZE
                                             + HeartDisplay.HEART_SPACING))


@pytest.mark.parametrize("maximum", [3, 10, 14, 20])
def test_no_heart_overlaps_the_weapon_box(maximum):
    """Rect overlap, from the layout the HUD itself uses.

    Mutation: in `StatsPanel.panel_width` return `max(218, hearts_w + 16)`
    (the old width) -> the tenth heart of a full row overlaps the box.
    """
    slot = StatsPanel.weapon_slot_rect(_panel_w(maximum))
    for rect in _heart_rects(maximum):
        assert not rect.colliderect(slot), (maximum, rect, slot)


@pytest.mark.parametrize("maximum", [3, 10, 14, 20])
def test_hearts_and_weapon_box_both_draw_where_the_layout_says(make_game,
                                                               maximum):
    """Colour at a position, on the real frame: every heart is read back
    (full, then empty), and the weapon box well is on top of nothing else.

    Mutation: `StatsPanel.panel_width` returning the old `hearts_w + 16`
    -> at 10, 14 and 20 hearts the box paints over the last column's hearts
    and `read_hearts` no longer finds them.
    """
    full = maximum - 1
    game = make_game(hearts=float(full), me={"max_hearts": float(maximum)})
    frame = settle(game, label=f"hud_hearts_layout_{maximum}")
    drawn = read_hearts(frame, maximum)
    assert drawn == ["full"] * full + ["empty"], (maximum, drawn)
    assert HEART_FULL != HEART_EMPTY
    slot = StatsPanel.weapon_slot_rect(_panel_w(maximum))
    # The well's interior, away from its rounded border, is the slot colour
    # (nothing selected, so no icon or label is on it).
    for dx, dy in ((4, 4), (31, 4), (4, 31), (31, 31)):
        assert ex.pixel(frame, (slot.x + dx, slot.y + dy)) == theme.SLOT_BG, (
            maximum, dx, dy)
