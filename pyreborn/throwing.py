"""Shared flight and landing data for carried objects."""


from reborn_protocol.coords import in_level_bounds, segment_at, segment_origin

from .tiletypes import get_tile_type, type_is_blocking, selection_for
from .liftobjects import LIFT_NAMES, LIFT_OBJECTS, LIFT_SPRITES

TICK = 0.05
THROW_TICKS = 9  # TPlayer.cpp:7831.
INITIAL_HEIGHT = 2.375  # TPlayer.cpp:7827-7829: sprite y=-1.375, ground y=1.
HEIGHT_DROP = 0.2  # TInitStatics.cpp:1167: sprite dy minus ground dy.
DIRECTIONS = ((0, -1), (-1, 0), (0, 1), (1, 0))


def carry_code(sprite):
    # TPlayer.cpp:3221-3236, TServerPlayer.cpp:38-40,1754: decoded wire value.
    return {0x41: 0, 0x42: 200, 0xef: 201}.get(
        sprite, ((sprite + 0x1c) & 0xff) - 0x20)


def carry_object(code):
    """Resolve a decoded carry property through the shared lift tables."""
    for name, sprite, tiles in zip(LIFT_NAMES, LIFT_SPRITES, LIFT_OBJECTS):
        if carry_code(sprite) == code:
            tl, bl, tr, br = tiles
            return name, (tl, tr, bl, br)
    return None


def make_throw(x, y, direction, kind, tiles, owner_id=None):
    dx, dy = DIRECTIONS[direction]
    return {'x': x + 0.5, 'y': y + 1.0, 'z': INITIAL_HEIGHT,
            'z0': INITIAL_HEIGHT, 'dx': dx, 'dy': dy, 'type': kind,
            'tiles': tiles, 'owner_id': owner_id, 'remote': owner_id is not None,
            'ticks': 0, 'elapsed': 0.0, 'dist': 0.0,
            'range': float(THROW_TICKS), 'speed': 1.0 / TICK,
            'segment': segment_at(x, y)}


def remote_throw(client, owner_id):
    """TClient.cpp:3741-3756, TServerPlayer.cpp:1054-1091: launch at owner."""
    owner = client.players.get(owner_id)
    from .carrying import BOMB_CODES
    carried = carry_object(owner.get('carry_sprite', -1)) if owner else None
    if owner and owner.get('carry_sprite', -1) in BOMB_CODES:
        carried = 'bomb', ()
    if carried is None:
        return None
    ox, oy = remote_origin(client, owner)
    x, y = owner.get('world_x'), owner.get('world_y')
    x = owner.get('x', 0) + ox if x is None else x
    y = owner.get('y', 0) + oy if y is None else y
    obj = make_throw(x, y, owner.get('direction', 2), *carried, owner_id=owner_id)
    obj['layer'] = owner.get('layer', 0)
    bomb = owner.pop('_carried_bomb', None)
    if bomb is not None:
        obj['bomb'] = bomb
        bomb['carried_by'] = None
        bomb['in_flight'] = True
    owner['carry_sprite'] = -1
    owner['animation'] = 'idle'
    return obj


def remote_origin(client, player):
    if not getattr(client, 'in_gmap_segment', False):
        return 0, 0
    gx, gy = player.get('gmaplevelx'), player.get('gmaplevely')
    if gx is not None and gy is not None:
        return segment_origin(gx, gy)
    return segment_origin(*segment_at(client.x, client.y))


def landing_type(game, obj):
    # TServerCarry.cpp:220-236,262-265: water uses sprite y; burst uses ground y.
    if game._check_water_at_position(obj['x'] + 1, obj['y'] - obj['z'] + 1):
        return 5
    return 0 if obj.get('type') == 'bush' else 3 if obj.get('type') == 'sign' else 2


def handoff(client, obj):
    # TServerCarry.cpp:133-164: sprite-edge handoff skips that tick's collisions.
    if not getattr(client, 'in_gmap_segment', False):
        return False
    grid = obj.setdefault('segment', segment_at(obj['x'], obj['y']))
    ox, oy = segment_origin(*grid)
    x, y = obj['x'] - ox, obj['y'] - obj['z'] - oy
    dx = -1 if obj['dx'] < 0 and x <= 0 else 1 if obj['dx'] > 0 and x >= 64 else 0
    dy = -1 if obj['dy'] < 0 and y <= 0 else 1 if obj['dy'] > 0 and y >= 64 else 0
    target = grid[0] + dx, grid[1] + dy
    if target != grid and target in client.gmap_grid:
        obj['segment'] = target
        return True
    return False


def report_throw(client):
    from .packets import PacketID, build_throwcarried
    if getattr(client, 'connected', False) and getattr(client, '_authenticated', False):
        client._protocol.send_packet(PacketID.PLI_THROWCARRIED, build_throwcarried())


def throw_damage(hearts):
    # TServerCarry.cpp:202: all carried sprites use the same damage rule.
    return 0.5 if hearts <= 1.0 else 1.0


def throw_hits(x, y, px, py):
    # TServerCarry.cpp:181-184: strict distances from the ground track.
    return abs(x - (px + 0.5)) < 2.0 and abs(y - (py + 1.0)) < 2.0


def point_hits_npc(client, npc, x, y):
    if not npc.get('visible', True):
        return False
    runtime = getattr(getattr(client, 'gs1_host', None), 'rt', None)
    if runtime is not None:
        return runtime.npc_footprint_hit(npc, x, y)
    nx, ny = npc.get('world_x', npc.get('x', 0)), npc.get('world_y', npc.get('y', 0))
    return nx <= x < nx + npc.get('width', 2) and ny <= y < ny + npc.get('height', 2)


def advance_throw(game, obj, dt, remote=False):
    """Advance full ticks, testing walls, then a point NPC probe, then players."""
    client = game.client
    remote = remote or obj.get('remote', False)
    obj['elapsed'] = obj.get('elapsed', 0.0) + max(0.0, dt)
    target = int((obj['elapsed'] + 1e-9) / TICK)
    while obj.get('ticks', 0) < min(obj.get('landing_tick', THROW_TICKS), target):
        obj['ticks'] = obj.get('ticks', 0) + 1
        obj['x'] += obj['dx']
        obj['y'] += obj['dy']
        obj['dist'] = float(obj['ticks'])
        obj['z'] = INITIAL_HEIGHT - HEIGHT_DROP * obj['ticks']
        if handoff(client, obj):
            if obj['ticks'] >= THROW_TICKS:
                obj['landing_tick'] = obj['ticks'] + 1
            continue
        x, y = obj['x'] + 1.0, obj['y'] + 1.0
        if not getattr(client, 'in_gmap_segment', False) and not in_level_bounds(x, y):
            return True
        tile = game._get_tile_at(x, y)
        tile_type = get_tile_type(tile, selection_for(client).active_tilestype())
        blocking = game._is_tile_blocking(tile)
        runtime = getattr(getattr(client, 'gs1_host', None), 'rt', None)
        if runtime is not None:
            overlay = runtime.npc_tile_type(x, y)
            if overlay > 1:
                tile_type = overlay
                blocking = type_is_blocking(tile_type)
        # TServerLevel.cpp:2655-2664: type 20 bypasses throw walls.
        if tile_type != 20 and blocking:
            return True
        if tile_type != 20:
            grid = obj.get('segment', segment_at(client.x, client.y))
            ox, oy = segment_origin(*grid) if getattr(client, 'in_gmap_segment', False) else (0, 0)
            level_name = (client.gmap_grid.get(grid, '') if getattr(client, 'in_gmap_segment', False)
                          else getattr(client, '_current_level_name', ''))
            for cx, cy in getattr(client, 'chests', {}).get(
                    level_name, {}):
                if cx + ox <= x < cx + ox + 2 and cy + oy <= y < cy + oy + 2:
                    return True
            for bomb in getattr(client, 'bombs', {}).get(
                    level_name, {}).values():
                # TServerLevel.cpp:2666-2710: half-open point rectangle.
                if (bomb['x'] + ox + .25 <= x < bomb['x'] + ox + 3
                        and bomb['y'] + oy <= y < bomb['y'] + oy + 2):
                    return True
        for npc_id, npc in (getattr(client, 'npcs', {}) or {}).items():
            npc_type = npc.get('tiletype', 0)
            if runtime is not None:
                if npc_id in runtime.shapes:
                    # TServerNPC.cpp:2016-2040: live fractional NPC-relative
                    # lookup, just like tiletype and movement collision.
                    npc_type = runtime._shape_type_at(npc_id, npc, x, y)
            if npc_type == 20 or not point_hits_npc(client, npc, x, y):
                continue
            kind = obj.get('type', 'bush')
            npc['pelt_kind'] = {'pot': 'vase', 'rock': 'stone'}.get(kind, kind)
            npc['protected_object'] = 0xf  # TServerCarry.cpp:174.
            gs1, gs2 = game.gs1, game.gs2
            if gs1 is not None:
                gs1.trigger_npc_event(npc_id, 'waspelt')
            if gs2 is not None:
                gs2.trigger_npc_event(npc_id, 'onWasPelt')
            return True
        if remote:
            p = client.player
            if (throw_hits(obj['x'], obj['y'], p.x, p.y)
                    and obj.get('layer', 0) == getattr(p, 'layer', 0)
                    and client.can_receive_local_hit()):
                # TServerCarry.cpp:186-197: known throwers force landing in no-PK.
                owner_id = obj.get('owner_id', 0)
                level = getattr(getattr(client, 'gs2_host', None), 'level_object', None)
                nopk = (getattr(client, 'level_nopk', False)
                        or (level is not None and level.get('isnopkzone')))
                if nopk and owner_id in client.players:
                    return True
                damage = throw_damage(p.hearts)
                # Share the relay grace and duplicate guard used by arrows:
                # an attacker may also report this collision with HURTPLAYER.
                client._pending_arrow_hits.append({
                    'owner_id': obj.get('owner_id', 0), 'damage': damage,
                    'pvp': False,
                    'damage_type': 'bush', 'dx': obj['dx'], 'dy': obj['dy'],
                    'resolve_at': client.clock.sim_now() + client._ARROW_HIT_GRACE})
                return True
        else:
            for pid, p in getattr(client, 'players', {}).items():
                ox, oy = remote_origin(client, p)
                px, py = p.get('world_x'), p.get('world_y')
                px = p.get('x', 0) + ox if px is None else px
                py = p.get('y', 0) + oy if py is None else py
                if (p.get('status', 0) & 0x09 or p.get('action_mode', 0) in (3, 10)
                        or getattr(client, 'level_nopk', False)):
                    continue
                if throw_hits(obj['x'], obj['y'], px, py):
                    # combat.py:728-763: server reports share 2 s invincibility.
                    client.attack_player(pid, damage=throw_damage(p.get('hearts', 3)),
                                         knockback_x=obj['dx'], knockback_y=obj['dy'])
                    return True
    obj['z'] = INITIAL_HEIGHT - HEIGHT_DROP * obj.get('ticks', 0)
    return obj.get('ticks', 0) >= obj.get('landing_tick', THROW_TICKS)


# TServerLeap.cpp:11-81,110-132: signed offsets in eighth-tiles; unused chunks omitted.
LEAP_FRAMES = (
    (  # type 0
        ((25, 0, 4), (25, 6, 0), (26, 6, 8), (26, 9, 17)),
        ((25, -2, 4), (25, 4, -4), (26, 8, 10), (26, 9, 19)),
        ((26, -4, 4), (25, 2, -8), (26, 10, 12), (26, 9, 21)),
        ((25, -5, 4), (25, 1, -10), (25, 9, 13), (25, 9, 22)),
        ((25, -6, 4), (25, 0, -12), (25, 10, 14), (25, 10, 23)),
        ((26, -7, 4), (25, -1, -14), (26, 10, 15), (26, 10, 24)),
        ((26, -8, 4), (25, -2, -16), (26, 10, 22), (26, 10, 25)),
    ),
    (  # type 1
        ((24, 0, 8), (24, 8, 0), (24, 12, 8)),
        ((24, -2, 8), (24, 8, -2), (24, 14, 8)),
        ((24, -4, 8), (24, 8, -4), (24, 16, 8)),
        ((24, -6, 8), (24, 8, -6), (24, 18, 8)),
    ),
    (  # type 2
        ((96, -1, 0), (96, 0, 9), (98, 9, -1), (98, 10, 8)),
        ((99, -3, -2), (99, -2, 11), (97, 11, -3), (97, 12, 10)),
        ((96, -5, -4), (96, -4, 13), (98, 13, -5), (98, 14, 12)),
        ((99, -7, -6), (99, -6, 15), (97, 15, -7), (97, 16, 14)),
    ),
    (  # type 3
        ((100, -1, 0), (100, 0, 9), (102, 9, -1), (102, 10, 8)),
        ((103, -3, -2), (103, -2, 11), (101, 11, -3), (101, 12, 10)),
        ((100, -5, -4), (100, -4, 13), (102, 13, -5), (102, 14, 12)),
        ((103, -7, -6), (103, -6, 15), (101, 15, -7), (101, 16, 14)),
    ),
    (  # type 4
        ((132, 0, 0), (133, 10, 0), (134, 0, 9), (135, 10, 9)),
        ((132, -4, -4), (133, 14, -4), (134, -4, 13), (135, 14, 13)),
        ((132, -8, -8), (133, 18, -8), (134, -8, 17), (135, 18, 17)),
        ((132, -12, -12), (133, 22, -12), (134, -12, 21), (135, 22, 21)),
    ),
    (  # type 5
        ((326, -6, 3), (327, 7, 3)),
        ((326, -8, 1), (327, 9, 1)),
        ((326, -9, -1), (327, 10, -1)),
        ((326, -10, -3), (327, 11, -3)),
        ((326, -13, -4), (327, 14, -4)),
        ((326, -15, -4), (327, 16, -4)),
        ((326, -17, -3), (327, 18, -3)),
        ((326, -19, -1), (327, 20, -1)),
    ),
)

