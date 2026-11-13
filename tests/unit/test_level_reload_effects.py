"""Level reloads deterministically clear the unified bomb registry."""

class TestReloadClearsServerBombSeen:
    def test_server_bomb_seen_cleared_on_level_change(self, make_game):
        h = make_game()
        h.active_projectiles = [{'x': 1.0}]
        h.thrown_objects = [{'x': 1.0}]
        h.active_bombs = [{
            'x': 5.0, 'y': 5.0, 'time': 123.0, 'source': 'remote',
            'power': 1, 'exploded': False,
        }]
        h.active_bomb_explosions = [{'x': 1.0}]
        h.particles.breaks = [{'x': 1.0}]

        h._reload_level_scripts("level2.nw")

        # Remote and local bombs now share active_bombs.  There is no separate
        # first-seen map that can be repopulated or cleared out of order.
        assert h.active_bombs == []
        assert h.active_projectiles == []


class TestReloadClearsLevelLocalParticles:
    def test_reload_drops_breaks_leaves_ripples_and_keeps_leaps_and_numbers(
            self, make_game):
        h = make_game()
        p = h.particles
        p.breaks.append({'x': 1.0})
        p.leaves.append({'x': 1.0})
        p.ripples.append({'x': 1.0})
        p.leaps.append({'x': 1.0})
        p.damage_numbers.append({'x': 1.0})

        h._reload_level_scripts("level2.nw")

        assert p.breaks == [], "breaks are level-local"
        assert p.leaves == [], "leaves are level-local"
        assert p.ripples == [], "ripples are level-local"
        assert p.leaps == [{'x': 1.0}], "leaps survive a reload"
        assert p.damage_numbers == [{'x': 1.0}], "damage numbers survive a reload"
