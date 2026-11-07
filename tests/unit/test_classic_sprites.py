"""Independent reference indices and sheet geometry for classic sprites."""

import pytest

from pyreborn.classic_sprites import SPRITE_RECTS, sprite_rect
from pyreborn.ground_items import GIVE_SPRITES, item_index


@pytest.mark.parametrize('item,rect', [
    ('greenrupee', (0, 144, 16, 32)),
    ('bluerupee', (16, 144, 16, 32)),
    ('redrupee', (32, 144, 16, 32)),
    ('heart', (42, 176, 16, 16)),
    ('glove1', (28, 212, 28, 32)),
    ('bombs', (70, 216, 28, 32)),
    ('darts', (84, 138, 16, 32)),
    ('sword', (0, 176, 16, 34)),
    ('shield', (42, 192, 16, 20)),
    ('bow', (56, 212, 14, 32)),
])
def test_giveitems_addresses_expected_art(item, rect):
    # giveitems: TInitStatics.cpp:1197-1201; geometry from sprites.png.
    assert sprite_rect(GIVE_SPRITES[item_index(item)]) == rect


@pytest.mark.parametrize('index,rect', [
    (42, (24, 0, 16, 8)),  # TServerExtra.cpp:63: ground-item shadow
    (67, (70, 216, 28, 32)),
    (96, (24, 82, 16, 16)),  # TServerLeap.cpp:34-46: stone/bush fragments
    (97, (40, 82, 16, 16)),
    (98, (24, 98, 16, 16)),
    (99, (40, 98, 16, 16)),
    (100, (56, 82, 16, 14)),
    (103, (72, 96, 16, 14)),
    (107, (10, 422, 10, 30)),  # TServerFlying.cpp:23: up/left/down/right
    (108, (0, 412, 30, 10)),
    (109, (0, 422, 10, 30)),
    (110, (0, 402, 30, 10)),
    (131, (64, 144, 16, 26)),
    (132, (0, 116, 12, 14)),  # TServerLeap.cpp:50-54: four stone chips
    (135, (12, 130, 12, 14)),
    (150, (0, 306, 32, 16)),  # TServerPlayer.cpp:1271-1278: swamp pairs
    (151, (0, 322, 32, 16)),
    (350, (42, 192, 16, 20)),
    (351, (56, 212, 14, 32)),
])
def test_reference_sprite_anchors(index, rect):
    assert sprite_rect(index) == rect


def test_placeholder_extends_zero_run_before_first_stone_fragment():
    assert SPRITE_RECTS[69:96] == ((0, 0, 0, 0),) * 27


def test_leap_renderer_uses_correct_fragment_blocks():
    from pyreborn.game.render_effects import EffectsRenderMixin

    rects = EffectsRenderMixin._LEAP_SPRITE_RECTS
    assert rects[96] == (24, 82, 16, 16)
    assert rects[103] == (72, 96, 16, 14)
    assert rects[132] == (0, 116, 12, 14)
    assert rects[135] == (12, 130, 12, 14)


def test_arrow_collision_uses_directional_sprite_dimensions():
    from pyreborn.arrowflight import ARROW_SIZES, overlaps_player

    assert ARROW_SIZES == ((0.625, 1.875), (1.875, 0.625),
                           (0.625, 1.875), (1.875, 0.625))
    # The up arrow is narrow; the left arrow reaches the player's left edge.
    assert not overlaps_player(0, 0, 0, 0.5, -1)
    assert overlaps_player(0, 0, 1, 0.5, -1)
