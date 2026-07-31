"""The client handles entity packets.

These packets contain local player properties, other-player rosters, NPCs,
baddies, and ground items.
"""

from reborn_protocol.coords import LEVEL_SIZE, local_coord, segment_origin

from ..packets import (
    PacketID,
    parse_baddy_props,
    parse_item_add,
    parse_item_del,
    parse_move,
    parse_move2,
    parse_npc_props,
    parse_npc_showimgs,
    parse_npcdel2,
    parse_npcmoved,
    parse_other_player,
    parse_player_props,
    parse_rc_add_player,
    parse_rc_del_player,
)
from .registry import STOP, handles

# NPC delete packet ID not in PacketID class yet
PLO_NPCDEL = 29

#: Props whose arrival marks the reference's `playerListChanged` flag, i.e.
#: fires universe.onPlayerChanges on an already-known player (FourPlay
#: TServerPlayer.cpp setProperties: NICKNAME :1581, ACCOUNTNAME :1821,
#: RATING-change :1840, prop-81 external :1952, COMMUNITYNAME :1959; the
#: rating prop has no handler in _OTHER_PROP_HANDLERS so it cannot appear
#: here).
_ROSTER_CHANGE_KEYS = frozenset(
    ('nickname', 'account', 'playerlist_flags', 'communityname'))


def _same_gmap_world(client, other_level):
    """Return True if `other_level` is part of the current gmap.

    A gmap is ONE contiguous world. GServer-v2 keeps the players from every
    segment in one Level. It reports the .gmap filename as each player's
    CURLEVEL (PlayerClient::getLevelName,
    server/src/player/PlayerClient.cpp:1148). Thus, the roster must keep
    players from adjacent segments. Without this function, the plain name
    comparison above drops each cross-segment properties packet. The other
    players then become invisible. This fault caused
    `--gmap cross_segment_visibility` to fail.

    The function accepts both forms because servers differ. A server can send
    the .gmap name or a sibling segment's .nw name. In the past, pygserver sent
    the .nw name.
    """
    if not getattr(client, 'is_gmap', False):
        return False
    if other_level == getattr(client, 'gmap_name', None):
        return True
    grid = getattr(client, 'gmap_grid', None) or {}
    return other_level in grid.values()


def _update_global_roster(client, player_id, props):
    """Update the session-global `all_players` roster.

    The function fires the engine's universe events through the attached GS2
    host.

    The function matches scriptfun_client_setotherplayerprops (FourPlay
    TClient.cpp:3076-3160). When the function first finds an ID, it adds the ID
    to allplayers and fires onPlayerLogin(other, id). The DISCONNECT property
    removes the ID and fires onPlayerLogout. A roster-related property update
    for a known player fires onPlayerChanges. Level leaves (joinleave==0) and
    cross-level updates do NOT change this roster. A player does not log out
    when the player leaves your level.

    Returns True when this packet was a logout (caller stops processing: the
    packet carries nothing but the DISCONNECT marker)."""
    roster = getattr(client, 'all_players', None)
    if roster is None:
        return False
    host = getattr(client, 'gs2_host', None)
    if props.get('disconnect'):
        record = roster.pop(player_id, None)
        left_level = client.players.pop(player_id, None) is not None
        if left_level and client.on_player_left:
            client.on_player_left(player_id)
        if record is not None and host is not None:
            host.roster_player_removed(player_id, record)
        return True
    is_new = player_id not in roster
    record = roster.setdefault(player_id, {})
    for key, value in props.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    if host is not None:
        if is_new:
            host.roster_player_added(player_id)
        elif any(key in props for key in _ROSTER_CHANGE_KEYS):
            host.roster_player_changed(player_id)
    return False


@handles(PacketID.PLO_PLAYERPROPS)
def handle_player_props(client, data):
    # Player properties (our player data)
    props = parse_player_props(
        data, client._colors_len, client.prop_parse_diagnostics)

    # Silent warp rejection (gs2emu): msgPLI_LEVELWARP with an
    # unloadable level sends NO PLO_WARPFAILED - it "resolves" by
    # re-warping us to our CURRENT level (PlayerClientPackets.cpp:
    # 92-98), and the same-level warp path (PlayerClient.cpp:
    # 1198-1218) emits only X2/Y2 props. So a server-set position
    # arriving while our warp still awaits its PLO_LEVELNAME confirm
    # means the server re-anchored us in the PRE-warp level: restore
    # it, then let the props below apply the authoritative position.
    # (A confirmed warp clears the flag via PLO_LEVELNAME before any
    # in-level props arrive, so this can't fire on a successful one.)
    if (client._awaiting_warp_confirm and client._warp_fallback
            and ('x' in props or 'y' in props)):
        client._restore_failed_warp(
            "server re-anchored position without level confirm")

    # The server tracks position as LOCAL coords (0-63) within the
    # player's current segment, not world coords. Convert to the client's
    # world-coordinate model so the camera stays aligned with the tiles.
    #
    # Only a level that is an actual GMAP segment gets the grid offset;
    # standalone interior levels reached via a door (houses, caves) are
    # not in the grid even though a gmap is loaded, so they stay local.
    if 'x' in props or 'y' in props:
        grid = None
        if client.gmap_width > 0:
            grid = next((cell for cell, name in client.gmap_grid.items()
                         if name == client._current_level_name), None)
        if grid:
            # Rebuild world coords: world = local + segment origin. Localizing
            # first makes this correct whether the server sent local or world.
            seg_ox, seg_oy = segment_origin(*grid)
            if 'x' in props:
                props['x'] = local_coord(props['x']) + seg_ox
            if 'y' in props:
                props['y'] = local_coord(props['y']) + seg_oy
        else:
            if 'x' in props:
                props['x'] = local_coord(props['x'])
            if 'y' in props:
                props['y'] = local_coord(props['y'])

    client.player.update_from_props(props)
    if 'animation' in props:
        host = getattr(client, 'gs2_host', None)
        if host is not None:
            host.note_gani(("local", getattr(client.player, "id", 0)),
                           props['animation'], force=True)

    # First props packet means we're authenticated
    if not client._authenticated:
        client._authenticated = True
        # Weapon headers announced earlier in this login burst
        # couldn't be pulled yet (request_weapon_bytecode refuses
        # pre-auth) — pull them now.
        for wname, hdr in client.gs2_script_headers.items():
            if hdr.get('type') == 'weapon' and not hdr.get('bytecode'):
                req_key = (wname, hdr.get('crc', ''))
                if req_key not in client._gs2_requested:
                    if client.request_weapon_bytecode(wname):
                        client._gs2_requested.add(req_key)


@handles(PacketID.PLO_ITEMADD)
def handle_item_add(client, data):
    # PLO_ITEMADD (22) - item added to level
    item_info = parse_item_add(data)
    if item_info:
        x = item_info.get('x', 0)
        y = item_info.get('y', 0)
        item_type = item_info.get('type', '')
        client.items[(x, y)] = item_type
        if client.on_item:
            client.on_item(x, y, item_type, True)


@handles(PacketID.PLO_ITEMDEL)
def handle_item_del(client, data):
    # PLO_ITEMDEL (23) - item removed from level
    item_info = parse_item_del(data)
    if item_info:
        x = item_info.get('x', 0)
        y = item_info.get('y', 0)
        item_type = client.items.pop((x, y), '')
        if client.on_item:
            client.on_item(x, y, item_type, False)


@handles(PacketID.PLO_ADDPLAYER)
def handle_add_player(client, data):
    # PLO_ADDPLAYER (55) - online roster entry (login dump + joins)
    info = parse_rc_add_player(data)
    if info and 'id' in info:
        pid = info['id']
        is_new = pid not in client.player_list
        client.player_list.setdefault(pid, {}).update(info)
        if is_new and client.on_add_player:
            client.on_add_player(pid, client.player_list[pid])


@handles(PacketID.PLO_DELPLAYER)
def handle_del_player(client, data):
    # PLO_DELPLAYER (56) - player left the server
    pid = parse_rc_del_player(data)
    info = client.player_list.pop(pid, None)
    if info is not None and client.on_del_player:
        client.on_del_player(pid, info)
    # Some server paths announce a logout only this way (the RC-flavored
    # roster); if the id is also in the global allplayers roster, that is a
    # logout there too. GServer-v2's client path sends the DISCONNECT prop
    # as well, in which case the roster entry is already gone and this is a
    # no-op.
    record = getattr(client, 'all_players', {}).pop(pid, None)
    if record is not None:
        host = getattr(client, 'gs2_host', None)
        if host is not None:
            host.roster_player_removed(pid, record)


@handles(PacketID.PLO_BADDYPROPS)
def handle_baddy_props(client, data):
    # PLO_BADDYPROPS (2) - baddy/enemy properties
    props = parse_baddy_props(data)
    if props and 'id' in props:
        baddy_id = props['id']
        if baddy_id in client.baddies:
            client.baddies[baddy_id].update(props)
        else:
            client.baddies[baddy_id] = props
        if client.on_baddy:
            client.on_baddy(baddy_id, props)


@handles(PacketID.PLO_NPCPROPS)
def handle_npc_props(client, data):
    # NPC properties
    props = parse_npc_props(
        data, client._colors_len, client.prop_parse_diagnostics)
    if props and 'id' in props:
        npc_id = props['id']
        # Associate the NPC with a level. Preference order:
        #   1. GMAPLEVELX/GMAPLEVELY props (41/42) -> gmap segment.
        #      gs2emu streams a gmap's NPCs under PLO_SETACTIVELEVEL
        #      <map>.gmap (the whole gmap is one level server-side,
        #      PlayerClient.cpp sendDynamicLevelData), so the pending
        #      level name is the .gmap - useless for placement. The
        #      grid cell carried in the props is the real attribution.
        #   2. The level this (already-known) NPC was previously
        #      attributed to - a partial runtime update without level
        #      info must not re-stamp it with whatever level happened
        #      to stream last (e.g. a stale neighbour-preload name).
        #   3. The pending/current level (fresh NPC on a plain level).
        npc_level = client._pending_level_name or client._current_level_name
        grid_cell = None
        gx = props.get('gmaplevelx')
        gy = props.get('gmaplevely')
        if gx is not None and gy is not None and (gx, gy) in client.gmap_grid:
            grid_cell = (gx, gy)
            npc_level = client.gmap_grid[grid_cell]
        else:
            known = client.npcs.get(npc_id)
            if (known is not None and known.get('_level')
                    and gx is None and gy is None):
                npc_level = known['_level']
            if client.gmap_grid and npc_level:
                grid_cell = next(
                    (cell for cell, name in client.gmap_grid.items()
                     if name == npc_level), None)
        props['_level'] = npc_level

        # Convert NPC local coords to world coords if in GMAP.
        # parse_npc_props writes both NPCPROP.X/Y (props 2/3,
        # always LEVEL-LOCAL) and NPCPROP.X2/Y2 (props 75/76,
        # pixel-precision - LOCAL on this server, but WORLD per the
        # general protocol on a real GServer-v2) into the same
        # 'x'/'y' keys. Blindly adding the segment offset here
        # double-counts it whenever 'x'/'y' is already a world
        # value: seen live as an NPC's world_x/world_y reading
        # exactly +64,+64 past its true position for one update,
        # then reverting. Guard the same way as the OTHERPLPROPS
        # merge (BUG 1): only fold in the segment offset for a
        # value that's still in the local 0-63 range.
        if grid_cell is not None:
            seg_ox, seg_oy = segment_origin(*grid_cell)
            if 'x' in props:
                raw_x = props['x']
                props['world_x'] = (raw_x if (raw_x >= LEVEL_SIZE or raw_x < 0)
                                     else raw_x + seg_ox)
            if 'y' in props:
                raw_y = props['y']
                props['world_y'] = (raw_y if (raw_y >= LEVEL_SIZE or raw_y < 0)
                                     else raw_y + seg_oy)
        elif not client.gmap_grid:
            # Not in GMAP - local coords are world coords
            if 'x' in props:
                props['world_x'] = props['x']
            if 'y' in props:
                props['world_y'] = props['y']
        if npc_id in client.npcs:
            client.npcs[npc_id].update(props)
        else:
            # First sighting of this NPC (not an in-play movement
            # update of an already-known one) - mark it so the
            # renderer snaps its visual position rather than lerping
            # in from wherever a stale same-id visual entry sits.
            client._mark_npc_pos_snap(props)
            client.npcs[npc_id] = props
        if 'gani' in props:
            host = getattr(client, 'gs2_host', None)
            if host is not None:
                host.note_gani(("npc", npc_id), props['gani'], force=True)


@handles(PacketID.PLO_SHOWIMGNPC)
def handle_npc_showimgs(client, data):
    # Server-owned GS1 showimg layers. Updates are sparse and mutate the
    # same npc['imgs'] records used by locally interpreted GS1 commands.
    info = parse_npc_showimgs(data)
    npc_id = info.get('npc_id')
    if npc_id is not None:
        npc = client.npcs.setdefault(npc_id, {})
        imgs = npc.setdefault('imgs', {})
        if info['clear']:
            imgs.clear()
        for index, changes in info['records'].items():
            rec = imgs.setdefault(index, {})
            rec.update(changes)
            rec.setdefault('screen', False)
            rec.setdefault('vis', 4)


@handles(PLO_NPCDEL)
def handle_npc_del(client, data):
    # NPC deleted
    if len(data) >= 3:
        from ..packets import PacketReader
        reader = PacketReader(data)
        npc_id = reader.read_gint3()
        npc = client.npcs.pop(npc_id, None)
        if npc is not None:
            level = npc.get('_level')
            cached = client._npc_cache.get(level) if level else None
            if cached is not None:
                cached.pop(npc_id, None)
            if client.on_npc_del:
                client.on_npc_del(npc_id)


@handles(PacketID.PLO_NPCDEL2)
def handle_npc_del2(client, data):
    # NPC deleted, scoped to an explicit level (packet 150) - sent instead
    # of PLO_NPCDEL when the target player's active level isn't the NPC's
    # level, so it also purges any stale per-level cache entry (see
    # packets.parse_npcdel2 for why: GServer-v2 targets clients with a
    # past-visit cached copy, not just the current level roster).
    info = parse_npcdel2(data)
    npc_id = info['npc_id']
    level = info['level']
    if npc_id in client.npcs:
        del client.npcs[npc_id]
        if client.on_npc_del:
            client.on_npc_del(npc_id)
    cached = client._npc_cache.get(level)
    if cached is not None:
        cached.pop(npc_id, None)


@handles(PacketID.PLO_OTHERPLPROPS)
def handle_other_player_props(client, data):
    # Other player properties
    props = parse_other_player(
        data, client._colors_len, client.prop_parse_diagnostics)
    if props and 'id' in props:
        player_id = props['id']
        # Session-global roster + universe events first: the level-roster
        # logic below early-returns for leaves/cross-level updates, and
        # those must still keep `allplayers` current.
        if _update_global_roster(client, player_id, props):
            return STOP           # pure logout notification, nothing to merge
        # An EXTERNAL player (prop-81 bit 1: another server's player, a
        # channel, or a channel member injected by the serverlist-chat leg)
        # is never in our level -- keep pseudo-players out of the in-level
        # roster the renderer/QA hit-tests iterate. The flag may only be on
        # the roster record (prop 81 isn't repeated on every update).
        roster_rec = getattr(client, 'all_players', {}).get(player_id, {})
        if int(roster_rec.get('playerlist_flags') or 0) & 1:
            client.players.pop(player_id, None)
            return STOP
        # JOINLEAVELVL=0 is the server's "this player left your
        # level" notification — drop them from the level roster
        # (they'd otherwise linger as a ghost at their last position).
        if props.get('joinleave') == 0:
            client.players.pop(player_id, None)
            if client.on_player_left:
                client.on_player_left(player_id)
            return STOP
        # gs2emu (unlike pygserver) keeps sending cross-level updates
        # for players AFTER their leave notification, with CURLEVEL
        # naming their new level — verified via live beta4 packet
        # trace (leave packet followed one tick later by a props
        # packet that re-added the ghost). client.players is the
        # SAME-LEVEL roster (sword arcs, visibility), so a props
        # update naming a different level removes/skips instead.
        other_level = props.get('level')
        if other_level and client._current_level_name and \
                other_level != client._current_level_name and \
                not _same_gmap_world(client, other_level):
            client.players.pop(player_id, None)
            return STOP
        # A non-empty CURCHAT prop is another player's chat bubble — the
        # primary in-level chat path. Surface it through on_chat.
        chat = props.get('chat')
        if chat and client.on_chat:
            client.on_chat(player_id, chat)
        # Normalize the X/Y coordinate FRAME before merging. Classic
        # props 15/16 (X/Y) are always LEVEL-LOCAL (0-63), while
        # high-precision props 78/79 (X2/Y2) legitimately carry WORLD
        # pixels on a gmap - but parse_other_player writes both into
        # the same 'x'/'y' keys, and different server paths favor
        # different props for the SAME player (e.g. pygserver relays
        # plain movement via classic X/Y-derived local coords but
        # respond_to_hurt's PLI_PLAYERPROPS round-trips the client's
        # own WORLD x/y through X2/Y2 verbatim). Without normalizing,
        # players[pid]['x'/'y'] silently flips frame depending on
        # which prop arrived LAST: seen live as another player's y
        # reported as 97.25 instead of 33.25 (a whole segment high),
        # which made every sword-hit test against them miss forever
        # until they moved or warped. Store LEVEL-LOCAL canonically
        # in 'x'/'y' (wrap any world value via %64) and ALSO stash
        # 'world_x'/'world_y' whenever the wire value told us the
        # true world position (>=64, only possible from X2/Y2) so
        # consumers that need world coords (cross-segment hit tests)
        # can prefer that over re-deriving it from our own segment.
        # A fresh LOCAL-only update invalidates any previously known
        # world_x/world_y - we no longer know it's still correct -
        # rather than let a stale world coordinate silently survive
        # a merge alongside a now-different local one.
        if 'x' in props:
            raw_x = props['x']
            if raw_x >= LEVEL_SIZE or raw_x < 0:
                props['world_x'] = raw_x
                props['x'] = local_coord(raw_x)
            else:
                props['world_x'] = None
        if 'y' in props:
            raw_y = props['y']
            if raw_y >= LEVEL_SIZE or raw_y < 0:
                props['world_y'] = raw_y
                props['y'] = local_coord(raw_y)
            else:
                props['world_y'] = None
        if player_id in client.players:
            # Merge props (None marks a value to DROP, not store -
            # see the world_x/world_y invalidation above).
            existing = client.players[player_id]
            for key, value in props.items():
                if value is None:
                    existing.pop(key, None)
                else:
                    existing[key] = value
        else:
            client.players[player_id] = {k: v for k, v in props.items()
                                        if v is not None}
        if 'ani' in props:
            host = getattr(client, 'gs2_host', None)
            if host is not None:
                host.note_gani(("player", player_id), props['ani'], force=True)


@handles(PacketID.PLO_NPCMOVED)
def handle_npc_moved(client, data):
    # NPC warped to a different level (packet 24).
    info = parse_npcmoved(data)
    if client.on_npc_moved:
        client.on_npc_moved(info)


@handles(PacketID.PLO_MOVE2)
def handle_move2(client, data):
    # NPC move-queue update, modern clients (packet 189).
    info = parse_move2(data)
    npc = client.npcs.get(info['npc_id'])
    if npc is not None:
        npc['x'] = info['x']
        npc['y'] = info['y']
    client.npc_moves[info['npc_id']] = info
    if client.on_npc_move:
        client.on_npc_move(info)


@handles(PacketID.PLO_MOVE)
def handle_move(client, data):
    # NPC move-queue update, legacy pre-CLVER_2_3 clients (packet 165) -
    # the GCHAR-precision counterpart to PLO_MOVE2 above. GServer-v2 sends
    # exactly one of MOVE/MOVE2 per move-queue update depending on the
    # recipient's negotiated version (NPC.cpp:472-475), so mirror MOVE2's
    # handling rather than treating this as a separate stream.
    info = parse_move(data)
    npc = client.npcs.get(info['npc_id'])
    if npc is not None:
        npc['x'] = info['x']
        npc['y'] = info['y']
    client.npc_moves[info['npc_id']] = info
    if client.on_npc_move:
        client.on_npc_move(info)
