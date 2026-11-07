"""NPC attachment state shared by packet handlers, scripts and drawing."""

import math

from reborn_protocol.coords import local_coord, segment_origin
from reborn_protocol.props import PLAYER_PROPS, encode_value


def _data(player):
    return player if isinstance(player, dict) else getattr(player, '__dict__', {})


def _rounded(value):
    return math.floor(value * 16 + .5) / 16


def npc_position(npc):
    return (npc.get('world_x', npc.get('x', 0)),
            npc.get('world_y', npc.get('y', 0)))


def detach(client, player, send=False):
    data = _data(player)
    old = data.pop('_attachment', None)
    data['attached_npc_id'] = 0
    data['attached_npc_type'] = 0
    if old and isinstance(player, dict):
        for axis in ('x', 'y'):
            data['world_' + axis] = data.get(axis, 0)
            data[axis] = (local_coord(data.get(axis, 0))
                          if getattr(client, 'is_gmap', False) else data.get(axis, 0))
    if old and not old.get('pending') and send:
        send_attachment(client)


def attach(client, player, npc_id, deferred=False, send=False):
    data = _data(player)
    old = data.get('_attachment')
    if old and old['npc_id'] == npc_id:
        return
    npc = client.npcs.get(npc_id)
    if npc is None:
        if deferred and old is None:
            data['_attachment'] = {'npc_id': npc_id, 'pending': True}
        return
    if old:
        detach(client, player, send=send)
    # TServerPlayer.cpp:530-562: keep world displacement on immediate attach.
    if isinstance(player, dict):
        grid = getattr(client, 'gmap_grid', {})
        cell = next((cell for cell, level in grid.items()
                     if level == data.get('level')), None)
        origin = segment_origin(*cell) if cell else (0, 0)
        for axis, offset in zip(('x', 'y'), origin):
            data[axis] = data.get('world_' + axis, data.get(axis, 0) + offset)
    nx, ny = npc_position(npc)
    data['_attachment'] = {'npc_id': npc_id, 'last_x': nx, 'last_y': ny}
    data['attached_npc_type'], data['attached_npc_id'] = 0, npc_id
    sync_attachment(client, player)
    if send:
        send_attachment(client)


def sync_attachment(client, player):
    data = _data(player)
    att = data.get('_attachment')
    if att is None:
        return None
    npc = client.npcs.get(att['npc_id'])
    if npc is None:
        if not att.get('pending'):
            detach(client, player, send=not isinstance(player, dict))
        return None
    level = npc.get('_level')
    current = getattr(client, '_current_level_name', '')
    if level and current and level != current and not getattr(client, 'is_gmap', False):
        detach(client, player, send=not isinstance(player, dict))
        return None
    nx, ny = npc_position(npc)
    # TClient.cpp:2944: a deferred player's stored coordinates are offsets.
    resolved = att.pop('pending', False)
    if resolved:
        att['last_x'], att['last_y'] = 0, 0
        data['attached_npc_type'], data['attached_npc_id'] = 0, att['npc_id']
    # TServerPlayer.cpp:1501-1540: round displacement, then add the parent.
    data['x'] = nx + _rounded(data.get('x', 0) - att['last_x'])
    data['y'] = ny + _rounded(data.get('y', 0) - att['last_y'])
    att['last_x'], att['last_y'] = nx, ny
    if isinstance(player, dict):
        data['world_x'], data['world_y'] = data['x'], data['y']
    elif resolved:
        send_attachment(client)
    return npc


def apply_attachment_props(client, player, props):
    """Resolve attachment before interpreting this packet's relative axes."""
    data = _data(player)
    sync_attachment(client, player)
    attachment = props.pop('attach_npc', None)
    if attachment is not None:
        kind, npc_id = attachment
        # TServerPlayer.cpp:1771's PLPROP_CARRYNPC label is wrong: its
        # type + gint3 id layout is prop 42 (ATTACHNPC), not carried-NPC prop 24.
        if npc_id <= 0:
            detach(client, player, send=not isinstance(player, dict))
        elif kind == 0:
            attach(client, player, npc_id, deferred=True, send=not isinstance(player, dict))
    npc = sync_attachment(client, player)
    if npc is not None:
        nx, ny = npc_position(npc)
        for axis, base in (('x', nx), ('y', ny)):
            if axis in props:
                props[axis] = base + _rounded(props[axis])
                props['world_' + axis] = props[axis]
    return '_attachment' in data


def update_attachments(client):
    sync_attachment(client, client.player)
    for player in getattr(client, 'players', {}).values():
        sync_attachment(client, player)


def delete_npc_attachments(client, npc_id):
    for player in (client.player, *client.players.values()):
        att = _data(player).get('_attachment')
        if att and att['npc_id'] == npc_id:
            sync_attachment(client, player)
            detach(client, player, send=not isinstance(player, dict))


def attachment_z(client, player):
    # TLevelObject.cpp:113-118: attachment inherits z without replacing own z.
    npc = sync_attachment(client, player)
    return npc.get('z', 0) if npc is not None else 0


def stored_position(client, x, y):
    level = getattr(client, '_current_level_name', '')
    att = _data(client.player).get('_attachment')
    if att and att.get('pending'):
        # A deferred receiver still stores the incoming offsets directly.
        return _rounded(x), _rounded(y)
    if att:
        npc = client.npcs.get(att['npc_id'])
        if npc is not None:
            nx, ny = npc_position(npc)
            # Receivers add the NPC position; both positions are world-space.
            return _rounded(x - nx), _rounded(y - ny)
    cell = next((cell for cell, name in getattr(client, 'gmap_grid', {}).items()
                 if name == level), None)
    ox, oy = segment_origin(*cell) if cell else (0, 0)
    return x - ox, y - oy


def sends_attachment(client):
    """Attached axes go out NPC-relative only where the server knows
    ATTACHNPC (42) and X2/Y2; pre-2.30 servers keep the attachment local
    and get level-local X/Y."""
    return bool(getattr(client, '_use_pixel_props', True)
                and _data(client.player).get('_attachment'))


def send_attachment(client):
    # ATTACHNPC then NPC-relative X2/Y2; detached axes are level-local.
    if not client.connected or not client._authenticated:
        return False
    if not getattr(client, '_use_pixel_props', True):
        return False
    player = client.player
    x, y = stored_position(client, player.x, player.y)
    values = ((42, (0, player.attached_npc_id)), (78, x), (79, y))
    payload = b''.join(bytes([pid + 32]) + encode_value(PLAYER_PROPS[pid], value)
                       for pid, value in values)
    from .packets import PacketID
    sent = client._protocol.send_packet(PacketID.PLI_PLAYERPROPS, payload)
    if sent:
        client._note_position_sent()
    return sent
