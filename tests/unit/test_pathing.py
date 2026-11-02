"""Offline path planning and GameBot movement integration checks."""

import math
import time
from collections import Counter

import pytest

from game_tester.game_bot import GameBot
from game_tester.pathing import UNREACHABLE, plan_path
from reborn_protocol.coords import segment_at


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


def test_enclosed_goal_reports_exhausted_search():
    def blocked(x, y):
        return not (0 <= x <= 4 and 0 <= y <= 4) or (
            max(abs(x - 2), abs(y - 2)) == 0.5)

    assert plan_path((0, 0), (2, 2), blocked) is UNREACHABLE


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

    assert plan_path((0, 0), (0.5, 0.5), blocked) is UNREACHABLE


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


def test_lattice_snaps_negative_world_origin_and_rounds_goal():
    assert plan_path((-64.0625, 64.0625), (-63, 64), open_cell) == [
        (-64, 64), (-63.5, 64), (-63, 64)]


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
    assert bot._is_position_blocked(10, 10)
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


def test_start_snap_chooses_nearest_clear_node():
    def blocked(x, y):
        return (x, y) == (10, 10)

    path = plan_path((10.2, 10.2), (12, 10), blocked)
    assert path[0] in {(10.5, 10), (10, 10.5)}
    assert all(not blocked(*point) for point in path)


def test_offset_start_moves_to_snap_before_following_path(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch, start=(10.2, 10.2))
    assert bot._plan_walk_path(12, 10)[0] == (10, 10)
    assert bot.walk_to(12, 10, follow_links=False)
    assert calls[0] == pytest.approx((-0.8, -0.8))


def test_final_approach_reaches_non_lattice_goal(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch, start=(10.2, 10.2))
    goal = (12.13, 10.18)
    assert bot.walk_to(*goal, follow_links=False, tolerance=0.01)
    assert (bot.x, bot.y) == pytest.approx(goal)
    assert any(0 < abs(dx) < 1 or 0 < abs(dy) < 1 for dx, dy in calls)
    assert bot.action_log[-1].result is True


@pytest.mark.parametrize('y,blocked', [(10, False), (10.2, True), (10.5, True)])
def test_wall_row_uses_full_half_open_feet_rectangle(monkeypatch, y, blocked):
    bot, _, _ = walking_bot(monkeypatch)
    bot.client.tiles[13 * 64:14 * 64] = [-1] * 64
    assert bot._is_position_blocked(10, y) is blocked
    assert bot._path_position_blocked(10, y) is blocked


def test_offset_start_escapes_wall_overlap_via_snap(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch, start=(11.8, 10.2))
    bot.client.tiles[13 * 64:14 * 64] = [-1] * 64
    path = bot._plan_walk_path(10, 10)
    assert path[0] == (12, 10)
    assert all(not bot._is_position_blocked(*point) for point in path)
    assert bot.walk_to(10, 10, follow_links=False)
    assert calls[0] == pytest.approx((0.8, -0.8))
    assert bot.y == 10


def test_move_cannot_put_feet_inside_wall_row(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch, start=(10, 14))
    bot.client.tiles[17 * 64:18 * 64] = [-1] * 64
    assert not bot.move(0, 1, follow_links=False)
    assert calls == []
    assert bot.move(0, -1, follow_links=False)


def test_arrival_on_last_tick_and_tolerance_boundary_is_success(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch)
    assert bot.walk_to(10.75, 10, timeout=0.05, follow_links=False)
    assert bot.x == 10.25
    assert bot.action_log[-1].result is True


def gmap_walking_bot(monkeypatch, start):
    bot, calls, now = walking_bot(monkeypatch, start=start)
    c = bot.client
    c.gmap_width = c.gmap_height = 3
    c.gmap_name = 'test.gmap'
    c.gmap_grid = {(gx, gy): f'segment_{gx}_{gy}.nw'
                   for gx in range(3) for gy in range(3)}
    c.levels = {name: [0] * 4096 for name in c.gmap_grid.values()}
    c._current_level_name = c.gmap_grid[segment_at(*start)]
    c.tiles = c.levels[c._current_level_name]
    original_move = c.move

    def move(dx, dy):
        result = original_move(dx, dy)
        c._current_level_name = c.gmap_grid[segment_at(c.x, c.y)]
        c.tiles = c.levels[c._current_level_name]
        return result

    monkeypatch.setattr(c, 'move', move)
    return bot, calls, now


@pytest.mark.parametrize('pathing', [True, False])
@pytest.mark.parametrize('start,goal', [((63.8, 97.5), (70, 100)),
                                       ((64, 97.5), (62, 110)),
                                       ((94, 63.8), (94, 70))])
def test_gmap_seam_continues_in_both_walkers(monkeypatch, pathing, start, goal):
    bot, _, _ = gmap_walking_bot(monkeypatch, start)
    old_level = bot.level
    assert bot.walk_to(*goal, timeout=20, pathing=pathing)
    assert bot.level != old_level
    assert math.dist((bot.x, bot.y), goal) <= 0.5
    assert 'warped_to' not in bot.action_log[-1].args


def test_planner_reads_neighbour_board_across_seam(monkeypatch):
    bot, _, _ = gmap_walking_bot(monkeypatch, (60, 97.5))
    east = bot.client.levels['segment_1_1.nw']
    for y in range(30, 41):
        east[y * 64 + 2] = -1
    path = bot._plan_walk_path(70, 97.5)
    assert path is not None
    assert any(y < 30 + 64 - 3 or y >= 41 + 64 - 1 for x, y in path)
    assert bot.walk_to(70, 97.5, timeout=20)


@pytest.mark.parametrize('pathing', [True, False])
@pytest.mark.parametrize('follow_links', [True, False])
def test_gmap_identity_change_ends_walk(monkeypatch, pathing, follow_links):
    bot, calls, _ = gmap_walking_bot(monkeypatch, (60, 97.5))
    monkeypatch.setattr(bot, '_update_swimming_state',
                        lambda: setattr(bot.client, 'gmap_name', 'other.gmap'))
    assert not bot.walk_to(70, 100, pathing=pathing, follow_links=follow_links)
    assert len(calls) == 1
    assert 'warped_to' in bot.action_log[-1].args


@pytest.mark.parametrize('pathing', [True, False])
def test_interior_warp_with_cached_gmap_ends_walk(monkeypatch, pathing):
    bot, calls, _ = gmap_walking_bot(monkeypatch, (60, 97.5))
    monkeypatch.setattr(bot, '_maybe_follow_link',
                        lambda: setattr(bot.client, '_current_level_name', 'inside.nw'))
    assert not bot.walk_to(70, 100, pathing=pathing)
    assert len(calls) == 1


def add_door(bot, level='test.nw', x=15, y=10):
    bot.client.links[level] = [{'x': x, 'y': y, 'width': 2, 'height': 2,
                                'dest_level': 'inside.nw'}]


def test_walk_routes_around_link_footprint_and_triggers(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    add_door(bot)
    visited = []
    original_move = bot.client.move

    def move(dx, dy):
        result = original_move(dx, dy)
        visited.append((bot.x, bot.y))
        return result

    monkeypatch.setattr(bot.client, 'move', move)
    assert bot.walk_to(22, 10, timeout=20)
    assert any(dy for dx, dy in calls)
    assert all(not bot._walk_link_blocked(x, y, 22, 10) for x, y in visited)
    assert bot.level == 'test.nw'


def test_greedy_fallback_also_avoids_links(monkeypatch):
    bot, calls, _ = walking_bot(monkeypatch)
    add_door(bot)
    monkeypatch.setattr(bot, '_plan_walk_path', lambda *args: None)
    original_move = bot.move

    def move(dx, dy, **kwargs):
        assert not bot._walk_link_blocked(bot.x + dx * 0.25, bot.y + dy * 0.25, 22, 10)
        return original_move(dx, dy, **kwargs)

    monkeypatch.setattr(bot, 'move', move)
    bot.walk_to(22, 10, timeout=2)
    assert calls
    assert bot.level == 'test.nw'


def test_goal_just_outside_link_does_not_allow_crossing(monkeypatch):
    bot, _, _ = walking_bot(monkeypatch)
    add_door(bot)
    assert not bot._walk_link_blocked(14, 10, 16.9, 11.9)
    assert bot._walk_link_blocked(14, 10, 17, 11)
    assert bot._walk_link_blocked(14, 10, 16, 12)


@pytest.mark.parametrize('follow_links', [True, False])
def test_targeted_link_preserves_follow_links(monkeypatch, follow_links):
    bot, _, _ = walking_bot(monkeypatch)
    add_door(bot)
    followed = []

    def follow():
        followed.append(True)
        if bot.x >= 12:
            bot.client._current_level_name = 'inside.nw'

    monkeypatch.setattr(bot, '_maybe_follow_link', follow)
    result = bot.walk_to(16, 11, follow_links=follow_links)
    assert result is (not follow_links)
    assert bool(followed) is follow_links


def test_world_link_coordinates_and_neighbour_seam_link(monkeypatch):
    bot, _, _ = gmap_walking_bot(monkeypatch, (60, 97.5))
    add_door(bot, 'segment_1_1.nw', x=10, y=34)
    assert bot._walk_link_blocked(73, 97, 90, 97)
    assert not bot._walk_link_blocked(73, 97, 75, 99)
    bot.client.links['segment_0_1.nw'] = [
        {'x': 63, 'y': 0, 'width': 1, 'height': 64,
         'dest_level': 'segment_1_1.nw'}]
    assert not bot._walk_link_blocked(63.8, 97.5, 70, 100)
    assert bot.walk_to(70, 100, timeout=20)


def enclosed_walking_bot(monkeypatch, corridor=0):
    bot, calls, now = walking_bot(monkeypatch, start=(10.5, 10))
    bot.client.tiles = [-1] * 4096
    # Two disconnected rooms with clear standing positions. With no corridor,
    # every attempted step from the start collides with the surrounding walls.
    for y in (11, 12):
        for x in (*range(11, 13 + corridor), 21, 22):
            bot.client.tiles[y * 64 + x] = 0
    return bot, calls, now


def test_walk_exhausted_search_returns_low_unreachable_after_two_seconds(monkeypatch):
    bot, calls, now = enclosed_walking_bot(monkeypatch)
    assert bot._plan_walk_path(20.5, 10) is UNREACHABLE
    assert not bot.walk_to(20.5, 10, timeout=25, follow_links=False)
    assert 2 <= now[0] <= 2.5
    assert calls == []
    assert [(issue.severity, issue.category) for issue in bot.issues] == [('LOW', 'movement')]
    assert 'target unreachable' in bot.issues[0].description
    assert 'strand' not in bot.issues[0].description
    assert bot.action_log[-1].action == 'walk_to'
    assert bot.action_log[-1].result is False


def test_unreachable_grace_period_resets_after_greedy_progress(monkeypatch):
    bot, calls, now = enclosed_walking_bot(monkeypatch, corridor=6)
    assert bot._plan_walk_path(20.5, 10) is UNREACHABLE
    assert not bot.walk_to(20.5, 10, timeout=25, follow_links=False)
    assert calls
    assert bot.x == 16.5
    assert 3.1 <= now[0] <= 3.7  # 1.2 seconds of progress plus recovery.
    assert bot.issues[-1].severity == 'LOW'
    assert 'target unreachable' in bot.issues[-1].description


def test_unreachable_recovery_does_not_count_oscillation_as_progress(monkeypatch):
    bot, _, now = walking_bot(monkeypatch)
    monkeypatch.setattr(bot, '_plan_walk_path', lambda *args: UNREACHABLE)
    attempts = []

    def move(dx, dy, **kwargs):
        attempts.append((dx, dy))
        now[0] += 0.05
        bot.client.player.x = 10.25 if len(attempts) % 2 else 10
        return True

    monkeypatch.setattr(bot, 'move', move)
    assert not bot.walk_to(20, 10, timeout=25, follow_links=False)
    assert 2 <= now[0] <= 2.5
    assert 'target unreachable' in bot.issues[-1].description


@pytest.mark.parametrize('cutoff', ['deadline', 'max_nodes'])
def test_planner_cutoff_still_uses_full_greedy_timeout(monkeypatch, cutoff):
    bot, _, now = walking_bot(monkeypatch)

    def plan(*args):
        kwargs = ({'deadline': now[0] - 1} if cutoff == 'deadline'
                  else {'max_nodes': 1})
        result = plan_path((10, 10), (20, 10), open_cell, **kwargs)
        assert result is None
        return result

    def move(*args, **kwargs):
        now[0] += 0.05
        return False

    monkeypatch.setattr(bot, '_plan_walk_path', plan)
    monkeypatch.setattr(bot, 'move', move)
    assert not bot.walk_to(20, 10, timeout=4, follow_links=False)
    assert 4 <= now[0] <= 4.3
    assert bot.issues[-1].severity == 'MEDIUM'
    assert 'movement strand' in bot.issues[-1].description


def test_exhaustion_on_last_allowed_node_is_unreachable():
    assert plan_path((0, 0), (2, 0),
                     lambda x, y: (x, y) not in {(0, 0), (2, 0)},
                     max_nodes=1) is UNREACHABLE


def test_deadline_during_final_expansion_is_a_cutoff(monkeypatch):
    now = [0.0]
    monkeypatch.setattr('game_tester.pathing.time.monotonic', lambda: now[0])

    def blocked(x, y):
        if (x, y) not in {(0, 0), (2, 0)}:
            now[0] = 2.0
            return True
        return False

    assert plan_path((0, 0), (2, 0), blocked, deadline=1.0) is None


def test_replan_exhaustion_also_enables_unreachable_recovery(monkeypatch):
    bot, _, now = walking_bot(monkeypatch)
    plans = iter([[(10.5, 10)], UNREACHABLE])
    monkeypatch.setattr(bot, '_plan_walk_path', lambda *args: next(plans))
    monkeypatch.setattr(bot, 'move', lambda *args, **kwargs: False)
    assert not bot.walk_to(20, 10, timeout=25, follow_links=False)
    assert 2.2 <= now[0] <= 2.7
    assert 'target unreachable' in bot.issues[-1].description
