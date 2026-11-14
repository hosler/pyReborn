"""The client handles entity packets.

These packets contain local player properties, other-player rosters, NPCs,
baddies, and ground items.
"""

from reborn_protocol.coords import local_to_world, segment_origin

from ..gmap_coords import (grid_of, in_grid, level_origin, origin_at,
                           same_level)

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
from reborn_protocol import PLPROP, PLSTATUS

from ..client_callbacks import emit
from ..npc_handler import (CHARACTER_IMAGE, is_map_name, mark_npc_character,
                           npc_cell, place_npc)
from .registry import STOP, handles
from ..colors_width import colors_width_policy
from ..attachments import (apply_attachment_props, update_attachments,
                           delete_npc_attachments)

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


def _parse_colors_stream(parser, client, data):
    colors_len, known = colors_width_policy(client)
    return parser(data, colors_len, client.prop_parse_diagnostics,
                  colors_len_known=known)


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
    # gmap_name/gmap_grid are only filled once the .gmap FILE has been
    # downloaded and parsed, but the server names the gmap in PLO_LEVELNAME
    # (-> player.level) before that, and it sends the props of every player
    # already in the world in the same login stream. Trusting the announced
    # name keeps them: without it the second player to log into a populated
    # gmap dropped everyone present (later X/Y-only updates then re-created
    # them as nickname-less ghosts; QA multi_visibility on a gmap spawn).
    announced = getattr(getattr(client, 'player', None), 'level', None)
    if other_level and announced and other_level == announced \
            and announced.endswith('.gmap'):
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
        if left_level:
            emit(client, 'on_player_left', player_id)
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
    props = _parse_colors_stream(parse_player_props, client, data)
    # client._handle_packet reads the login look from THIS parse, so the
    # look-ahead can never pick a different COLORS width for the packet.
    client._last_self_props = dict(props)

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
    attached = apply_attachment_props(client, client.player, props)
    if not attached and ('x' in props or 'y' in props):
        grid = (grid_of(client.gmap_grid, client._current_level_name)
                if client.gmap_width > 0 else None)
        if grid is not None:
            # world = local + segment origin (the reference client's
            # local + (mapX << 6)). The wire value is level-local even
            # outside 0-63: a local just past the edge (70.25, -1.5) is
            # legitimate, so it is not wrapped.
            seg_ox, seg_oy = segment_origin(*grid)
            if 'x' in props:
                props['x'] = props['x'] + seg_ox
            if 'y' in props:
                props['y'] = props['y'] + seg_oy

    client.player.update_from_props(props)
    if client.player.hearts > 0:
        # Authoritative HP restoration starts a new life for kill claims.
        client._pker_claimed = False
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

    # The reference server keeps a player's status across sessions, so a
    # disconnect in the middle of hideplayer() can come back as a permanent
    # hide. Only a pending local hide may carry the bit: clear it and tell
    # the server once.
    if ('status' in props and not client.hide_player_until
            and int(client.player.status) & PLSTATUS.HIDDEN):
        client.player.status = int(client.player.status) & ~PLSTATUS.HIDDEN
        client._send_appearance_prop(PLPROP.STATUS, client.player.status)


@handles(PacketID.PLO_ITEMADD)
def handle_item_add(client, data):
    # PLO_ITEMADD (22) - item added to level
    item_info = parse_item_add(data)
    if item_info:
        x = item_info.get('x', 0)
        y = item_info.get('y', 0)
        item_type = item_info.get('type', '')
        # Items of a level that is not the player's own are dropped
        # (TClient.cpp:3665): an adjacent preload's scope is the neighbour.
        if not client._scope_is_own_level():
            return
        level_name = client._level_scope_name()
        client.items.setdefault(level_name, {})[(x, y)] = item_type
        # The reference starts a fresh lifetime on receipt (putExtra 0xa4,
        # TClient.cpp:3685), including for items already lying there on entry.
        client.item_stamps[(level_name, (x, y))] = client.item_clock()
        emit(client, 'on_item', x, y, item_type, True)


@handles(PacketID.PLO_ITEMDEL)
def handle_item_del(client, data):
    # PLO_ITEMDEL (23) - item removed from level
    item_info = parse_item_del(data)
    if item_info:
        x = item_info.get('x', 0)
        y = item_info.get('y', 0)
        # Same gate and level scope as additions (TClient.cpp:3719), so
        # matching local positions in different levels stay independent.
        if not client._scope_is_own_level():
            return
        level_name = client._level_scope_name()
        # The reference server relays a take to the OTHER players only; the
        # taker already removed its copy when it sent PLI_ITEMTAKE, and an
        # item that expired locally is gone too, so an unknown spot is a no-op.
        client.remove_item_local(level_name, x, y)


@handles(PacketID.PLO_ADDPLAYER)
def handle_add_player(client, data):
    # PLO_ADDPLAYER (55) - online roster entry (login dump + joins)
    info = parse_rc_add_player(data)
    if info and 'id' in info:
        pid = info['id']
        is_new = pid not in client.player_list
        client.player_list.setdefault(pid, {}).update(info)
        if is_new:
            emit(client, 'on_add_player', pid, client.player_list[pid])


@handles(PacketID.PLO_DELPLAYER)
def handle_del_player(client, data):
    # PLO_DELPLAYER (56) - player left the server
    pid = parse_rc_del_player(data)
    info = client.player_list.pop(pid, None)
    if info is not None:
        emit(client, 'on_del_player', pid, info)
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
        found = client.find_baddy(baddy_id)
        if found is not None:
            _, baddy = found
            baddy.update(props)
        else:
            # Preserve the per-level-store rule: search existing buckets first
            # and use the level scope only for a new id.
            level_name = client._level_scope_name()
            client.baddies.setdefault(level_name, {})[baddy_id] = props
        emit(client, 'on_baddy', baddy_id, props)


@handles(PacketID.PLO_NPCPROPS)
def handle_npc_props(client, data):
    # NPC properties
    props = _parse_colors_stream(parse_npc_props, client, data)
    if props and 'id' in props:
        npc_id = props['id']
        npc_level, cell, owned = _npc_level_and_cell(client, npc_id, props)
        props['_level'] = npc_level
        props['_map_owned'] = owned
        if cell is not None:
            props['gmaplevelx'], props['gmaplevely'] = cell
        if npc_id in client.npcs:
            if 'x' in props or 'y' in props:
                client.npcs[npc_id].pop('_move_queue', None)
            client.npcs[npc_id].update(props)
            # A cell change moves the NPC even when its local x/y did not
            # change, so both axes are placed from the merged record.
            place_npc(client.gmap_grid, client.npcs[npc_id])
        else:
            place_npc(client.gmap_grid, props)
            # First sighting of this NPC (not an in-play movement
            # update of an already-known one) - mark it so the
            # renderer snaps its visual position rather than lerping
            # in from wherever a stale same-id visual entry sits.
            client._mark_npc_pos_snap(props)
            client.npcs[npc_id] = props
        if props.get('image'):
            # The server marks a character with the image "#c#" (a
            # `showcharacter` sends it); any other non-empty image clears
            # the mark, like the client's setimg. An empty image changes
            # nothing.
            mark_npc_character(client.npcs[npc_id],
                               props['image'] == CHARACTER_IMAGE)
        update_attachments(client)
        host = getattr(client, 'gs2_host', None)
        if 'gani' in props and host is not None:
            host.note_gani(("npc", npc_id), props['gani'], force=True)
        if 'classes' in props and host is not None:
            # Modern servers send SCRIPT empty and list the joined classes
            # here; the client pulls each one (PLI_UPDATECLASS). A present but
            # empty list replaces the old one; an absent prop changes nothing.
            host.npc_classes(npc_id, props['classes'])


def _npc_level_and_cell(client, npc_id, props):
    """The level, map cell and owner kind an NPC props packet leaves the NPC in.
    The third value is whether the owner is a map (the reference's
    `serverLevel` is the map, TServerNPC.cpp:316-319); `npc_in_range` reads
    it, because only a map-owned NPC is hidden outside the 3x3.

    The reference client's rule:

    * A new NPC joins the active NPC level, the last PLO_SETACTIVELEVEL
      (TClient.cpp:2894-2922). A ``.gmap`` name makes the map its owner
      (TClient.cpp:3777-3784) and the NPC keeps its own cell, which starts at
      (0, 0) (TServerNPC.cpp:316-319, TLevelObject.cpp:28-31); the reference
      server sends GMAPLEVELX/Y only when the cell is not (0, 0)
      (GServer-v2 server/src/object/NPC.cpp:146-150). A segment name makes
      that segment the owner and the NPC copies the segment's cell
      (TServerNPC.cpp:321-324, the segment's cell from
      TServerLevel.cpp:945-946).
    * Props 41/42 then set the cell one axis at a time
      (TServerNPC.cpp:1271-1282): a packet with only GMAPLEVELX keeps the
      other axis. The reference server sends only the axis that changed
      when an NPC crosses a seam (GServer-v2 server/src/object/NPC.cpp:458-467).
    * A known NPC with an id below 1000 keeps the level and cell it has, then
      takes the props. One with an id of 1000 or more is added to the active
      NPC level on every props packet, when there is one
      (TClient.cpp:2950-2951). Added to a level it is already in, nothing
      changes; added to a map it keeps its own cell; added to a plain level
      it takes that level's cell (TServerNPC.cpp:289-325). Added to the map
      from a plain level it keeps the cell it has (an NPC in a level off
      the grid has cell (0, 0), so its local position is its world
      position) and becomes map-owned. Here the level of a map-owned NPC is
      the segment at its cell, so an NPC already map-owned never changes
      level or cell under a map target.

    The level is the grid's segment at the cell when there is one. A
    ``.gmap`` name is never kept as the level: the NPC falls back to its
    known level, else the player's level, until the grid is loaded and
    `_update_npc_world_coords` places it again.
    """
    grid = client.gmap_grid
    active = client._npc_level or client._current_level_name
    known = client.npcs.get(npc_id)
    if known is None:
        level = active
        owned = is_map_name(active)
        base = grid_of(grid, active)
        if base is None and owned:
            base = (0, 0)
    else:
        level = known.get('_level') or active
        owned = bool(known.get('_map_owned'))
        base = npc_cell(grid, known)
        if base is None and is_map_name(level):
            # A map-owned NPC that never had a cell stamped (the reference
            # loader stamps only gmap-loaded NPCs, LevelLoader.cpp:386-392;
            # an unchanged value is not sent, NPC.cpp:1458-1462) re-joins the
            # map at cell (0, 0) (TServerNPC.cpp:316-319,
            # TLevelObject.cpp:28-31).
            base = (0, 0)
        target = client._npc_level
        if npc_id >= 1000 and target:
            if is_map_name(target):
                if not owned:
                    # From a plain level into the map: the NPC keeps the
                    # cell it has (TServerNPC.cpp:316-319); one in a level
                    # off the grid has cell (0, 0), so its local position
                    # becomes its world position.
                    owned = True
                    if base is None:
                        base = (0, 0)
            elif owned or not same_level(level, target):
                # Out of the map, or between plain levels: it copies the
                # new level's cell (TServerNPC.cpp:321-324).
                owned = False
                level = target
                base = grid_of(grid, target)
                if base is None:
                    # A level outside the grid has no cell to copy: drop the
                    # old one, as handle_npc_moved does for a plain level.
                    known.pop('gmaplevelx', None)
                    known.pop('gmaplevely', None)
    gx, gy = props.get('gmaplevelx'), props.get('gmaplevely')
    if base is None and gx is None and gy is None:
        return level, None, owned
    bx, by = base if base is not None else (0, 0)
    cell = (bx if gx is None else gx, by if gy is None else gy)
    segment = grid.get(cell) if grid else None
    if segment is not None:
        return segment, cell, owned
    if is_map_name(level):
        fallback = known.get('_level') if known is not None else None
        if not fallback or is_map_name(fallback):
            fallback = client._current_level_name or level
        level = fallback
    return level, cell, owned


@handles(PacketID.PLO_SHOWIMGNPC)
def handle_npc_showimgs(client, data):
    # Server-owned GS1 showimg layers. Updates are sparse and mutate the
    # same npc['imgs'] records used by locally interpreted GS1 commands.
    info = parse_npc_showimgs(data)
    npc_id = info.get('npc_id')
    if npc_id is not None:
        npc = client.npcs.setdefault(npc_id, {})
        apply_showimgs(npc, info)


def _showimg_origin(client, owner):
    """World origin of the segment a player's show-images are placed in.

    The reference adds the owner's own segment (mapX << 6,
    TServerPlayer.cpp:826-860). In order of preference: the owner's
    gmaplevelx/gmaplevely props; the segment holding its world position;
    the segment whose .nw name is its level. Real servers report another
    player's level as the .gmap file, which names no segment, so the level
    name is the last resort. A level outside any gmap has origin (0, 0).
    """
    gx, gy = owner.get('gmaplevelx'), owner.get('gmaplevely')
    if gx is not None and gy is not None:
        return segment_origin(gx, gy)
    wx, wy = owner.get('world_x'), owner.get('world_y')
    if wx is not None and wy is not None and getattr(client, 'is_gmap', False):
        return origin_at(wx, wy)
    return level_origin(client.gmap_grid, owner.get('level'))


def apply_showimgs(owner, info, client=None):
    imgs = owner.setdefault('imgs', {})
    if info['clear']:
        imgs.clear()
    for index, changes in info['records'].items():
        if changes.get('image') == '':
            imgs.pop(index, None)
            continue
        rec = imgs.setdefault(index, {})
        rec.update(changes)
        rec.setdefault('screen', False)
        rec.setdefault('vis', 1 if info.get('player_images') else 4)
        if info.get('player_images'):
            # FourPlay/quattroplay/src/TServerPlayer.cpp:826-860.
            for axis in ('x', 'y'):
                if axis in changes:
                    rec['_wire_' + axis] = changes[axis]
            gui = rec['vis'] >= 11
            rec['vis_set'] = gui
            origin = _showimg_origin(client, owner)
            for axis, offset in zip(('x', 'y'), origin):
                value = rec.get('_wire_' + axis, 0)
                rec[axis] = value * 4 if gui else value + offset


def _drop_npc_bytecode(client, npc_id):
    """A deleted NPC's stored GS2 blob must not outlive it: the GS2 host
    replays every stored blob when it is installed, so a host installed after
    the delete, or a reused id that now carries a text script, would
    resurrect the old bytecode. Class, weapon and gani blobs are untouched."""
    client.gs2_bytecode['npc'].pop(npc_id, None)


def _purge_cached_npc(client, npc_id, level=None):
    """Drop `npc_id` from the per-level NPC cache: from every bucket, or
    only from `level`'s when one is given."""
    for name, bucket in client._npc_cache.items():
        if level is None or name == level:
            bucket.pop(npc_id, None)


@handles(PLO_NPCDEL)
def handle_npc_del(client, data):
    # NPC deleted
    if len(data) >= 3:
        from ..packets import PacketReader
        reader = PacketReader(data)
        npc_id = reader.read_gint3()
        delete_npc_attachments(client, npc_id)
        _drop_npc_bytecode(client, npc_id)
        npc = client.npcs.pop(npc_id, None)
        # The reference deletes by id from the global NPC table
        # (TClient.cpp:5171-5175, 2795-2799), so no level's cache keeps it.
        _purge_cached_npc(client, npc_id)
        if npc is not None:
            emit(client, 'on_npc_del', npc_id)


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
    delete_npc_attachments(client, npc_id)
    _drop_npc_bytecode(client, npc_id)
    if npc_id in client.npcs:
        del client.npcs[npc_id]
        emit(client, 'on_npc_del', npc_id)
    # The reference deletes from the named level's roster only
    # (TClient.cpp:2802-2811, :5233-5250). A map owns every NPC placed in it,
    # and this client files those under the map's segments, so a map or
    # segment name purges every bucket; a plain level purges its own.
    if is_map_name(level) or in_grid(client.gmap_grid, level):
        _purge_cached_npc(client, npc_id)
    else:
        _purge_cached_npc(client, npc_id, level)


@handles(PacketID.PLO_OTHERPLPROPS)
def handle_other_player_props(client, data):
    # Other player properties
    props = _parse_colors_stream(parse_other_player, client, data)
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
            emit(client, 'on_player_left', player_id)
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
        if chat:
            emit(client, 'on_chat', player_id, chat)
        # X/Y (15/16) and X2/Y2 (78/79) are both LEVEL-LOCAL: the reference
        # server stores the received pixel value unchanged and relays it
        # verbatim (GServer-v2 beta4 PlayerProps.cpp X2/Y2 setters store
        # localPixelX/Y), and the player's gmap segment travels separately
        # in GMAPLEVELX/Y (43/44). A local just past a segment edge (70.25,
        # -1.5) is legitimate, so the frame comes from the prop, never from
        # the value's magnitude. 'x'/'y' keep the wire value unwrapped;
        # 'world_x'/'world_y' are derived only once that player's own
        # segment is known (see _resolve_player_world).
        existing = client.players.setdefault(player_id, {})
        attached = apply_attachment_props(client, existing, props)
        for key, value in props.items():
            if value is None:
                existing.pop(key, None)     # None marks a value to drop
            else:
                existing[key] = value
        if not attached and _FRAME_KEYS.intersection(props):
            _resolve_player_world(client, existing)
        if 'ani' in props:
            host = getattr(client, 'gs2_host', None)
            if host is not None:
                host.note_gani(("player", player_id), props['ani'], force=True)


#: Props that move another player's world position: its local position, or
#: the segment that local position is measured from.
_FRAME_KEYS = frozenset(('x', 'y', 'gmaplevelx', 'gmaplevely', 'level'))


def _player_segment(client, record):
    """The gmap segment another player's local position is measured from.

    Its own GMAPLEVELX/Y props first (the reference's mapX/mapY), else the
    segment its level name names. Reference servers and pygserver report the
    .gmap file as the level, which names no segment, so the grid props are
    the normal source. None when neither is known yet.
    """
    gx, gy = record.get('gmaplevelx'), record.get('gmaplevely')
    if gx is not None and gy is not None:
        return gx, gy
    return grid_of(client.gmap_grid, record.get('level'))


def _resolve_player_world(client, record):
    """Set or clear `record`'s world_x/world_y from its local x/y.

    world = local + that player's own segment origin, the reference client's
    local + (mapX << 6). The props can arrive in any order across packets
    (X2/Y2 before or without the grid props), so an unknown segment clears
    the world position instead of guessing one; consumers then fall back to
    their own segment, which is right for a same-segment player.
    """
    segment = _player_segment(client, record)
    if segment is None or 'x' not in record or 'y' not in record:
        record.pop('world_x', None)
        record.pop('world_y', None)
        return
    record['world_x'], record['world_y'] = local_to_world(
        record['x'], record['y'], *segment)


def _canonical_level_name(client, name):
    """Level name as the reference resolves it: case-insensitively.

    setnpcremoved looks the level up through getLevel, which lower-cases the
    name (unsorted.cpp:2435-2447, TFiles::lowerCaseFilename). This client
    keys levels by the spelling the server first used, so a name matching a
    known level in any case takes that spelling and an unknown one is
    lower-cased, keeping later level-name comparisons consistent.
    """
    if not name:
        return name
    lowered = name.lower()
    known = (client._current_level_name, client._npc_level,
             *client.gmap_grid.values(), *client.levels)
    for candidate in known:
        if isinstance(candidate, str) and candidate.lower() == lowered:
            return candidate
    return lowered


@handles(PacketID.PLO_NPCMOVED)
def handle_npc_moved(client, data):
    # FourPlay/quattroplay/src/TClient.cpp:2958-2981.
    info = parse_npcmoved(data)
    info['new_level'] = _canonical_level_name(client, info['new_level'])
    npc = client.npcs.get(info['npc_id'])
    if npc is not None:
        level = info['new_level']
        npc['_level'] = level
        npc['_map_owned'] = is_map_name(level)
        npc['visible'] = bool(level) and bool(npc.get('visflags', 1) & 1)
        if level:
            npc['x'], npc['y'] = info['x'], info['y']
            # Joining a plain level copies that level's cell: a segment's
            # own, (0, 0) for any other (TServerNPC.cpp:321-324,
            # TServerLevel.cpp:945-946, :959-960). What a .gmap name here
            # does to the cell is not established; the NPC keeps its own.
            cell = grid_of(client.gmap_grid, level)
            if cell is not None:
                npc['gmaplevelx'], npc['gmaplevely'] = cell
            elif not is_map_name(level):
                npc.pop('gmaplevelx', None)
                npc.pop('gmaplevely', None)
            cell = npc_cell(client.gmap_grid, npc)
            ox, oy = segment_origin(*cell) if cell is not None else (0, 0)
            npc['world_x'], npc['world_y'] = info['x'] + ox, info['y'] + oy
        npc.pop('_move_queue', None)
        client._mark_npc_pos_snap(npc)
        update_attachments(client)
    emit(client, 'on_npc_moved', info)


def _handle_moves(client, info):
    from ..npc_movement import queue_moves
    queue_moves(client, info)
    client.npc_moves[info['npc_id']] = info
    emit(client, 'on_npc_move', info)


@handles(PacketID.PLO_MOVE2)
def handle_move2(client, data):
    _handle_moves(client, parse_move2(data))


@handles(PacketID.PLO_MOVE)
def handle_move(client, data):
    _handle_moves(client, parse_move(data))
