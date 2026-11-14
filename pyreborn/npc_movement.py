"""Timed server NPC movement queues."""

import math

from reborn_protocol.coords import segment_origin

from .npc_handler import npc_cell

from .attachments import update_attachments
from .gs1_client.objects import _write_npc_attr


def _position(npc, x, y):
    _write_npc_attr(npc, 'x', x)
    _write_npc_attr(npc, 'y', y)


def queue_moves(client, info):
    npc = client.npcs.get(info['npc_id'])
    if npc is None or not info['records']:
        return
    now = client.clock.sim_now()
    queue = npc.setdefault('_move_queue', [])
    was_empty = not queue
    for record in info['records']:
        move = dict(record, remaining=record['duration_ms'] / 1000.0)
        # FourPlay/quattroplay/src/TClient.cpp:5217-5229: CACHE, absolute.
        absolute = bool(move['options'])
        if not absolute:
            move['x'] = npc.get('x', 0) + sum(m['dx'] for m in queue)
            move['y'] = npc.get('y', 0) + sum(m['dy'] for m in queue)
        # FourPlay/quattroplay/src/TServerNPC.cpp:624-730.
        if len(queue) >= 100:
            queue.clear()
            _position(npc, move['x'], move['y'])
            was_empty = True
        elif not absolute and queue:
            distance = abs(move['x'] - npc.get('x', 0)) + abs(move['y'] - npc.get('y', 0))
            total = move['remaining'] + sum(m['remaining'] for m in queue)
            if distance > 10 and total > 0:
                factor = move['remaining'] / total
                for pending in queue:
                    pending['remaining'] *= factor
                move['remaining'] *= factor
        queue.append(move)
    if was_empty:
        # PLO_MOVE/MOVE2 positions are local to the NPC's cell, which a
        # move never changes (TClient.cpp:5202-5230).
        cell = npc_cell(client.gmap_grid, npc)
        ox, oy = segment_origin(*cell) if cell is not None else (0, 0)
        npc.setdefault('world_x', npc.get('x', 0) + ox)
        npc.setdefault('world_y', npc.get('y', 0) + oy)
        _position(npc, queue[0]['x'], queue[0]['y'])
        npc['_move_clock'] = now
        client._mark_npc_pos_snap(npc)
    update_attachments(client)


def tick_moves(client, now=None):
    now = client.clock.sim_now() if now is None else now
    moved = False
    for npc in list(client.npcs.values()):
        queue = npc.get('_move_queue')
        if not queue:
            continue
        elapsed = now - npc.get('_move_clock', now)
        steps = max(0, math.floor((elapsed + 1e-9) / .05))
        if not steps:
            continue
        npc['_move_clock'] += steps * .05
        # FourPlay/quattroplay/src/TServerNPC.cpp:1630-1664,1753-1775.
        for _ in range(steps):
            if not queue:
                break
            move = queue[0]
            if not move.get('started'):
                _position(npc, move['x'], move['y'])
                move['started'] = True
            count = max(1, math.floor(move['remaining'] / .05 + 1e-9))
            dx, dy = move['dx'] / count, move['dy'] / count
            _position(npc, npc['x'] + dx, npc['y'] + dy)
            move['dx'] -= dx
            move['dy'] -= dy
            move['remaining'] -= .05
            if move['remaining'] <= 1e-9:
                queue.pop(0)
            moved = True
    if moved:
        update_attachments(client)
