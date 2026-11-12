"""Game-layer reconciliation with the Client bomb simulation.

A lying bomb detonates when Client._tick_bomb_sims fires (the callback runs
the presentation only). Carried and in-flight bombs, and bombs the client does
not know, keep the game layer's own clock.
"""

from unittest.mock import Mock

import pytest

from pyreborn.game.callbacks.client_callbacks import wire_client_callbacks
from pyreborn.game.callbacks.gs1_callbacks import wire_gs1_callbacks
from pyreborn.gs1_client import ClientGS1
from pyreborn.handlers.combat import handle_bomb_add, handle_bomb_del
from pyreborn.packets import build_bomb_del
from pyreborn.packets import PacketID
from .test_bomb_sim import bomb_add_packet
from .test_lift_oracle import Game


@pytest.fixture
def game(sim_time, monkeypatch):
    clock = [100.0]
    sim_time(lambda: clock[0])
    g = Game()
    g.t = clock
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
    bomb = {'x': x, 'y': y, 'time': game.t[0], 'fuse_time': 3.0,
            'power': 1, 'exploded': False, 'source': 'local'}
    game.active_bombs.append(bomb)
    return bomb


def test_client_detonation_marks_the_matching_entry_and_runs_presentation(game):
    near = lay(game, 30.0, 30.0)
    other = lay(game, 40.0, 40.0, timer_ms=60000)
    game.t[0] += 3.0
    game.client.update = Mock()
    game.client._tick_bomb_sims()
    assert near['exploded'] and not other['exploded']
    assert len(near['cells']) == 9
    game.sound_mgr.play.assert_called_once_with('bomb.wav')
    game._start_camera_shake.assert_called_once()
    # The Client already blasted the board; the game must not do it again.
    game.client._blast_board_at.assert_called()
    count = game.client._blast_board_at.call_count
    game._advance_bombs()
    assert game.client._blast_board_at.call_count == count


def test_lying_bomb_is_not_detonated_by_the_game_clock(game):
    bomb = lay(game, 30.0, 30.0)
    game.t[0] += 50.0                  # far past the game's own fuse
    game._advance_bombs()
    assert not bomb['exploded']
    assert bomb in game.active_bombs
    game.client._tick_bomb_sims()          # the Client fires, the game follows
    game._advance_bombs()
    assert bomb['exploded']


def test_bomb_unknown_to_the_client_keeps_the_legacy_clock(game):
    bomb = {'x': 30.0, 'y': 30.0, 'time': 100.0, 'fuse_time': 3.0,
            'power': 1, 'exploded': False, 'source': 'script'}
    game.active_bombs.append(bomb)
    game.t[0] += 3.1
    game._advance_bombs()
    assert bomb['exploded']


def test_carried_bomb_never_uses_a_clock_and_keeps_its_remaining_fuse(game):
    bomb = lay(game, 30.0, 30.0)
    game.client.bombs[game.client._current_level_name].clear()   # pickup removed it
    bomb['carried_by'] = game.client.player.id
    bomb['fuse_remaining'] = 1.0
    game.t[0] += 60.0
    game.client._tick_bomb_sims()
    game._advance_bombs()
    assert not bomb['exploded'] and bomb['fuse_remaining'] == 1.0


def test_unmatched_simulated_bomb_still_gets_presentation(game):
    game.client.put_bomb(30.0, 30.0, consume_ammo=False)   # no registry entry
    game.t[0] += 3.0
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
    record = next(iter(game.client.bombs[game.client._current_level_name].values()))
    game.t[0] += 1.0
    bomb = game._add_remote_bomb(dict(record))
    assert bomb['time'] == record['placed_at'] and bomb['fuse_time'] == pytest.approx(3.0)


def test_wire_stacks_stay_separate_in_the_game_and_gs1_array(game):
    game.gs1 = ClientGS1(game.client)
    wire_gs1_callbacks(game)
    for power in (1, 3, 2):
        handle_bomb_add(game.client, bomb_add_packet(9, 30, 30, power=power, ticks=5))
    assert len(game.active_bombs) == 3
    assert [b['power'] for b in game.gs1._host._bomb_list()] == [1, 3, 2]
    game.t[0] += .3
    game.client._tick_bomb_sims()
    assert all(b['exploded'] for b in game.active_bombs)
    assert game.sound_mgr.play.call_count == 3
    assert game.gs1._host._bomb_list() == []


def test_wire_bomb_del_clears_the_whole_game_stack_without_a_burst(game):
    for owner in (8, 9):
        handle_bomb_add(game.client, bomb_add_packet(owner, 30, 30))
    handle_bomb_del(game.client, build_bomb_del(30, 30))
    assert game.active_bombs == []
    assert not list(game.client._bomb_records())
    game.sound_mgr.play.assert_not_called()


@pytest.mark.parametrize('command', ['removebomb', 'explodebomb'])
def test_game_gs1_stack_removal_uses_the_bound_placement(game, command):
    game.gs1 = ClientGS1(game.client)
    wire_gs1_callbacks(game)
    script = f'if (playertouchsme) {{ {command} 1; }}'
    game.client.npcs[5] = {'x': 5, 'y': 5, 'script': script}
    game.gs1.load_script('npc_5', script, npc_id=5, x=5, y=5)
    for power in (1, 3):
        handle_bomb_add(game.client, bomb_add_packet(9, 30, 30, power=power))
    first, second = game.active_bombs
    game.client._explosion_cells = Mock(return_value=None)
    game.gs1.trigger_npc_event(5, 'playertouchsme')
    if command == 'removebomb':
        assert game.active_bombs == []
        assert not list(game.client._bomb_records())
        game.sound_mgr.play.assert_not_called()
    else:
        assert not first['exploded'] and second['exploded']
        assert [b['power'] for b in game.client._bomb_records()] == [1]
        assert game._bomb_blocks(31, 31)
        game.sound_mgr.play.assert_called_once_with('thunder.wav')
