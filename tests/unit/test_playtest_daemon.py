"""Exercise the HTTP handler directly through in-memory streams, without sockets."""

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
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
    monkeypatch.setattr(daemon, 'bot_locks', {bot.name: threading.RLock()})
    monkeypatch.setattr(daemon, '_bot_last_level', {bot.name: bot.level})
    calls = []

    def move(dx, dy):
        calls.append((dx, dy))
        bot.client.player.x += dx * 0.25
        bot.client.player.y += dy * 0.25
        return True

    monkeypatch.setattr(bot.client, 'move', move)
    return bot, calls


def request(query, path='/act', name='daemon_test', server=None):
    handler = daemon.Handler.__new__(daemon.Handler)
    handler.path = path + '?name=' + name + '&' + query
    handler.requestline = 'GET ' + handler.path + ' HTTP/1.1'
    handler.request_version = 'HTTP/1.1'
    handler.command = 'GET'
    handler.wfile = BytesIO()
    handler.server = server
    handler.do_GET()
    headers, body = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    response = (json.loads(body) if b'Content-Type: application/json' in headers
                else body.decode())
    return int(headers.split(b' ')[1]), response


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
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(request, '', '/state').result(timeout=1)[0] == 200


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
    monkeypatch.setattr(daemon, 'bot_locks', {bot.name: threading.RLock()})
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


@pytest.fixture
def fake_bots(monkeypatch):
    bots = {
        name: SimpleNamespace(name=name, level='test.nw',
                              update=lambda duration: None, disconnect=lambda: None)
        for name in ('busy', 'idle')
    }
    monkeypatch.setattr(daemon, 'bots', bots)
    monkeypatch.setattr(daemon, 'bot_locks',
                        {name: threading.RLock() for name in bots})
    monkeypatch.setattr(daemon, '_bot_last_level',
                        {name: bot.level for name, bot in bots.items()})
    monkeypatch.setattr(daemon, 'running', True)
    monkeypatch.setattr(daemon, 'pending', set())
    monkeypatch.setattr(daemon, 'bot_state', lambda bot: {'name': bot.name})
    return bots


def test_state_for_other_bot_does_not_wait_for_slow_action(monkeypatch, fake_bots):
    started = threading.Event()

    def slow_action(bot, get):
        started.set()
        time.sleep(0.5)
        return True

    monkeypatch.setitem(GameBot.ACTIONS, 'slow', SimpleNamespace(run=slow_action))
    with ThreadPoolExecutor(max_workers=1) as pool:
        action = pool.submit(request, 'cmd=slow', name='busy')
        assert started.wait(timeout=1)
        start = time.monotonic()
        response = request('', '/state', name='idle')
        elapsed = time.monotonic() - start
        assert response == (200, {'name': 'idle'})
        assert elapsed < 0.2
        assert not action.done()
        assert action.result(timeout=1)[1]['result'] is True


def test_pump_skips_busy_bot_and_updates_idle_bot(monkeypatch, fake_bots):
    calls = {name: [] for name in fake_bots}
    for name, bot in fake_bots.items():
        bot.update = calls[name].append
    monkeypatch.setattr(daemon.time, 'sleep',
                        lambda duration: setattr(daemon, 'running', False))

    with daemon.bot_locks['busy']:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(daemon.pump_loop).result(timeout=1)

    assert calls == {'busy': [], 'idle': [0.01]}


def test_leave_waits_for_action_before_disconnecting(monkeypatch, fake_bots):
    started = threading.Event()
    finish = threading.Event()
    disconnected = threading.Event()
    order = []

    def slow_action(bot, get):
        started.set()
        assert finish.wait(timeout=2)
        # Exercise level tracking before releasing the action lock, too.
        bot.level = 'next.nw'
        order.append('action finished')
        return True

    def disconnect():
        order.append('disconnected')
        disconnected.set()

    fake_bots['busy'].disconnect = disconnect
    monkeypatch.setitem(GameBot.ACTIONS, 'slow', SimpleNamespace(run=slow_action))
    with ThreadPoolExecutor(max_workers=2) as pool:
        action = pool.submit(request, 'cmd=slow', name='busy')
        try:
            assert started.wait(timeout=1)
            leave = pool.submit(request, '', '/leave', name='busy')
            assert not disconnected.wait(timeout=0.1)
            assert not leave.done()
            # Waiting for /leave must leave the registry available to others.
            assert request('', '/state', name='idle')[0] == 200
        finally:
            finish.set()
        assert action.result(timeout=1)[0] == 200
        assert leave.result(timeout=1) == (200, 'left')

    assert order == ['action finished', 'disconnected']
    assert 'busy' not in daemon.bots
    assert 'busy' not in daemon.bot_locks
    assert 'busy' not in daemon._bot_last_level


def test_quit_replies_and_forces_disconnect_during_stuck_action(monkeypatch, fake_bots,
                                                             caplog):
    started = threading.Event()
    shutdown = threading.Event()
    disconnected = threading.Event()

    def stuck_action(bot, get):
        started.set()
        time.sleep(2)
        bot.level = 'next.nw'
        return True

    def disconnect():
        assert shutdown.wait(timeout=0.5)
        disconnected.set()

    fake_bots['busy'].disconnect = disconnect
    monkeypatch.setitem(GameBot.ACTIONS, 'stuck', SimpleNamespace(run=stuck_action))
    monkeypatch.setattr(daemon, 'DISCONNECT_TIMEOUT', 0.05)
    server = SimpleNamespace(shutdown=shutdown.set)
    sent = []
    original_send = daemon.Handler._send

    def send(handler, obj, code=200):
        if obj == 'bye':
            assert not shutdown.is_set()
            sent.append(obj)
        return original_send(handler, obj, code)

    monkeypatch.setattr(daemon.Handler, '_send', send)
    with ThreadPoolExecutor(max_workers=1) as pool:
        action = pool.submit(request, 'cmd=stuck', name='busy')
        assert started.wait(timeout=1)
        start = time.monotonic()
        assert request('confirm=shutdown', '/quit', server=server) == (200, 'bye')
        assert time.monotonic() - start < 1
        assert sent == ['bye']
        assert disconnected.is_set()
        assert not action.done()
        assert not daemon.bots and not daemon.bot_locks and not daemon._bot_last_level
        assert 'forcing disconnect' in caplog.text
        assert action.result(timeout=3)[0] == 200
    # A forced-out action must not recreate registry metadata when it finishes.
    assert not daemon._bot_last_level


@pytest.fixture
def spawn_bot(monkeypatch, fake_bots):
    bot = SimpleNamespace(name='new', level='new.nw', connect=lambda: True,
                          update=lambda duration: None, disconnect=lambda: None)
    created = []

    def make_bot(name, host, port):
        assert name == bot.name
        created.append(bot)
        return bot

    monkeypatch.setattr(daemon, 'GameBot', make_bot)
    return bot, created


def test_concurrent_spawns_reserve_name_and_return_one_conflict(spawn_bot):
    bot, created = spawn_bot
    started, finish = threading.Event(), threading.Event()

    def connect():
        started.set()
        assert finish.wait(timeout=2)
        return True

    bot.connect = connect
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(request, '', '/spawn', name='new')
        try:
            assert started.wait(timeout=1)
            assert request('', '/spawn', name='new') == (409, 'spawn in progress')
            assert request('', '/state', name='new')[0] == 404
        finally:
            finish.set()
        assert first.result(timeout=1) == (200, {'name': 'new'})
    assert created == [bot]
    assert daemon.bots['new'] is bot
    assert 'new' in daemon.bot_locks
    assert not daemon.pending
    assert request('', '/spawn', name='new') == (409, 'bot already exists')


def test_state_stays_responsive_during_another_bots_slow_connect(spawn_bot):
    bot, _ = spawn_bot
    started, finish = threading.Event(), threading.Event()

    def connect():
        started.set()
        assert finish.wait(timeout=2)
        return True

    bot.connect = connect
    with ThreadPoolExecutor(max_workers=1) as pool:
        spawn = pool.submit(request, '', '/spawn', name='new')
        try:
            assert started.wait(timeout=1)
            start = time.monotonic()
            assert request('', '/state', name='idle') == (200, {'name': 'idle'})
            assert time.monotonic() - start < 0.2
            assert not spawn.done()
        finally:
            finish.set()
        assert spawn.result(timeout=1)[0] == 200


@pytest.mark.parametrize('failure', ['refused', 'connect exception', 'update exception'])
def test_failed_spawn_releases_reservation_and_disconnects(spawn_bot, failure):
    bot, _ = spawn_bot
    disconnected = []
    bot.disconnect = lambda: disconnected.append(True)

    def fail(*args):
        raise RuntimeError('synthetic spawn failure')

    if failure == 'refused':
        bot.connect = lambda: False
    elif failure == 'connect exception':
        bot.connect = fail
    else:
        bot.update = fail

    assert request('', '/spawn', name='new')[0] == 500
    assert disconnected == [True]
    assert 'new' not in daemon.pending
    assert 'new' not in daemon.bots
    assert 'new' not in daemon.bot_locks


def test_spawn_finishing_during_shutdown_disconnects_without_publishing(spawn_bot):
    bot, _ = spawn_bot
    started, finish = threading.Event(), threading.Event()
    disconnected = []
    bot.disconnect = lambda: disconnected.append(True)

    def connect():
        started.set()
        assert finish.wait(timeout=2)
        return True

    bot.connect = connect
    with ThreadPoolExecutor(max_workers=1) as pool:
        spawn = pool.submit(request, '', '/spawn', name='new')
        try:
            assert started.wait(timeout=1)
            with daemon.lock:
                daemon.running = False
        finally:
            finish.set()
        assert spawn.result(timeout=1) == (503, 'daemon is shutting down')
    assert disconnected == [True]
    assert not daemon.pending
    assert 'new' not in daemon.bots
