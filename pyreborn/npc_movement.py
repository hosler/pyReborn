"""Timed NPC movement queues: server moves (PLO_MOVE/MOVE2) and script `move`.

Both go through `add_npc_move`, the reference's `TServerNPC::addNPCMove`
(Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:619-730), and
`tick_moves` plays the queue like `TServerNPC::doNPCMove` (:1628-1835), once
per simulation tick, so rendering, blocking and touch follow a script move
exactly as they follow a server one.
"""

import math

from reborn_protocol.coords import segment_origin
from reborn_protocol.gs1.values import to_num

from .npc_handler import npc_cell

from .attachments import update_attachments
from .gs1_client.frame import _write_npc_attr

#: `flags` of a move (TServerNPC.cpp:668-713 for the mode, :1647-1735 for the
#: rest). A server move always carries MODE_FAR_ONLY (TClient.cpp:5229).
MODE_MASK = 3
MODE_ALL = 0          # squeeze every pending duration into the new total
MODE_FAR_ONLY = 1     # squeeze only when the queue spans more than 10 tiles
BLOCK_WALL = 0x04
FINISHED_EVENT = 0x08
FACE_MOVE = 0x10
BLOCK_WATER = 0x20
DEFAULT_ANI = 0x40

_STEP = .05           # npcMoveTick(): 1 / 20 (TServerNPC.cpp:120-123)
_EPS = 1e-4           # DOUBLE_00402440 (TInitStatics.cpp:1266)


def _position(npc, x, y):
    _write_npc_attr(npc, 'x', x)
    _write_npc_attr(npc, 'y', y)


def _squeeze(queue, move):
    """Scale the pending durations and the new move's so the whole queue
    lasts the new move's duration (TServerNPC.cpp:660-696)."""
    total = move['remaining'] + sum(m['remaining'] for m in queue)
    if total > 0:
        factor = move['remaining'] / total
        for pending in queue:
            pending['remaining'] *= factor
        move['remaining'] *= factor


def add_npc_move(client, npc, dx, dy, duration, flags, *, absolute=False,
                 x=0.0, y=0.0, record=None, start_now=False):
    """`addNPCMove(dx, dy, duration, flags, x, y, absolute)`: append one move.

    A relative move (every script `move`) starts where the queued moves end:
    the NPC's current local position plus their remaining deltas. An absolute
    one (a server move with its easing byte set) keeps (x, y). Either way a
    queue of 100 moves is dropped and the NPC put at the start position
    first. `start_now` positions the NPC at the move's start at once and marks
    the render position as a jump (the wire path); a script move starts where
    the NPC already is, and the first tick positions it as the reference does.
    """
    queue = npc.setdefault('_move_queue', [])
    move = dict(record or {}, dx=dx, dy=dy, remaining=duration, flags=flags)
    if not absolute:
        x = npc.get('x', 0) + sum(m['dx'] for m in queue)
        y = npc.get('y', 0) + sum(m['dy'] for m in queue)
    move['x'], move['y'] = x, y
    if len(queue) >= 100:
        queue.clear()
        _position(npc, x, y)
    elif not absolute and queue:
        mode = flags & MODE_MASK
        if mode == MODE_ALL:
            _squeeze(queue, move)
        elif mode == MODE_FAR_ONLY:
            distance = abs(x - npc.get('x', 0)) + abs(y - npc.get('y', 0))
            if distance > 10:
                _squeeze(queue, move)
    was_empty = not queue
    queue.append(move)
    if was_empty:
        # Server moves are local to the NPC's cell, which a move never
        # changes (TClient.cpp:5202-5230).
        cell = npc_cell(client.gmap_grid, npc)
        ox, oy = segment_origin(*cell) if cell is not None else (0, 0)
        npc.setdefault('world_x', npc.get('x', 0) + ox)
        npc.setdefault('world_y', npc.get('y', 0) + oy)
        if start_now:
            _position(npc, queue[0]['x'], queue[0]['y'])
        npc['_move_clock'] = client.clock.sim_now()
        if start_now:
            client._mark_npc_pos_snap(npc)
    update_attachments(client)


def queue_moves(client, info):
    npc = client.npcs.get(info['npc_id'])
    if npc is None or not info['records']:
        return
    for record in info['records']:
        # FourPlay/quattroplay/src/TClient.cpp:5217-5229: the easing byte is
        # the `absolute` argument, the flags are the constant 1.
        absolute = bool(record['options'])
        add_npc_move(client, npc, record['dx'], record['dy'],
                     record['duration_ms'] / 1000.0, MODE_FAR_ONLY,
                     absolute=absolute, x=record['x'], y=record['y'],
                     record=record, start_now=True)


def _facing(npc, step_x, step_y):
    """`setdir` of a FACE_MOVE step (TServerNPC.cpp:1670-1679)."""
    if abs(step_x) <= abs(step_y):
        npc['direction'] = 0 if step_y < 0 else 2
    else:
        npc['direction'] = 1 if step_x < 0 else 3


def _blocked(client, npc_id, npc, move, step_x, step_y):
    """The wall and water tests of a BLOCK_WALL / BLOCK_WATER move, at the
    point the NPC's leading edge reaches after this step
    (TServerNPC.cpp:1682-1749)."""
    rt = client.gs1_runtime
    if rt is None:
        return False
    x = to_num(npc.get('world_x', npc.get('x', 0))) + step_x
    y = to_num(npc.get('world_y', npc.get('y', 0))) + step_y
    direction = int(to_num(npc.get('direction', 2)))
    if rt.npc_character_mode(npc):
        edge = {0: (1.5, 1.0), 1: (0.5, 1.5), 2: (1.5, 3.0), 3: (3.0, 1.5)}
    else:
        w, h = rt.npc_tile_size(npc_id, npc)
        edge = {0: (w * .5, 0.0), 1: (0.0, h * .5), 2: (w * .5, h),
                3: (w, h * .5)}
    ex, ey = edge.get(direction, (0.0, 0.0))
    x, y = x + ex, y + ey
    flags = move['flags']
    if flags & BLOCK_WALL and rt.is_wall(x, y, exclude_npc=npc_id):
        return True
    return bool(flags & BLOCK_WATER and rt.is_water_at(x, y))


def _default_animation(client, rt, npc, moved_x, moved_y):
    """The DEFAULT_ANI leg of a character NPC's step: swim on water, else
    idle / walkslow / walk by the distance this step covered; a head image
    named `bomy_*` picks the bomy_ set instead
    (TServerNPC.cpp:1781-1832, defanis TInitStatics.cpp:1459-1491)."""
    bomy = str(npc.get('head_image', '')).startswith('bomy_')
    if rt.is_water_at(to_num(npc.get('world_x', npc.get('x', 0))) + 1.5,
                      to_num(npc.get('world_y', npc.get('y', 0))) + 2.0):
        name = 'bomy_kick' if bomy else 'swim'
    elif not npc.get('_move_queue') or (abs(moved_x) < _EPS
                                       and abs(moved_y) < _EPS):
        name = 'bomy_idle' if bomy else 'idle'
    elif abs(moved_x) < .5 and abs(moved_y) < .5:
        name = 'bomy_walk' if bomy else 'walkslow'
    else:
        name = 'bomy_walk' if bomy else 'walk'
    npc['gani'] = name + ','


def _step_move(client, npc_id, npc):
    """One `doNPCMove`. Returns True when the NPC moved."""
    queue = npc['_move_queue']
    move = queue[0]
    if not move.get('started'):
        _position(npc, move['x'], move['y'])
        move['started'] = True
    flags = move['flags']
    old_x, old_y = to_num(npc['x']), to_num(npc['y'])
    finished = False
    steps = math.floor(move['remaining'] / _STEP + _EPS)
    if steps < 1:
        step_x, step_y = move['dx'], move['dy']
        finished = bool(flags & FINISHED_EVENT)
        queue.pop(0)
    else:
        step_x, step_y = move['dx'] / steps, move['dy'] / steps
        if flags & FACE_MOVE:
            _facing(npc, step_x, step_y)
        if flags & (BLOCK_WALL | BLOCK_WATER) and _blocked(
                client, npc_id, npc, move, step_x, step_y):
            finished = bool(flags & FINISHED_EVENT)
            npc.pop('_move_queue', None)
            step_x = step_y = 0.0
        else:
            move['dx'] -= step_x
            move['dy'] -= step_y
            move['remaining'] -= _STEP
            if move['remaining'] < _EPS:
                step_x += move['dx']
                step_y += move['dy']
                finished = bool(flags & FINISHED_EVENT)
                queue.pop(0)
    if step_x or step_y:
        _position(npc, npc['x'] + step_x, npc['y'] + step_y)
    rt = client.gs1_runtime
    if finished and rt is not None:
        rt.trigger_npc_event(npc_id, 'movementfinished')
    rt = client.gs1_runtime
    if flags & DEFAULT_ANI and rt is not None and rt.npc_character_mode(npc):
        _default_animation(client, rt, npc, to_num(npc['x']) - old_x,
                           to_num(npc['y']) - old_y)
    return True


def tick_moves(client, now=None):
    now = client.clock.sim_now() if now is None else now
    moved = False
    for npc_id, npc in list(client.npcs.items()):
        if not npc.get('_move_queue'):
            continue
        elapsed = now - npc.get('_move_clock', now)
        steps = max(0, math.floor((elapsed + 1e-9) / _STEP))
        if not steps:
            continue
        npc['_move_clock'] += steps * _STEP
        for _ in range(steps):
            if not npc.get('_move_queue'):
                break
            moved = _step_move(client, npc_id, npc) or moved
    if moved:
        update_attachments(client)
