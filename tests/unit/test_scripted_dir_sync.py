"""Regression test: mid-walk direction changes under script-driven movement
(disabledefmovement) must reach the local player's sprite.

Live evidence (Bomber v6, -Test/Movement weapon): switching arrow keys while
walking kept the character facing/animating the OLD direction. The weapon's
Movement() writes `player.dir = k` on every timer tick a key is held, but its
Animate() only calls setani() on movemode TRANSITIONS (IDLE->WALK etc.), so
the setani->player_anim bridge in gs2_client never fires for a WALK->WALK
direction change. The real client re-reads player.dir every frame for the
local sprite. RenderMixin._update_animations now mirrors that whenever a
script drives movement (gs1.default_movement False).

The engine side (keydown() -> player.dir write -> movement vector) was
verified correct against the cached v6 bytecode. Only the renderer facing
was stale, so that is what's pinned here.
"""

import pytest


@pytest.fixture
def harness(make_game):
    """A real offline game, script-driven movement, mid-walk facing down."""
    h = make_game()
    h.gs1.default_movement = False
    h.client.player.direction = 3
    h.player_anim.set_animation("walk", 3, force=True)   # a looping gani
    h.current_anim_name = "walk"
    h.is_moving = False
    return h


def test_scripted_movement_dir_change_reaches_sprite_mid_walk(harness):
    h = harness
    # Script wrote a new direction mid-walk (WALK->WALK, no setani fired).
    h.client.player.direction = 0
    h._update_animations(0.05)
    assert h.player_anim.direction == 0


def test_scripted_movement_float_dir_is_coerced(harness):
    h = harness
    h.client.player.direction = 1.0  # GS1 engine hands back floats
    h._update_animations(0.05)
    assert h.player_anim.direction == 1
    assert isinstance(h.player_anim.direction, int)


def test_default_movement_keeps_builtin_facing_ownership(harness):
    # With built-in movement, actions.py owns facing (grab/corner-assist hold
    # a facing that deliberately differs from player.direction) — the sync
    # must NOT run then.
    h = harness
    h.gs1.default_movement = True
    h.current_anim_name = "idle"  # keep the walk->idle fallback out of the way
    h.client.player.direction = 0
    h._update_animations(0.05)
    assert h.player_anim.direction == 3


def test_scripted_movement_walk_anim_not_stomped_to_idle(harness):
    # The 59976de stomp gate: is_moving is only set by the built-in path, so
    # with a script driving movement the walk gani must survive even though
    # is_moving is False.
    h = harness
    h.current_anim_name = "walk"
    h._update_animations(0.05)
    assert h.current_anim_name == "walk"
