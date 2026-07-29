"""Level and world packets: level naming/transitions, board data and tile
deltas, links, signs, chests, and the gmap/minimap metadata that frames them.
"""

import logging

from reborn_protocol.coords import local_to_world

from ..packets import (
    PacketID,
    parse_bigmap,
    parse_board_heights,
    parse_board_layer,
    parse_board_modify,
    parse_board_modify2,
    parse_board_packet,
    parse_level_chest,
    parse_level_link,
    parse_level_modtime,
    parse_level_name,
    parse_level_sign,
    parse_minimap,
    parse_playerwarp,
    parse_playerwarp2,
    parse_set_active_level,
)
from .registry import handles

logger = logging.getLogger(__name__)


def _load_cached_gmap(client, filename: str, blob: bytes) -> None:
    """Re-establish the gmap world frame from an already-downloaded .gmap.

    Mirrors handlers/files.handle_file's .gmap branch (the only other place a
    .gmap becomes a grid), minus the download.
    """
    try:
        client.load_gmap(blob.decode('latin-1', errors='replace'))
        client.gmap_name = filename
        client.request_adjacent_levels()
    except Exception:
        logger.warning("cached %s failed to parse; re-requesting", filename)
        client.request_file(filename)


@handles(PacketID.PLO_LEVELNAME)
def handle_level_name(client, data):
    # Level name - track which level we're receiving data for
    level_name = parse_level_name(data)
    # .nw files are actual levels, .gmap is the world map name
    if level_name.endswith('.nw'):
        # A real level transition (server push via PLO_PLAYERWARP/
        # PLO_PLAYERWARP2 for RC warps/respawn, or a client-initiated
        # warp_to_level()) always (re-)announces the destination via
        # this packet — GServer-v2 PlayerClient.cpp:1421/1473. Segments
        # of the currently loaded gmap are announced the same way as
        # we stream across them and must NOT reset per-level state
        # (that would wipe the stitched world's chests/signs/items/
        # NPCs on every segment hop); distinguish the two by checking
        # whether level_name is one of the loaded gmap's segments.
        is_gmap_segment = (client.gmap_width > 0 and
                            level_name in client.gmap_grid.values())
        if is_gmap_segment:
            # A GMAP segment's PLO_LEVELNAME is ambiguous on its own:
            # pygserver sends it both for a genuine warp/spawn (via
            # _send_level, always followed by PLO_PLAYERWARP2) AND for
            # a passive adjacent-segment preload (PLI_ADJACENTLEVEL,
            # sent by request_adjacent_levels() below and answered by
            # pygserver player.py _handle_adjacent_level, which streams
            # only [PLO_LEVELNAME, board] for a neighbour so the world
            # renders stitched — the player never moves and no warp
            # packet follows). Blindly trusting every one as "we are
            # now here" mislabels _current_level_name as whichever
            # neighbour preloaded last: e.g. spawning into chicken1.nw
            # (world (94, 94.5)) but ending up reporting chicken8.nw
            # once its 8 surrounding segments finish preloading, while
            # the NPCs/chests actually streamed still belong to
            # chicken1.nw. PLO_PLAYERWARP2 is the reliable "we actually
            # moved" signal — real warps/spawns always send it,
            # preloads never do — and its handler below already sets
            # _current_level_name from gmap_x/gmap_y, so leave it alone
            # here rather than trust this packet directly.
            pass
        elif (client._awaiting_warp_confirm
              and level_name != client._awaiting_warp_confirm):
            # A level stream already in flight is not authoritative
            # evidence that a client-requested warp failed.  In
            # particular, link-touch can race an old/adjacent board
            # response queued before PLI_LEVELWARP.  Route its board
            # through _pending_level_name below, but keep the requested
            # destination active and the camera held.  A PLAYERWARP
            # naming another level is the authoritative rejection.
            pass
        elif level_name != client._current_level_name:
            client._current_level_name = level_name
            client._plain_level_change_epoch += 1
            # Real warp: drop the old level's items/baddies/NPCs so
            # stale entries (e.g. a link back through a door that
            # doesn't exist here) don't leak into the new level,
            # then restore this level's NPCs from the session cache
            # (gs2emu won't re-stream them on a re-entry).
            client._reset_level_state()
            client._restore_cached_npcs(level_name)
        elif level_name == client._awaiting_warp_confirm:
            # Client-initiated warp: _current_level_name already equals
            # level_name (flipped optimistically at send), so the guard
            # above missed. Reset now on the authoritative confirmation
            # to purge any old-level NPC/chest props that leaked in
            # during the send->confirm window. cache_npcs=False: those
            # leaks are mis-stamped with THIS level, so caching them
            # would poison _npc_cache. On a FIRST visit the server
            # streams the real NPCs right after this packet; on a
            # re-entry it streams nothing (per-session level cache),
            # so restore this level's NPCs from our own session
            # cache - warp_to_level's optimistic restore was just
            # wiped by the reset above. (_npc_cache only ever holds
            # entries snapshotted with cache_npcs=True, i.e. stamped
            # BEFORE the warp, so no transit-window leak comes back.)
            client._reset_level_state(cache_npcs=False)
            client._restore_cached_npcs(level_name)
            client._plain_level_change_epoch += 1
        if (client._awaiting_warp_confirm
                and level_name == client._awaiting_warp_confirm):
            # The requested destination announcement confirms the
            # client warp. Other level streams can be stale/preloads;
            # an authoritative PLAYERWARP handles a real rejection.
            client._awaiting_warp_confirm = ""
            client._warp_fallback = None
        # Server-initiated warp/re-entry to a level whose board we
        # already hold this session: gs2emu's per-session level cache
        # means it will NOT re-stream PLO_BOARDPACKET, so re-point the
        # active render board at the cached tiles. warp_to_level()
        # does this for client-initiated warps, but a server push
        # (Bomber v6's preloader -> "joinlobby" -> bomblobby re-warp)
        # went only through this handler and left _tiles_level_name
        # stale forever: black board + a permanent "Loading level..."
        # overlay (live-traced 2026-07-23: cur=bomblobby.nw,
        # tiles=bomb_preloader.nw, bomblobby board sitting unused in
        # client.levels).
        if (not is_gmap_segment
                and level_name == client._current_level_name
                and client._tiles_level_name != level_name
                and level_name in client.levels):
            client.tiles = client.levels[level_name]
            client._tiles_level_name = level_name
        # Track for tile storage
        client._pending_level_name = level_name
    # Set player.level to GMAP name if available, else level name
    if level_name.endswith('.gmap') or not client.player.level:
        client.player.level = level_name
    # Entering a gmap: download the .gmap file so we can build the grid.
    # The server announces the gmap by name but doesn't push the file;
    # the client must request it (once) via PLI_WANTFILE.
    if level_name.endswith('.gmap') and level_name != client._requested_gmap:
        client._requested_gmap = level_name
        # Walking out of an interior cleared the grid (_exit_gmap), so this
        # fires again on every return to the overworld. The file itself is
        # already in _received_files from the first entry and cannot have
        # changed mid-session, so re-parse it here instead of paying another
        # PLI_WANTFILE round trip: measured on hastur, waiting for the server
        # left the camera in the interim standalone coordinate frame for
        # ~330 ms after the destination board had already arrived, and the
        # world frame then snapped in.
        cached_gmap = client._received_files.get(level_name)
        if cached_gmap:
            _load_cached_gmap(client, level_name, cached_gmap)
        else:
            client.request_file(level_name)
    # Leaving a gmap: a .nw level that isn't one of the gmap's segments
    # (e.g. warping into a cave/house) means we've left gmap mode. Clear
    # the grid so is_gmap/coordinates reflect the standalone level.
    elif (level_name.endswith('.nw') and client.gmap_width > 0 and
          level_name not in client.gmap_grid.values()):
        client._exit_gmap(level_name)
    # A cached-board destination already has its tiles active (set
    # synchronously in warp_to_level), so this announcement is the
    # release point - the server may not re-stream the board at all
    # (per-session level cache).
    client._maybe_release_local_transition()


@handles(PacketID.PLO_WARPFAILED)
def handle_warp_failed(client, data):
    # PLO_WARPFAILED (15) - the server rejected a warp (GServer-v2
    # PlayerClient.cpp:1180/1275 sends it with the failed level name when
    # a target level can't be loaded/entered). warp_to_level flipped
    # level/position optimistically, so restore the pre-warp snapshot or
    # we'd be stranded reporting a phantom level the server never put us
    # in (its authoritative state still has us in the old level).
    # NB: gs2emu does NOT send this for a bad PLI_LEVELWARP - that
    # rejection is detected in entities.handle_player_props instead.
    failed_level = data.decode('latin-1', errors='replace').strip()
    if (client._awaiting_warp_confirm
            and failed_level == client._awaiting_warp_confirm):
        client._restore_failed_warp("PLO_WARPFAILED")
    elif not failed_level:
        # An EMPTY level name never refers to one of our warps (we
        # refuse to send a nameless PLI_LEVELWARP, and GServer-v2
        # echoes the failed name back). Live Bomber v6 emits these as
        # junk whenever a server-side script setlevel2's an empty
        # string; the old wildcard match ("empty matches anything
        # pending") could roll back a SUCCESSFUL in-flight warp if
        # the junk raced our LEVELNAME confirm. Log-and-ignore.
        logger.info("PLO_WARPFAILED with empty level name ignored "
                    "(server-side script warped '' - not ours)")
    else:
        logger.warning("PLO_WARPFAILED for %r with no matching "
                       "pending warp", failed_level)


@handles(PacketID.PLO_BOARDPACKET)
def handle_board_packet(client, data):
    # Level board tiles (uncompressed, 8192 bytes; also reached for the
    # compressed/raw path - PLO_RAWDATA's payload is re-emitted with this
    # same packet_id once its byte count is satisfied, see protocol.py).
    tiles = parse_board_packet(data)
    # Store in levels dict using the pending level name
    level_for_tiles = client._pending_level_name or client._current_level_name
    if level_for_tiles:
        client.levels[level_for_tiles] = tiles
        # A fresh board stream means this level's static data (signs
        # included) is being (re-)sent: restart the ordered sign list so a
        # server that re-streams per entry (pygserver) doesn't append
        # duplicates and shift `say <n>` indices. gs2emu streams a level's
        # board only once per session, so its list is simply never reset.
        client.sign_lists.pop(level_for_tiles, None)
    # client.tiles is the ACTIVE render/collision board and must only
    # ever switch on a real warp/segment change - never on a GMAP
    # adjacent-segment preload (request_adjacent_levels(), answered
    # by pygserver's _handle_adjacent_level with just [LEVELNAME,
    # board] for a neighbour so the world renders stitched via
    # client.levels[] above; the player never actually moves there).
    # Previously this unconditionally clobbered client.tiles with
    # whichever segment's board arrived LAST, so during a preload
    # burst the active board flip-flopped between our real segment
    # and up to 8 neighbours (symptom: /map returning contradictory
    # boards, collision/warp-validation following stale tiles).
    # _current_level_name is always updated (optimistically, at
    # send time) before the confirming board for an actual
    # warp/segment-cross arrives - see warp_to_level()/move() and
    # the PLO_LEVELNAME/PLO_PLAYERWARP2 handlers - so gating on it
    # here is sufficient and doesn't need extra state.
    if level_for_tiles == client._current_level_name:
        client.tiles = tiles
        client._tiles_level_name = level_for_tiles
        client._maybe_release_local_transition()
    if client.on_level:
        client.on_level(tiles)


@handles(PacketID.PLO_PLAYERWARP)
def handle_player_warp(client, data):
    # Player warp/spawn position (packet 14) - non-GMAP levels
    warp = parse_playerwarp(data)
    if warp:
        level = warp.get('level', '')
        if (client._awaiting_warp_confirm and level
                and not client.warp_names_pending_destination(level)):
            client._restore_failed_warp(
                "server player warp named another level")
        # x, y are local coords (0-63 range for non-GMAP levels).
        # A warp we announced ourselves echoes back one round trip late; see
        # handle_player_warp2 below for why its coordinates are dropped.
        if not client.consume_warp_echo(level):
            client.player.x = warp.get('x', 0)
            client.player.y = warp.get('y', 0)
        if level:
            client.player.level = level


@handles(PacketID.PLO_PLAYERWARP2)
def handle_player_warp2(client, data):
    # Player warp with GMAP position (packet 49)
    warp = parse_playerwarp2(data)
    if warp:
        level = warp.get('level', '')
        if (client._awaiting_warp_confirm and level
                and not client.warp_names_pending_destination(level)):
            client._restore_failed_warp(
                "server player warp named another level")
        # x, y are local coords within the level/grid cell
        local_x = warp.get('x', 0)
        local_y = warp.get('y', 0)
        gmap_x = warp.get('gmap_x', 0)
        gmap_y = warp.get('gmap_y', 0)

        # Check if we're in GMAP mode:
        # 1. Have a gmap grid loaded, OR
        # 2. Level name ends with .gmap, OR
        has_gmap_grid = client.gmap_width > 0 and client.gmap_height > 0
        level_is_gmap = client.player.level and client.player.level.endswith('.gmap')

        # Only use world coords if we have a loaded gmap grid or level is explicitly a .gmap
        in_gmap = has_gmap_grid or level_is_gmap

        # A level change we announced ourselves (seam crossing, door link)
        # comes back one round trip later as this packet, carrying nothing but
        # the half-tile quantisation of the coordinates we sent. Adopting it
        # rewinds the player by however far they walked during the round trip
        # - 1.8 tiles (29 px) at a seam and 3.3 tiles (53 px) out of a door on
        # a live 180 ms link, every time. Take the level/grid bookkeeping,
        # keep our own position.
        echo = client.consume_warp_echo(level, (gmap_x, gmap_y))

        if not echo:
            if in_gmap:
                # Convert to world coords by adding the grid cell's origin
                client.player.x, client.player.y = local_to_world(
                    local_x, local_y, gmap_x, gmap_y)
            else:
                # Not in GMAP - use local coordinates only
                client.player.x = local_x
                client.player.y = local_y

        # Store grid position for GMAP detection
        client._gmap_spawn_x = gmap_x
        client._gmap_spawn_y = gmap_y

        # Update level name from gmap grid if available
        if client.gmap_grid and (gmap_x, gmap_y) in client.gmap_grid:
            client._current_level_name = client.gmap_grid[(gmap_x, gmap_y)]
        # Segment warp with the grid already loaded: the world frame
        # is established right here, so a held transition can end.
        client._maybe_release_local_transition()


@handles(PacketID.PLO_LEVELLINK)
def handle_level_link(client, data):
    # Level links
    link = parse_level_link(data)
    level_for_link = client._pending_level_name or client._current_level_name
    if link and level_for_link:
        if level_for_link not in client.links:
            client.links[level_for_link] = []
        # Re-entering a level the server has already streamed us
        # (e.g. crossing a GMAP segment boundary out and back)
        # re-sends every PLO_LEVELLINK for that level, and this
        # handler used to append unconditionally - links list grew
        # a duplicate per revisit. Identity here is the parsed
        # fields themselves (dest/rect), matching how callers
        # de-duplicate downstream (see playtest_daemon._current_links).
        if link not in client.links[level_for_link]:
            client.links[level_for_link].append(link)


@handles(PacketID.PLO_LEVELCHEST)
def handle_level_chest(client, data):
    # Level chest (packet 4)
    chest = parse_level_chest(data)
    if chest:
        # Match sign attribution exactly: during gmap preloading the
        # pending board owns streamed local coordinates, not necessarily
        # the segment containing the player.
        lvl = client._pending_level_name or client._current_level_name
        key = (chest['x'], chest['y'])
        client.chests.setdefault(lvl, {})[key] = chest['opened']
        # Remember the item an unopened chest holds (only sent on warp).
        if 'item' in chest:
            client.chest_items.setdefault(lvl, {})[key] = chest['item']
        if client.on_chest:
            client.on_chest(chest['x'], chest['y'], chest['opened'])


@handles(PacketID.PLO_LEVELSIGN)
def handle_level_sign(client, data):
    # Level sign (packet 5)
    sign = parse_level_sign(data)
    if sign:
        # Key signs by the level they belong to (the level whose board is
        # currently being received) so a sign never shows in another level
        # — local sign coords collide across segments otherwise.
        lvl = client._pending_level_name or client._current_level_name
        client.signs.setdefault(lvl, {})[(sign['x'], sign['y'])] = sign['text']
        # Arrival-order list for `say <n>` index addressing - the dict
        # above collapses coordinate collisions (see client_state.py).
        client.sign_lists.setdefault(lvl, []).append(
            (sign['x'], sign['y'], sign['text']))
        if client.on_sign:
            client.on_sign(sign['x'], sign['y'], sign['text'])


@handles(PacketID.PLO_MINIMAP)
def handle_minimap(client, data):
    # Minimap data (packet 172)
    mm = parse_minimap(data)
    if mm and client.on_minimap:
        client.on_minimap(mm['data'])


@handles(PacketID.PLO_BIGMAP)
def handle_bigmap(client, data):
    # Bigmap/minimap config (packet 171) - sent on gmap entry.
    client.bigmap_info = parse_bigmap(data)


@handles(PacketID.PLO_BOARDLAYER)
def handle_board_layer(client, data):
    # Board layer (packet 107)
    layer = parse_board_layer(data)
    if layer:
        client.board_layers[layer['layer']] = layer['tiles']
        if client.on_board_layer:
            client.on_board_layer(layer['layer'], layer['x'], layer['y'], layer['tiles'])


@handles(PacketID.PLO_BOARDMODIFY)
def handle_board_modify(client, data):
    # Single-level tile delta (packet 7) - non-gmap board edit.
    info = parse_board_modify(data)
    level_name = client._pending_level_name or client._current_level_name
    if level_name:
        client._apply_board_modify(level_name, info)
    if client.on_board_modify:
        client.on_board_modify(info)


@handles(PacketID.PLO_BOARDMODIFY2)
def handle_board_modify2(client, data):
    # Gmap tile delta (packet 186) - carries the target segment's map
    # position so it can be applied even to a level we're not standing on
    # (adjacent-level board edits within a gmap).
    info = parse_board_modify2(data)
    level_name = client.gmap_grid.get((info['map_x'], info['map_y']))
    if not level_name:
        level_name = client._pending_level_name or client._current_level_name
    if level_name:
        client._apply_board_modify(level_name, info)
    if client.on_board_modify:
        client.on_board_modify(info)


@handles(PacketID.PLO_BOARDHEIGHTS)
def handle_board_heights(client, data):
    # Gmap level-height overrides (packet 185) - no rendering, just cache.
    heights = parse_board_heights(data)
    client.board_heights[(heights['map_x'], heights['map_y'])] = heights


@handles(PacketID.PLO_LEVELBOARD)
def handle_level_board(client, data):
    # Board-sent marker (packet 0) - board data normally arrives via
    # PLO_BOARDPACKET/PLO_RAWDATA, so this is usually just an
    # acknowledgement (server sends it with an empty payload - see
    # PlayerClient.cpp/PlayerClientOriginal.cpp). Defensively handle the
    # "batched board changes" payload form too (Level.cpp
    # sendBoardChangesToPlayer style==2: concatenated
    # getPropsForSingleLevel() records, same body as PLO_BOARDMODIFY,
    # back to back) - currently dead code server-side (TODO, never
    # triggered) but cheap to support if it ever is.
    if data:
        from ..packets import PacketReader as _PacketReader
        level_name = client._pending_level_name or client._current_level_name
        reader = _PacketReader(data)
        while reader.pos < len(data):
            start = reader.pos
            layer = 0
            first = reader.read_gchar()
            if first >= 64:
                layer = first - 64
                x = reader.read_gchar()
            else:
                x = first
            y = reader.read_gchar()
            w = reader.read_gchar()
            h = reader.read_gchar()
            if w <= 0 or h <= 0 or w > 64 or h > 64 or reader.pos <= start:
                break  # not a valid record - bail rather than misparse
            tiles = [reader.read_gshort() for _ in range(w * h)]
            info = {'layer': layer, 'x': x, 'y': y, 'width': w,
                    'height': h, 'tiles': tiles}
            if level_name:
                client._apply_board_modify(level_name, info)
            if client.on_board_modify:
                client.on_board_modify(info)


@handles(PacketID.PLO_ISLEADER)
def handle_is_leader(client, data):
    # We are this level's leader (packet 10) - drive baddies/NPCs.
    client.is_leader = True


@handles(PacketID.PLO_LEVELMODTIME)
def handle_level_mod_time(client, data):
    # Active level's mod time (packet 39).
    level = client.active_level or client._pending_level_name
    client.level_modtimes[level] = parse_level_modtime(data)


@handles(PacketID.PLO_SETACTIVELEVEL)
def handle_set_active_level(client, data):
    # Active level for subsequent chest/baddy/npc/board packets (packet 156).
    client.active_level = parse_set_active_level(data)
    # Route level-scoped data (board/chest/sign) to this level too.
    client._pending_level_name = client.active_level
