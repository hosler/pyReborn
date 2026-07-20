"""Regression tests keeping standing and collision geometry independent."""

from pyreborn.game.constants import (
    PLAYER_BODY_CENTER_X,
    PLAYER_BODY_CENTER_Y,
    PLAYER_COLLISION_BOTTOM,
    PLAYER_COLLISION_LEFT,
    PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP,
    PLAYER_STAND_X,
    PLAYER_STAND_Y,
)
from pyreborn.game.render_entities import EntityRenderMixin


def test_standing_point_is_independent_from_collision_box():
    assert (PLAYER_COLLISION_LEFT, PLAYER_COLLISION_TOP) == (0.5, 1.0)
    assert (PLAYER_COLLISION_RIGHT, PLAYER_COLLISION_BOTTOM) == (2.5, 3.0)
    assert (PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y) == (1.5, 2.0)
    assert (PLAYER_STAND_X, PLAYER_STAND_Y) == (1.5, 2.5)
    assert PLAYER_STAND_Y != PLAYER_BODY_CENTER_Y


def test_shorter_npc_in_front_of_taller_player_sorts_first():
    entities = [
        ('player', EntityRenderMixin._depth_sort_key(0.0, 3.0)),
        ('npc', EntityRenderMixin._depth_sort_key(1.5, 1.0)),
    ]

    entities.sort(key=lambda entity: entity[1])

    assert [entity[0] for entity in entities] == ['npc', 'player']
