"""Simulation constants shared by the library layer and the game layer.

The library (client actions, combat, GS2 player objects) reads these, so they
live here rather than in game/constants.py; that module re-exports them.
"""

WALK_SPEED = 10.0  # FourPlay TPlayer.cpp:807
BOMB_FUSE_TIME = 3.0  # GServer Level.cpp:1986

# Player collision geometry relative to the 3x3 sprite's top-left anchor.
PLAYER_COLLISION_LEFT = 0.5
PLAYER_COLLISION_RIGHT = 2.5
PLAYER_COLLISION_TOP = 1.0
PLAYER_COLLISION_BOTTOM = 3.0
PLAYER_BODY_CENTER_X = (PLAYER_COLLISION_LEFT + PLAYER_COLLISION_RIGHT) / 2
PLAYER_BODY_CENTER_Y = (PLAYER_COLLISION_TOP + PLAYER_COLLISION_BOTTOM) / 2
