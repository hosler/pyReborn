"""Offline path planning and GameBot movement integration checks."""

import math
import time
from collections import Counter

import pytest

from game_tester.game_bot import GameBot
from game_tester.pathing import plan_path


def open_cell(x, y):
    return False


def test_open_grid_straight_line():
    assert plan_path((0, 0), (2, 0), open_cell) == [
        (0.5, 0), (1, 0), (1.5, 0), (2, 0)]


def test_open_grid_diagonal():
    assert plan_path((0, 0), (1, 1), open_cell) == [(0.5, 0.5), (1, 1)]


def test_wall_gap_forces_detour():
    def blocked(x, y):
        return not (0 <= x <= 4 and 0 <= y <= 4) or (x == 2 and y != 3)

    path = plan_path((0, 1), (4, 1), blocked)
    assert path is not None
    assert (2, 3) in path
    assert path[-1] == (4, 1)
    assert all(not blocked(*point) for point in path)


def test_enclosed_goal_returns_none():
    def blocked(x, y):
        return not (0 <= x <= 4 and 0 <= y <= 4) or (
            max(abs(x - 2), abs(y - 2)) == 0.5)

    assert plan_path((0, 0), (2, 2), blocked) is None


@pytest.mark.parametrize('offset', [-1.0, 0.001])
def test_unreachable_goal_deadline_returns_quickly(offset):
    calls = []

    def blocked(x, y):
        calls.append((x, y))
        return not (0 <= x < 64 and 0 <= y < 64) or (
            max(abs(x - 32), abs(y - 32)) == 0.5)

    start = time.monotonic()
    assert plan_path((1, 1), (32, 32), blocked, max_nodes=1000000,
                     deadline=start + offset) is None
    assert time.monotonic() - start < 0.2
    if offset < 0:
        assert not calls


def test_deadline_interrupts_search_at_expansion_checkpoint(monkeypatch):
    now = [0.0]
    calls = []
    monkeypatch.setattr('game_tester.pathing.time.monotonic', lambda: now[0])

    def blocked(x, y):
        calls.append((x, y))
        now[0] += 0.001
        return max(abs(x - 32), abs(y - 32)) == 0.5

    assert plan_path((0, 0), (32, 32), blocked, max_nodes=1000000,
                     deadline=0.01) is None
    assert 256 <= len(calls) <= 2049


@pytest.mark.parametrize('goal', [(2, 0), (2, 2)])
def test_collision_cache_probes_each_lattice_node_once(goal):
    calls = Counter()

    def blocked(x, y):
        calls[x, y] += 1
        return not (0 <= x <= 4 and 0 <= y <= 4) or (
            goal == (2, 2) and max(abs(x - 2), abs(y - 2)) == 0.5)

    plan_path((0, 0), goal, blocked)
    assert max(calls.values()) == 1
    assert calls[goal] == 1


def test_collision_cache_is_fresh_for_each_plan():
    blocked_cells = set()
    blocked = lambda x, y: (x, y) in blocked_cells
    assert plan_path((0, 0), (1, 0), blocked) is not None
    blocked_cells.add((1, 0))
    assert plan_path((0, 0), (1, 0), blocked) is None


def test_soft_cost_avoids_weighted_cell():
    path = plan_path((0, 0), (2, 0), open_cell,
                     cost=lambda x, y: 10 if (x, y) == (1, 0) else 0)
    assert path is not None
    assert (1, 0) not in path
    assert path[-1] == (2, 0)


def test_diagonal_does_not_cut_corners():
    def blocked(x, y):
        return (x, y) not in {(0, 0), (0.5, 0.5)}

    assert plan_path((0, 0), (0.5, 0.5), blocked) is None


def test_max_nodes_limits_expansion():
    assert plan_path((0, 0), (1, 0), open_cell, max_nodes=2) is None
    assert plan_path((0, 0), (1, 0), open_cell, max_nodes=3) == [(0.5, 0), (1, 0)]
    calls = []
    assert plan_path((0, 0), (100, 100),
                     lambda x, y: calls.append((x, y)) or False,
                     max_nodes=2) is None
    assert len(calls) <= 17  # Goal check plus eight neighbors per expansion.
    assert plan_path((0, 0), (1, 0), open_cell, max_nodes=0) is None


def test_blocked_goal_and_already_arrived():
    assert plan_path((0, 0), (1, 0), lambda x, y: True) is None
    assert plan_path((0, 0), (0, 0), open_cell) == []


def test_lattice_preserves_negative_world_origin_and_rounds_goal():
    assert plan_path((-64.0625, 64.0625), (-63, 64), open_cell) == [
        (-63.5625, 64.0625), (-63.0625, 64.0625)]


@pytest.mark.parametrize('penalty', [-1, math.inf, math.nan])
def test_invalid_cost_rejected(penalty):
    with pytest.raises(ValueError):
        plan_path((0, 0), (1, 0), open_cell, cost=lambda x, y: penalty)


def walking_bot(monkeypatch, start=(10, 10)):
    bot = GameBot('path_test', 'localhost', 1)
    bot.client.player.x, bot.client.player.y = start
    bot.client._current_level_name = 'test.nw'
    bot.client.tiles = [0] * 4096
    now = [0.0]
    calls = []
    monkeypatch.setattr('game_tester.game_bot.time.time', lambda: now[0])
    monkeypatch.setattr('game_tester.game_bot.time.monotonic', lambda: now[0])
    monkeypatch.setattr(bot, 'update', lambda duration: now.__setitem__(0, now[0] + duration))

    def client_move(dx, dy):
        calls.append((dx, dy))
        bot.client.player.x += dx * 0.25
        bot.client.player.y += dy * 0.25
        return True

    monkeypatch.setattr(bot.client, 'move', client_move)
    return bot, calls, now


def test_walk_follows_path_around_real_tile_wall(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    for y in range(18):
        bot.client.tiles[y * 64 + 15] = -1
    monkeypatch.setattr(bot, '_maybe_follow_link', lambda: None)
    assert bot.walk_to(20, 10, timeout=20)
    assert calls
    assert any(dy > 0 for dx, dy in calls)
    assert any(dy < 0 for dx, dy in calls)
    assert abs(bot.x - 20) < 0.5 and abs(bot.y - 10) < 0.5
    assert not bot.issues


def test_forced_greedy_never_plans(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)

    def unexpected_plan(*args):
        pytest.fail('Greedy walking must skip planning')

    monkeypatch.setattr(bot, '_plan_walk_path', unexpected_plan)
    assert bot.walk_to(12, 10, follow_links=False, pathing=False)
    assert all(call == (1, 0) for call in calls)


def test_failed_plan_uses_greedy_loop(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    monkeypatch.setattr(bot, '_plan_walk_path', lambda *args: None)
    assert bot.walk_to(12, 10, follow_links=False)
    assert calls[0] == (1, 0)


def test_stalls_replan_three_times_then_use_greedy(monkeypatch):
    bot, calls, now = walking_bot(monkeypatch)
    plans = []

    def plan(*args):
        plans.append(args)
        return [(10.5, 10)]

    def stalled_move(dx, dy, follow_links=True):
        calls.append((dx, dy, follow_links))
        now[0] += 0.01
        return False

    monkeypatch.setattr(bot, '_plan_walk_path', plan)
    monkeypatch.setattr(bot, 'move', stalled_move)
    assert not bot.walk_to(12, 10, timeout=2, follow_links=False)
    assert len(plans) == 4
    assert calls[27:29] == [(0, 1, False), (0, 1, False)]
    assert all(not follow for dx, dy, follow in calls)
    assert bot.issues[-1].severity == 'MEDIUM'


@pytest.mark.parametrize('timeout', [0.1, 2.0, 10.0])
def test_walk_shares_timeout_with_initial_plan_and_replans(monkeypatch, timeout):
    bot, _, now = walking_bot(monkeypatch)
    now[0] = 100.0
    plans = []
    walk_deadline = now[0] + timeout

    def plan(x, y, deadline):
        plans.append((now[0], deadline))
        now[0] = deadline
        return [(10.5, 10)]

    def move(*args, **kwargs):
        now[0] += 0.01
        return False

    monkeypatch.setattr(bot, '_plan_walk_path', plan)
    monkeypatch.setattr(bot, 'move', move)
    assert not bot.walk_to(12, 10, timeout=timeout, follow_links=False)
    assert plans[0] == (100.0, 100.0 + min(timeout * 0.4, 2.0))
    for started, deadline in plans[1:]:
        assert started < deadline <= walk_deadline
        assert deadline - started <= min(timeout * 0.1, 0.5) + 1e-9
        assert deadline - started < plans[0][1] - plans[0][0]
    if timeout >= 2:
        assert len(plans) == 4
    assert now[0] < walk_deadline + 0.061


def test_warp_during_planned_walk_returns_false(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    monkeypatch.setattr(bot, '_maybe_follow_link',
                        lambda: setattr(bot.client, '_current_level_name', 'inside.nw'))
    assert not bot.walk_to(12, 10)
    assert len(calls) == 1
    assert bot.action_log[-1].args['warped_to'] == 'inside.nw'


def test_warp_received_while_blocked_returns_false(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    monkeypatch.setattr(bot, 'move', lambda *args, **kwargs: False)
    monkeypatch.setattr(bot, 'update',
                        lambda duration: setattr(bot.client, '_current_level_name', 'inside.nw'))
    assert not bot.walk_to(12, 10)
    assert bot.action_log[-1].args['warped_to'] == 'inside.nw'


def test_replan_can_recover_and_finish(monkeypatch):
    bot, calls, now = walking_bot(monkeypatch)
    real_plan = bot._plan_walk_path
    real_move = bot.move
    plans = []
    attempts = []

    def plan(*args):
        plans.append(args)
        return real_plan(*args)

    def move(*args, **kwargs):
        attempts.append(args)
        if len(attempts) <= 4:
            now[0] += 0.01
            return False
        return real_move(*args, **kwargs)

    monkeypatch.setattr(bot, '_plan_walk_path', plan)
    monkeypatch.setattr(bot, 'move', move)
    assert bot.walk_to(12, 10, follow_links=False)
    assert len(plans) == 2
    assert calls


def test_npc_footprint_blocks_planning_and_move(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    bot.client.npcs[1] = {'x': 12, 'y': 11, 'image': '#c#', 'is_character': True}
    assert bot._path_position_blocked(11, 10)
    assert not bot.move(1, 0, follow_links=False)
    assert not calls
    bot.client.npcs[1]['dontblock'] = True
    assert not bot._path_position_blocked(11, 10)
    assert bot.move(1, 0, follow_links=False)


def test_classic_collision_rectangle_is_checked(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch)
    bot.client.tiles[12 * 64 + 10] = -1
    assert not bot._is_position_blocked(10, 10)
    assert bot._path_position_blocked(10, 10)


def test_player_soft_cost_uses_world_frame(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch, start=(74, 10))
    bot.client.gmap_width = 2
    bot.client.gmap_height = 1
    bot.client.gmap_grid = {(0, 0): 'west.nw', (1, 0): 'east.nw'}
    bot.client._current_level_name = 'east.nw'
    bot.client.players[2] = {'x': 12, 'y': 10, 'level': 'east.nw'}
    captured = {}

    def capture(start, goal, blocked, cost=None, deadline=None):
        captured['start'] = start
        captured['cost'] = cost
        captured['deadline'] = deadline
        return []

    monkeypatch.setattr('game_tester.game_bot.plan_path', capture)
    bot._plan_walk_path(80, 10, deadline=42.0)
    assert captured['start'] == (74, 10)
    assert captured['deadline'] == 42.0
    assert captured['cost'](76, 10) > 0
    assert captured['cost'](12, 10) == 0


def test_world_player_coordinates_override_local_fallback(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch)
    bot.client.players[2] = {'x': 12, 'y': 10, 'world_x': 76, 'world_y': 10}

    def capture(start, goal, blocked, cost=None, deadline=None):
        assert cost(76, 10) > 0
        assert cost(12, 10) == 0
        return []

    monkeypatch.setattr('game_tester.game_bot.plan_path', capture)
    bot._plan_walk_path(20, 10)


def test_planner_rejects_missing_gmap_segments(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch)
    bot.client.gmap_width = 2
    bot.client.gmap_height = 1
    bot.client.gmap_grid = {(0, 0): 'test.nw'}
    bot.client.levels['test.nw'] = bot.client.tiles
    assert bot._path_position_blocked(70, 10)
