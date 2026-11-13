"""Action gani and lightweight world-particle regressions (real offline game)."""

from offline_game import spy


def test_action_animation_is_local_and_server_visible(make_game, monkeypatch):
    h = make_game()
    h.client.player.direction = 3
    local = spy(monkeypatch, h.player_anim, 'set_animation')
    sent = spy(monkeypatch, h.client, 'set_animation')

    h._play_action_animation('shoot')

    assert [args[:2] + (args[2:] or (kwargs.get('force'),))[:1]
            for args, kwargs in local] == [('shoot', 3, True)]
    assert h.current_anim_name == 'shoot'
    assert [args[0] for args, _ in sent] == ['shoot']


def test_finished_action_broadcasts_its_setback(make_game, monkeypatch):
    h = make_game()
    h.client.player.direction = 3
    h._play_action_animation('hurt')
    # The synthetic ganis carry no SETBACKTO: this one finished, back to idle.
    monkeypatch.setattr(h.player_anim, 'is_finished', lambda: True)
    monkeypatch.setattr(h.player_anim, 'get_setback', lambda: 'idle')
    sent = spy(monkeypatch, h.client, 'set_animation')
    h.is_moving = False

    h._update_animations(0.1)

    assert h.current_anim_name == 'idle'
    assert [args[0] for args, _ in sent] == ['idle']


def test_leaf_spawn_is_capped(make_game):
    h = make_game()
    h.leaf_particles = []

    for _ in range(20):
        h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=6)

    assert len(h.leaf_particles) == h.MAX_LEAF_PARTICLES
    assert h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=6) == 0


def test_leaf_particles_expire_after_lifetime(make_game):
    h = make_game()
    h.leaf_particles = []
    h._spawn_leaf_particles(4.0, 5.0, now=10.0, count=5)

    assert len(h._expire_leaf_particles(now=10.59)) == 5
    assert h._expire_leaf_particles(now=10.6) == []
