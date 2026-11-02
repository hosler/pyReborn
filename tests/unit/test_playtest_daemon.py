"""Exercise the HTTP handler directly through in-memory streams, without sockets."""

from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from game_tester.game_bot import GameBot
from game_tester import playtest_daemon as daemon


def daemon_bot(monkeypatch):
    bot = GameBot('daemon_test', 'localhost', 1)
    bot.client._current_level_name = 'test.nw'
    bot.client.tiles = [0] * 4096
    bot.client.player.x = bot.client.player.y = 10
    monkeypatch.setattr(bot, 'update', lambda duration: None)
    monkeypatch.setattr(daemon, 'bots', {bot.name: bot})
    monkeypatch.setattr(daemon, '_bot_last_level', {bot.name: bot.level})
    calls = []

    def move(dx, dy):
        calls.append((dx, dy))
        bot.client.player.x += dx * 0.25
        bot.client.player.y += dy * 0.25
        return True

    monkeypatch.setattr(bot.client, 'move', move)
    return bot, calls


def request(query, path='/act'):
    handler = daemon.Handler.__new__(daemon.Handler)
    handler.path = path + '?name=daemon_test&' + query
    handler.requestline = 'GET ' + handler.path + ' HTTP/1.1'
    handler.request_version = 'HTTP/1.1'
    handler.command = 'GET'
    handler.wfile = BytesIO()
    handler.do_GET()
    headers, body = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    assert b'Content-Type: application/json' in headers
    return int(headers.split(b' ')[1]), json.loads(body)


def test_daemon_travel_dispatches_and_returns_state(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)
    calls = []
    monkeypatch.setattr(bot, 'travel_to', lambda **kw: calls.append(kw) or True)
    code, response = request('cmd=travel&level=next.nw&x=0&y=2.5')
    assert code == 200 and response['result'] is True
    assert response['state']['level'] == bot.level
    assert calls == [dict(level_name='next.nw', x=0, y=2.5)]


def test_daemon_route_merges_world_and_observed_without_moving(monkeypatch):
    from game_tester.world_graph import WorldGraph
    bot, moves = daemon_bot(monkeypatch)
    graph = WorldGraph()
    link = dict(x=1, y=2, width=3, height=4, dest_level='hall.nw',
                dest_x='playerx', dest_y=10)
    graph.add_observed('test.nw', [link])
    bot.world_graph = graph
    bot.client.links['hall.nw'] = [dict(link, dest_level='end.nw')]
    code, response = request('level=END.NW', '/route')
    assert code == 200
    assert [hop['dest_level'] for hop in response['route']] == ['hall.nw', 'end.nw']
    assert response['route'][0] == dict(source_level='test.nw', x=1, y=2,
                                      width=3, height=4, dest_level='hall.nw',
                                      dest_x='playerx', dest_y=10, seam=False)
    assert request('level=unknown.nw', '/route') == (200, {'route': None})
    assert request('level=test.nw', '/route') == (200, {'route': []})
    assert request('', '/route')[0] == 400
    assert moves == []


def test_daemon_fractional_move_is_one_scaled_step(monkeypatch):
    bot, calls = daemon_bot(monkeypatch)
    code, response = request('cmd=move&dy=-0.25')
    assert code == 200
    assert response['result'] is True
    assert calls == [(0.0, -0.25)]
    assert bot.y == 9.9375


def test_daemon_large_move_is_clamped_to_one_step(monkeypatch):
    bot, calls = daemon_bot(monkeypatch)
    code, response = request('cmd=move&dy=-10&dx=999')
    assert code == 200 and response['result'] is True
    assert calls == [(1.0, -1.0)]
    assert (bot.x, bot.y) == (10.25, 9.75)


@pytest.mark.parametrize('value', ['invalid', 'nan', 'inf', '-inf', '1e999'])
def test_daemon_invalid_move_returns_error_json(monkeypatch, value):
    _, calls = daemon_bot(monkeypatch)
    code, response = request('cmd=move&dy=' + value)
    assert code == 400
    assert response['error'].startswith('bad argument:')
    assert calls == []


def test_daemon_unknown_attack_target_returns_error_string(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)
    sent = []
    monkeypatch.setattr(bot.client, 'attack_player', lambda *args: sent.append(args))
    code, response = request('cmd=attack&pid=999')
    assert code == 200
    assert response['result'] == 'no visible player with id 999'
    assert sent == []
    assert bot.action_log[-1].result == response['result']


def test_daemon_known_attack_target_uses_existing_action(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)
    bot.client.players[7] = {'x': 11, 'y': 10}
    sent = []
    monkeypatch.setattr(bot.client, 'attack_player',
                        lambda *args: sent.append(args) or True)
    code, response = request('cmd=attack&pid=7')
    assert code == 200 and response['result'] is True
    assert sent == [(7, 0.5)]


def test_daemon_action_exception_is_also_json(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)

    def fail(**kwargs):
        raise RuntimeError('synthetic failure')

    monkeypatch.setattr(bot, 'move', fail)
    code, response = request('cmd=move&dx=1')
    assert code == 500
    assert response == {'error': 'error: synthetic failure'}


def test_daemon_idle_pumps_log_death_and_respawn(monkeypatch):
    bot = GameBot('idle_test', 'localhost', 1)
    hearts = iter([3, 0, 3])
    observed = []
    now = [100.0]
    client = SimpleNamespace(player=SimpleNamespace(hearts=3), x=12.0, y=8.0)

    def update(timeout):
        client.player.hearts = next(hearts)

    client.update = update
    bot.client = client
    monkeypatch.setattr(daemon, 'bots', {bot.name: bot})
    monkeypatch.setattr(daemon, 'running', True)
    monkeypatch.setattr('game_tester.game_bot.time.time', lambda: now[0])

    def sleep(duration):
        now[0] += duration
        if duration == 0.05:  # End of an idle background pump, no /act call.
            observed.append(client.player.hearts)
            if len(observed) == 3:
                daemon.running = False

    monkeypatch.setattr(daemon.time, 'sleep', sleep)
    daemon.pump_loop()

    assert observed == [3, 0, 3]
    assert len(bot.position_history) == 3
    assert [(issue.severity, issue.description) for issue in bot.issues] == [
        ('MEDIUM', 'Bot died at (12.0, 8.0)'),
        ('LOW', 'Bot respawned at (12.0, 8.0)'),
    ]


def test_daemon_state_uses_nickname_keys_and_explicit_ids(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)
    original = {'nickname': 'Alice', 'account': 'alice_account',
                'x': 30, 'y': 31, 'chat': 'hello'}
    bot.client.players[7] = original.copy()
    state = json.loads(json.dumps(daemon.bot_state(bot)))
    assert state['players_visible'] == {'Alice': dict(original, id=7)}
    assert state['players_visible_by_id'] == {'7': dict(original, id=7)}
    assert bot.client.players[7] == original


@pytest.mark.parametrize('reverse', [False, True])
def test_daemon_state_empty_duplicate_and_numeric_nicknames(monkeypatch, reverse):
    bot, _ = daemon_bot(monkeypatch)
    entries = [(1, {'nickname': ''}), (2, {}), (3, {'nickname': 'same'}),
               (4, {'nickname': 'same'}), (5, {'nickname': '1'}),
               (6, {'nickname': 'Alice'}), (7, {'nickname': '   '})]
    bot.client.players = dict(reversed(entries) if reverse else entries)
    state = daemon.bot_state(bot)
    assert {key: entry['id'] for key, entry in state['players_visible'].items()} == {
        '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, 'Alice': 6, '7': 7}
    assert {key: entry['id'] for key, entry in state['players_visible_by_id'].items()} == {
        str(pid): pid for pid, entry in entries}


def test_daemon_state_id_usable_for_pm_and_attack(monkeypatch):
    bot, _ = daemon_bot(monkeypatch)
    bot.client.players[7] = {'nickname': 'Alice'}
    pid = daemon.bot_state(bot)['players_visible']['Alice']['id']
    calls = []
    monkeypatch.setattr(bot, 'send_pm',
                        lambda **kwargs: calls.append(('pm', kwargs)) or True)
    monkeypatch.setattr(bot, 'attack_player',
                        lambda **kwargs: calls.append(('attack', kwargs)) or True)
    assert request(f'cmd=pm&pid={pid}&msg=hello')[1]['result'] is True
    assert request(f'cmd=attack&pid={pid}')[1]['result'] is True
    assert calls == [('pm', {'player_id': 7, 'message': 'hello'}),
                     ('attack', {'player_id': 7})]
