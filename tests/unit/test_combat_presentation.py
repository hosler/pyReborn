from pyreborn.game.combat_presentation import CombatPresentation


def test_invulnerability_blink_runs_for_full_grace_window():
    state = CombatPresentation()
    state.hurt(10.0)
    assert state.player_alpha(10.00) == 255
    assert state.player_alpha(10.11) == 105
    assert state.player_alpha(10.21) == 255
    assert state.player_alpha(11.19) == 105
    assert state.player_alpha(11.20) == 255


def test_new_hurt_restarts_blink_and_hit_flash():
    state = CombatPresentation()
    state.hurt(2.0)
    state.hurt(2.5)
    assert state.hurt_until == 3.7
    assert state.hit_flash_alpha(2.5) == 100
    assert state.hit_flash_alpha(2.65) == 0


def test_death_overlay_waits_then_is_suppressed_by_warp():
    state = CombatPresentation()
    state.hurt(5.0, dead=True)
    assert not state.show_death_overlay(5.2)
    assert state.show_death_overlay(5.35)
    state.sync(dead=True, warp_active=True, now=5.4)
    assert not state.show_death_overlay(6.0)


def test_respawn_clears_death_and_fades_in_for_half_second():
    state = CombatPresentation()
    state.hurt(1.0, dead=True)
    state.sync(dead=False, warp_active=False, now=3.0)
    assert state.death_started is None
    assert state.respawn_fade_alpha(3.0) == 255
    assert 120 <= state.respawn_fade_alpha(3.25) <= 135
    state.sync(dead=False, warp_active=False, now=3.5)
    assert state.respawn_started is None
    assert state.respawn_fade_alpha(3.5) == 0
