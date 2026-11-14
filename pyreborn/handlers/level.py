"""The client handles level and world packets.

These packets contain level names, transitions, board data, tile changes,
links, signs, chests, and the related gmap and minimap metadata.
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
from ..client_callbacks import emit
from ..gmap_coords import get_ci, has_level, in_grid, same_level
from ..npc_handler import is_map_name
from .registry import handles

logger = logging.getLogger(__name__)


def _load_cached_gmap(client, filename: str, blob: bytes) -> None:
    """Restore the gmap world frame from an already-downloaded .gmap.

    Shares handlers/files.adopt_gmap with every other path that builds a grid,
    and adds the one thing only this caller can do about a bad parse: ask for
    the file again.
    """
    from .files import adopt_gmap

    if not adopt_gmap(client, filename, blob):
        logger.warning("cached %s failed to parse; re-requesting", filename)
        client.request_file(filename)


def _is_current_map(client, map_name):
    """Whether `.gmap` name `map_name` is the map the player is on. A map is
    taken for the current one until another is known to be."""
    known = client.gmap_name or client._requested_gmap
    return not known or same_level(known, map_name)


@handles(PacketID.PLO_LEVELNAME)
def handle_level_name(client, data):
    # Level name - track which level we're receiving data for
    level_name = parse_level_name(data)
    if level_name.endswith('.nw'):
        client.level_state.streaming_level_name = level_name
    # .nw files are actual levels, .gmap is the world map name
    if level_name.endswith('.nw'):
        # The request carries the spelling the .gmap used; the server may
        # answer in another case (it lower-cases map names).
        requested = next((r for r in client._adjacent_level_requests
                          if same_level(r, level_name)), None)
        is_adjacent_preload = requested is not None
        if is_adjacent_preload:
            client._adjacent_level_requests.discard(requested)
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
                            in_grid(client.gmap_grid, level_name))
        if is_adjacent_preload:
            # The explicit request marker is authoritative even outside a
            # loaded gmap: an adjacent static-data answer never moves us.
            pass
        elif is_gmap_segment:
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
            # through the level scope below, but keep the requested
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
            client._restore_cached_layers(level_name)
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
            client._restore_cached_layers(level_name)
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
                and has_level(client.levels, level_name)):
            client.tiles = get_ci(client.levels, level_name)
            client._tiles_level_name = level_name
        # The level scope is the PLO_LEVELNAME target (TClient.cpp:3224-3241).
        # An adjacent preload sets it to the neighbour for the length of that
        # static block (board, links, chests, signs land there); the closing
        # PLO_LEVELNAME of the block sets it back. Any other level is the
        # player's entry, and also the NPC owner until PLO_SETACTIVELEVEL
        # names it. That approximates the reference, which sets the NPC
        # target at level load only when the scope does not name the loaded
        # level (TPlayer.cpp:941-946; `_own_warp_moves_targets` does that
        # for a warp without PLO_LEVELNAME). It differs in one window: an
        # NPC packet between this PLO_LEVELNAME and PLO_SETACTIVELEVEL is
        # filed here, where the reference files it under the previous NPC
        # target.
        client._level_scope = level_name
        if not is_adjacent_preload:
            client._level_scope_segment = level_name
            client._npc_level = level_name
    elif is_map_name(level_name) and _is_current_map(client, level_name):
        # The current map: the scope is the player's own segment, resolved
        # when read. Another map leaves it unchanged (TClient.cpp:3224-3241).
        client._level_scope = level_name
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
          not in_grid(client.gmap_grid, level_name)):
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
    # Store in levels dict under the level scope
    level_for_tiles = client._level_scope_name()
    if level_for_tiles:
        client.levels[level_for_tiles] = tiles
        # A real board means the level changed since the mod time we sent (or
        # we sent none): the server follows it with that level's links and
        # signs, and the reference replaces the cached level wholesale. Drop
        # the old ones, the stored layers and the ordered sign list (a
        # re-streaming server would otherwise append duplicates and shift
        # `say <n>` indices). An empty PLO_LEVELBOARD ("keep your copy") never
        # reaches here, so a visited level keeps all of it.
        client.links.pop(level_for_tiles, None)
        client.signs.pop(level_for_tiles, None)
        client.sign_lists.pop(level_for_tiles, None)
        client.level_state.level_layers.pop(level_for_tiles, None)
        if client._board_layers_level_name == level_for_tiles:
            client.board_layers.clear()
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
    emit(client, 'on_level', tiles)


def _own_warp_moves_targets(client, level):
    """What the reference client does to its two level targets when the
    server warps the player (PLO_PLAYERWARP / PLO_PLAYERWARP2).

    A warp naming a loaded ``.gmap`` sets the level scope to that map and
    clears the bound level; the entry stream then re-binds it
    (TClient.cpp:3003-3004 and :3401-3402 for the plain warp, :3054-3060 for
    the warp with a map position). A map that is not loaded changes nothing.
    A plain level leaves the scope alone: the level load then sets the NPC
    target to the new level only when the scope does not already name it
    (TPlayer.cpp:941-946). A modern-flow server names every level, so the
    scope follows PLO_LEVELNAME. A session on the original-client flow is the
    exception, handled below.
    """
    if is_map_name(level):
        if client.gmap_grid and _is_current_map(client, level):
            client._level_scope = level
    elif client._original_flow:
        # The server's original-client flow (login type PLTYPE_CLIENT,
        # GServer-v2 PlayerLogin.cpp:68-69) sends PLO_LEVELNAME only for the
        # first level (PlayerClientOriginal.cpp:158-160). No reference client
        # is served by that flow, so there is no reference behaviour to
        # port: the warp itself names the player's level, and everything
        # level-scoped lands there instead of stranding on the first level.
        if not same_level(client._current_level_name, level):
            client._current_level_name = level
            client._plain_level_change_epoch += 1
            client._reset_level_state()
            client._restore_cached_npcs(level)
            client._restore_cached_layers(level)
        client._level_scope = level
        client._level_scope_segment = level
        client._npc_level = level
    elif not same_level(client._level_scope, level):
        client._npc_level = level


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
            _own_warp_moves_targets(client, level)


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
        if level:
            _own_warp_moves_targets(client, level)
        # Segment warp with the grid already loaded: the world frame
        # is established right here, so a held transition can end.
        client._maybe_release_local_transition()


@handles(PacketID.PLO_LEVELLINK)
def handle_level_link(client, data):
    # Level links
    link = parse_level_link(data)
    level_for_link = client._level_scope_name()
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
        # level scope is the neighbour that owns the streamed local
        # coordinates, not necessarily the segment containing the player.
        lvl = client._level_scope_name()
        key = (chest['x'], chest['y'])
        client.chests.setdefault(lvl, {})[key] = chest['opened']
        # Remember the item an unopened chest holds (only sent on warp), and
        # the sign index beside it: the level editor's export has to write
        # that index back out, and the 3-byte form never carries it.
        if 'item' in chest:
            client.chest_items.setdefault(lvl, {})[key] = chest['item']
        if 'sign' in chest:
            client.chest_signs.setdefault(lvl, {})[key] = chest['sign']
        emit(client, 'on_chest', chest['x'], chest['y'], chest['opened'])


@handles(PacketID.PLO_LEVELSIGN)
def handle_level_sign(client, data):
    # Level sign (packet 5)
    sign = parse_level_sign(data)
    if sign:
        # Key signs by the level they belong to (the level whose board is
        # currently being received) so a sign never shows in another level
        # — local sign coords collide across segments otherwise.
        lvl = client._level_scope_name()
        client.signs.setdefault(lvl, {})[(sign['x'], sign['y'])] = sign['text']
        # Arrival-order list for `say <n>` index addressing - the dict
        # above collapses coordinate collisions (see client_state.py).
        client.sign_lists.setdefault(lvl, []).append(
            (sign['x'], sign['y'], sign['text']))
        emit(client, 'on_sign', sign['x'], sign['y'], sign['text'])


@handles(PacketID.PLO_MINIMAP)
def handle_minimap(client, data):
    mm = parse_minimap(data)
    if 'image' in mm:
        # Login sends BIGMAP then MINIMAP (GServer-v2 origin/beta4
        # PlayerClient.cpp:489-516); each keeps its own configuration so the
        # second packet does not replace the first.
        client.minimap_info = mm
    elif mm:
        emit(client, 'on_minimap', mm['data'])


@handles(PacketID.PLO_BIGMAP)
def handle_bigmap(client, data):
    # Bigmap/minimap config (packet 171) - sent on gmap entry.
    client.bigmap_info = parse_bigmap(data)


@handles(PacketID.PLO_BOARDLAYER)
def handle_board_layer(client, data):
    # Board layer (packet 107)
    layer = parse_board_layer(data)
    if layer:
        level_name = client._level_scope_name()
        # board_layers is a single-level store. Adjacent layers remain
        # available from their source board stream only for routing purposes;
        # merging them here would corrupt the active level's composite.
        if not client._scope_is_own_level():
            return
        if level_name != client._board_layers_level_name:
            client.board_layers.clear()
            client._board_layers_level_name = level_name
        client.board_layers[layer['layer']] = layer['tiles']
        emit(client, 'on_board_layer', layer['layer'], layer['x'], layer['y'], layer['tiles'])


@handles(PacketID.PLO_BOARDMODIFY)
def handle_board_modify(client, data):
    # Single-level tile delta (packet 7). It carries no level, and the server
    # only relays it to players in (or beside) the sender's own level, so the
    # target is the level WE are standing in - segment-aware, exactly like
    # Client.modify_board's local patch. The level scope (the reference's
    # target for this, TClient.cpp:3224-3241) is the neighbour only while an
    # adjacent preload streams, and a `.gmap` scope resolves to the segment
    # under the player, so another builder's edit lands in the player's level.
    info = parse_board_modify(data)
    level_name = client._level_scope_name()
    if level_name:
        client._apply_board_modify(level_name, info)
    emit(client, 'on_board_modify', info)


@handles(PacketID.PLO_BOARDMODIFY2)
def handle_board_modify2(client, data):
    # Gmap tile delta (packet 186) - carries the target segment's map
    # position so it can be applied even to a level we're not standing on
    # (adjacent-level board edits within a gmap).
    info = parse_board_modify2(data)
    level_name = client.gmap_grid.get((info['map_x'], info['map_y']))
    if not level_name:
        level_name = client._level_scope_name()
    if level_name:
        client._apply_board_modify(level_name, info)
    emit(client, 'on_board_modify', info)


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
        level_name = client._level_scope_name()
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
            emit(client, 'on_board_modify', info)


@handles(PacketID.PLO_ISLEADER)
def handle_is_leader(client, data):
    # We are this level's leader (packet 10) - drive baddies/NPCs.
    client.is_leader = True


@handles(PacketID.PLO_LEVELMODTIME)
def handle_level_mod_time(client, data):
    # Mod time of the level being streamed (packet 39). The reference sends it
    # at the end of the static data (PlayerClient.cpp:1513), before the
    # set-active-level packet, so the active level is still the previous one.
    level = (client.level_state.streaming_level_name
             or client._level_scope_name())
    client.level_modtimes[level] = parse_level_modtime(data)


@handles(PacketID.PLO_SETACTIVELEVEL)
def handle_set_active_level(client, data):
    # Owner of the NPC packets that follow (packet 156). The name may be a
    # .gmap. It sets only the NPC target: level-scoped data keeps the
    # PLO_LEVELNAME scope (TClient.cpp:3777-3784).
    client._npc_level = parse_set_active_level(data)
