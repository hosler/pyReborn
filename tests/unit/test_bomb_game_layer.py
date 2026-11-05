"""Game-layer reconciliation with the Client bomb simulation.

A lying bomb detonates when Client._tick_bomb_sims fires (the callback runs
the presentation only). Carried and in-flight bombs, and bombs the client does
not know, keep the game layer's own clock.
"""

from unittest.mock import Mock

import pytest

from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.packets import PacketID
from .test_lift_oracle import Game


@pytest.fixture
def game(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('time.time', lambda: clock[0])
    g = Game()
    g.clock = clock
    g.client.player.x = g.client.player.y = 5.0
    g._request_asset = Mock()
    g.sprite_mgr = Mock()
    g.sprite_mgr.get_sprite.return_value = None
    g._render_explosion_burst = Mock()
    g._render_bomb_ticking = Mock()
    wire_client_callbacks(g)
    g.client._blast_board_at = Mock(return_value=set())
    return g


def lay(game, x, y, **kw):
    """The shell's local placement: client.put_bomb + the registry entry."""
    game.client.put_bomb(x, y, consume_ammo=False, **kw)
    bomb = {'x': x, 'y': y, 'time': game.clock[0], 'fuse_time': 3.0,
            'power': 1, 'exploded': False, 'source': 'local'}
    game.active_bombs.append(bomb)
    return bomb


def test_client_detonation_marks_the_matching_entry_and_runs_presentation(game):
    near = lay(game, 30.0, 30.0)
    other = lay(game, 40.0, 40.0, timer_ms=60000)
    game.clock[0] += 3.0
    game.client.update = Mock()
    game.client._tick_bomb_sims()
    assert near['exploded'] and not other['exploded']
    assert len(near['cells']) == 9
    game.sound_mgr.play.assert_called_once_with('bomb.wav')
    game._start_camera_shake.assert_called_once()
    # The Client already blasted the board; the game must not do it again.
    game.client._blast_board_at.assert_called()
    count = game.client._blast_board_at.call_count
    game._render_bombs()
    assert game.client._blast_board_at.call_count == count


def test_lying_bomb_is_not_detonated_by_the_game_clock(game):
    bomb = lay(game, 30.0, 30.0)
    game.clock[0] += 50.0                  # far past the game's own fuse
    game._render_bombs()
    assert not bomb['exploded']
    assert bomb in game.active_bombs
    game.client._tick_bomb_sims()          # the Client fires, the game follows
    game._render_bombs()
    assert bomb['exploded']


def test_bomb_unknown_to_the_client_keeps_the_legacy_clock(game):
    bomb = {'x': 30.0, 'y': 30.0, 'time': 100.0, 'fuse_time': 3.0,
            'power': 1, 'exploded': False, 'source': 'script'}
    game.active_bombs.append(bomb)
    game.clock[0] += 3.1
    game._render_bombs()
    assert bomb['exploded']


def test_carried_bomb_never_uses_a_clock_and_keeps_its_remaining_fuse(game):
    bomb = lay(game, 30.0, 30.0)
    game.client.bombs[game.client._current_level_name].clear()   # pickup removed it
    bomb['carried_by'] = game.client.player.id
    bomb['fuse_remaining'] = 1.0
    game.clock[0] += 60.0
    game.client._tick_bomb_sims()
    game._render_bombs()
    assert not bomb['exploded'] and bomb['fuse_remaining'] == 1.0


def test_unmatched_simulated_bomb_still_gets_presentation(game):
    game.client.put_bomb(30.0, 30.0, consume_ammo=False)   # no registry entry
    game.clock[0] += 3.0
    game.client._tick_bomb_sims()
    assert len(game.active_bombs) == 1 and game.active_bombs[0]['exploded']
    game.sound_mgr.play.assert_called_once_with('bomb.wav')


def test_bomb_del_stays_a_plain_removal(game):
    bomb = lay(game, 30.0, 30.0)
    game.client.on_bomb_del(30.0, 30.0)
    assert bomb not in game.active_bombs and not bomb['exploded']
    game.sound_mgr.play.assert_not_called()


def test_remote_entry_adopts_the_records_remaining_fuse(game):
    game.client.put_bomb(30.0, 30.0, consume_ammo=False)
    record = game.client.bombs[game.client._current_level_name][(30.0, 30.0)]
    game.clock[0] += 1.0
    bomb = game._add_remote_bomb(dict(record))
    assert bomb['time'] == record['placed_at'] and bomb['fuse_time'] == pytest.approx(3.0)
