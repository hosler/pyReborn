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

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn.game.render import RenderMixin


class _AnimStub:
    """Records set_direction. The rest of the AnimationState surface used by
    _update_animations is inert."""

    def __init__(self, direction=3):
        self.direction = direction

    def set_direction(self, direction):
        if 0 <= direction <= 3:
            self.direction = direction

    def update(self, dt):
        return []

    def is_finished(self):
        return False

    def set_animation(self, name, direction=None, force=False):
        if direction is not None:
            self.direction = int(direction) & 3


class _PlayerStub:
    direction = 3
    is_sitting = False

    def is_carrying(self):
        return False


class _ClientStub:
    def __init__(self):
        self.player = _PlayerStub()
        self.players = {}
        self.npcs = {}
        self.baddies = {}
        self.horses = {}


class _GS1Stub:
    default_movement = False


class _Harness(RenderMixin):
    """Minimal GameClient stand-in for the animation-update slice."""

    def __init__(self):
        self.client = _ClientStub()
        self.player_anim = _AnimStub(direction=3)
        self.gs1 = _GS1Stub()
        self.current_anim_name = "walk"
        self.grab_state = None
        self._grab_direction = 2
        self.is_pushing = False
        self.is_moving = False
        self.is_swimming = False
        self.other_player_anims = {}
        self.other_player_visual = {}
        self.npc_anims = {}
        self.npc_visual = {}
        self.baddy_anims = {}
        self.horse_anims = {}

    def _update_sitting_state(self):
        pass

    def _play_entity_sounds(self, sounds, world_pos):
        pass


def test_scripted_movement_dir_change_reaches_sprite_mid_walk():
    h = _Harness()
    # Script wrote a new direction mid-walk (WALK->WALK, no setani fired).
    h.client.player.direction = 0
    h._update_animations(0.05)
    assert h.player_anim.direction == 0


def test_scripted_movement_float_dir_is_coerced():
    h = _Harness()
    h.client.player.direction = 1.0  # GS1 engine hands back floats
    h._update_animations(0.05)
    assert h.player_anim.direction == 1
    assert isinstance(h.player_anim.direction, int)


def test_default_movement_keeps_builtin_facing_ownership():
    # With built-in movement, actions.py owns facing (grab/corner-assist hold
    # a facing that deliberately differs from player.direction) — the sync
    # must NOT run then.
    h = _Harness()
    h.gs1.default_movement = True
    h.current_anim_name = "idle"  # keep the walk->idle fallback out of the way
    h.client.player.direction = 0
    h._update_animations(0.05)
    assert h.player_anim.direction == 3


def test_scripted_movement_walk_anim_not_stomped_to_idle():
    # The 59976de stomp gate: is_moving is only set by the built-in path, so
    # with a script driving movement the walk gani must survive even though
    # is_moving is False.
    h = _Harness()
    h.current_anim_name = "walk"
    h._update_animations(0.05)
    assert h.current_anim_name == "walk"
