"""Action gani and lightweight world-particle regressions."""

from types import SimpleNamespace

from pyreborn.game.actions import ActionsMixin
from pyreborn.game.render import RenderMixin
from pyreborn.game.render_effects import EffectsRenderMixin


class _Animation:
    def __init__(self, setback=None):
        self.calls = []
        self.setback = setback

    def set_animation(self, name, direction, force=False):
        self.calls.append((name, direction, force))

    def update(self, dt):
        return []

    def is_finished(self):
        return self.setback is not None

    def get_setback(self):
        return self.setback


class _Client:
    def __init__(self):
        self.player = SimpleNamespace(
            direction=3, hearts=3, is_sitting=False,
            is_carrying=lambda: False,
        )
        self.animations = []
        self.players = {}
        self.npcs = {}
        self.baddies = {}
        self.horses = {}

    def set_animation(self, name):
        self.animations.append(name)


def test_action_animation_is_local_and_server_visible():
    h = SimpleNamespace(client=_Client(), player_anim=_Animation(),
                        current_anim_name='idle')

    ActionsMixin._play_action_animation(h, 'shoot')

    assert h.player_anim.calls == [('shoot', 3, True)]
    assert h.current_anim_name == 'shoot'
    assert h.client.animations == ['shoot']


def test_finished_action_broadcasts_its_setback():
    h = SimpleNamespace(
        client=_Client(), player_anim=_Animation('idle'), sound_mgr=SimpleNamespace(
            play_from_gani=lambda sound: None), current_anim_name='shoot',
        is_moving=False, is_swimming=False, grab_state=None,
        is_pushing=False, other_player_anims={}, other_player_visual={},
        npc_anims={}, npc_visual={}, baddy_anims={}, baddy_visual={},
        horse_anims={},
    )
    h._update_sitting_state = lambda: None

    RenderMixin._update_animations(h, 0.1)

    assert ('idle', 3, False) in h.player_anim.calls
    assert h.current_anim_name == 'idle'
    assert h.client.animations == ['idle']


class _Particles(EffectsRenderMixin):
    def __init__(self):
        self.leaf_particles = []


def test_leaf_spawn_is_capped():
    h = _Particles()

    for _ in range(20):
        h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=6)

    assert len(h.leaf_particles) == h.MAX_LEAF_PARTICLES
    assert h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=6) == 0


def test_leaf_particles_expire_after_lifetime():
    h = _Particles()
    h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=5)

    assert len(h._expire_leaf_particles(now=10.59)) == 5
    assert h._expire_leaf_particles(now=10.6) == []
