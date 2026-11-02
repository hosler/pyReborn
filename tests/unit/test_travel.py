"""Offline travel execution using stubbed walking and real collision probes."""

import pytest

from game_tester.game_bot import GameBot
from game_tester.world_graph import WorldGraph


def add_link(graph, src, dest, x=10, y=10, width=2, height=1):
    link = dict(x=x, y=y, width=width, height=height, dest_level=dest,
                dest_x=30, dest_y=30)
    graph.add_observed(src, [link])
    return link


def offline_bot(monkeypatch):
    bot = GameBot('travel_test', 'localhost', 1)
    bot.client._current_level_name = 'a.nw'
    bot.client.player.x = bot.client.player.y = 10
    bot.client.tiles = [0] * 4096
    now = [0.0]
    monkeypatch.setattr('game_tester.game_bot.time.monotonic', lambda: now[0])
    monkeypatch.setattr(bot, 'update', lambda dt: now.__setitem__(0, now[0] + dt))
    monkeypatch.setattr(bot, 'warp_to', lambda *a, **k: pytest.fail('travel must walk'))
    return bot, now


@pytest.mark.parametrize('unexpected', [False, True])
def test_travel_hop_loop_replans_and_finishes_coordinates(monkeypatch, unexpected):
    bot, _ = offline_bot(monkeypatch)
    graph = WorldGraph()
    add_link(graph, 'a.nw', 'b.nw')
    add_link(graph, 'b.nw', 'c.nw')
    # The detour, if taken, is learned only upon arrival.
    walks, moves = [], []

    def walk(x, y, **kwargs):
        walks.append((bot.level, x, y, kwargs))
        bot.client.player.x, bot.client.player.y = x, y
        return True

    def move(dx, dy, **kwargs):
        moves.append((bot.level, kwargs))
        bot.client._current_level_name = (
            'detour.nw' if unexpected and bot.level == 'a.nw' else
            'b.nw' if bot.level == 'a.nw' else 'c.nw')
        # Merging new observations is required for both normal and detour paths.
        bot.client.links[bot.level] = [add_link(WorldGraph(), bot.level, 'c.nw')]
        return True

    monkeypatch.setattr(bot, 'walk_to', walk)
    monkeypatch.setattr(bot, 'move', move)
    assert bot.travel_to('C.NW', 7, 8, graph=graph)
    assert bot.level == 'c.nw'
    assert [src for src, _ in moves] == ['a.nw', 'detour.nw' if unexpected else 'b.nw']
    assert all(kwargs['follow_links'] for _, kwargs in moves)
    assert walks[-1][1:3] == (7, 8)
    assert not bot.issues
    assert not hasattr(bot, '_travel_link_goal')


def test_travel_observed_only_and_walk_returning_false_on_warp(monkeypatch):
    bot, _ = offline_bot(monkeypatch)
    bot.client.links['a.nw'] = [add_link(WorldGraph(), 'a.nw', 'b.nw')]

    def walk(*args, **kwargs):
        bot.client._current_level_name = 'b.nw'
        return False

    monkeypatch.setattr(bot, 'walk_to', walk)
    monkeypatch.setattr(bot, 'move', lambda *a, **k: pytest.fail('already warped'))
    assert bot.travel_to('b.nw')


@pytest.mark.parametrize('mode', ['no_route', 'timeout', 'no_warp', 'replans'])
def test_travel_failures_record_low_issue(monkeypatch, mode):
    bot, now = offline_bot(monkeypatch)
    graph = WorldGraph()
    for src, dest in [('a.nw', 'b.nw'), ('detour.nw', 'b.nw')]:
        add_link(graph, src, dest)
    calls = []

    def walk(*args, **kwargs):
        calls.append(bot.level)
        if mode == 'timeout':
            now[0] += kwargs['timeout']
        if mode == 'replans':
            bot.client._current_level_name = 'detour.nw' if bot.level == 'a.nw' else 'a.nw'
        return True

    monkeypatch.setattr(bot, 'walk_to', walk)
    monkeypatch.setattr(bot, 'move', lambda *a, **k: False)
    assert not bot.travel_to('missing.nw' if mode == 'no_route' else 'b.nw', graph=graph)
    assert bot.issues[-1].severity == 'LOW'
    assert 'travel unreachable' in bot.issues[-1].description
    if mode == 'replans':
        assert len(calls) == 4
    if mode == 'timeout':
        assert now[0] == 60


def test_solid_door_approach_uses_standable_point_and_normal_blocked_move(monkeypatch):
    bot, _ = offline_bot(monkeypatch)
    graph = WorldGraph()
    link = add_link(graph, 'a.nw', 'b.nw', x=12, y=10, width=1, height=2)
    bot.client.links['a.nw'] = [link]
    bot.client.player.x, bot.client.player.y = 9.5, 10
    for y in range(64):
        bot.client.tiles[y * 64 + 12:(y + 1) * 64] = [-1] * 52
    approaches, warps = [], []

    def walk(x, y, **kwargs):
        assert not bot._path_position_blocked(x, y)
        assert not bot._walk_link_blocked(x, y, x, y)
        approaches.append((x, y))
        bot.client.player.x, bot.client.player.y = x, y
        return True

    def use_link(observed):
        warps.append(observed)
        bot.client._current_level_name = 'b.nw'
        return True

    monkeypatch.setattr(bot, 'walk_to', walk)
    monkeypatch.setattr(bot, 'use_link', use_link)
    assert bot.travel_to('b.nw', graph=graph)
    assert approaches and warps == [link]
    assert bot.action_log[0].args['blocked'] is True


@pytest.mark.parametrize('dest, expected', [('east.nw', (128, 100)),
                                           ('west.nw', (63.5, 100)),
                                           ('north.nw', (100, 63.5)),
                                           ('south.nw', (100, 128))])
def test_travel_gmap_seam_is_world_movement(monkeypatch, dest, expected):
    bot, _ = offline_bot(monkeypatch)
    c = bot.client
    c.gmap_width, c.gmap_height, c.gmap_name = 3, 3, 'test.gmap'
    c.gmap_grid = {(0, 1): 'west.nw', (1, 1): 'a.nw', (2, 1): 'east.nw',
                   (1, 0): 'north.nw', (1, 2): 'south.nw'}
    c.levels = {name: [0] * 4096 for name in c.gmap_grid.values()}
    c.player.x, c.player.y = 100, 100
    moves = []

    def client_move(dx, dy):
        moves.append((dx, dy))
        c.player.x += dx * .25
        c.player.y += dy * .25
        return True

    monkeypatch.setattr(c, 'move', client_move)
    monkeypatch.setattr(bot, 'use_link', lambda *a: pytest.fail('seam must not warp'))
    assert bot.travel_to(dest)
    assert moves
    assert (bot.x, bot.y) == expected
    assert bot.level == dest


def test_return_trip_walks_away_from_arrival_before_approaching(monkeypatch):
    bot, _ = offline_bot(monkeypatch)
    bot._link_arrival = (10, 10)
    bot._was_on_link = True
    graph = WorldGraph()
    add_link(graph, 'a.nw', 'b.nw')
    walks = []

    def walk(x, y, **kwargs):
        walks.append(kwargs)
        bot.client.player.x, bot.client.player.y = x, y
        if kwargs['follow_links']:
            assert not bot._was_on_link
            assert bot._link_arrival is None
            bot.client._current_level_name = 'b.nw'
            return False
        return True

    monkeypatch.setattr(bot, 'walk_to', walk)
    assert bot.travel_to('b.nw', graph=graph)
    assert [kw['follow_links'] for kw in walks] == [False, True]


def test_travel_waits_for_delayed_warp_confirmation(monkeypatch):
    bot, now = offline_bot(monkeypatch)
    graph = WorldGraph()
    add_link(graph, 'a.nw', 'b.nw')
    monkeypatch.setattr(bot, 'walk_to', lambda *a, **kw: True)
    monkeypatch.setattr(bot, 'move', lambda *a, **kw: True)

    def update(dt):
        now[0] += dt
        if now[0] >= 1:
            bot.client._current_level_name = 'b.nw'

    monkeypatch.setattr(bot, 'update', update)
    assert bot.travel_to('b.nw', graph=graph)
    assert 1 <= now[0] < 3


@pytest.mark.parametrize('kwargs', [dict(x=1), dict(y=2), dict(timeout=float('nan')),
                                    dict(x=float('inf'), y=1)])
def test_travel_rejects_bad_coordinates(monkeypatch, kwargs):
    bot, _ = offline_bot(monkeypatch)
    with pytest.raises(ValueError):
        bot.travel_to('b.nw', **kwargs)
