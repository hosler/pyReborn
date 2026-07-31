from __future__ import annotations

import logging
import math

from reborn_protocol.coords import level_index, segment_at, world_to_local
from reborn_protocol.gs1.values import to_num



logger = logging.getLogger(__name__)


class GS1NoBoard(Exception):
    """A script read `tiles[x,y]` before the client received the current board.

    GS1 has no "unknown tile" value. Thus, a script cannot distinguish an
    invented number from a real tile ID. The old answer, 0.0, means "empty
    floor." The classic Bomber room0.nw furniture catalog then deletes each
    wall-mounted object whose tile is not wall ID 0x278. It writes the shortened
    object list directly to `server.room<N>` (ResetObj/Delete,
    room0.nw:1006/1052). If the client stops the script, the furniture stays
    unchanged. The event runs again after the board arrives.
    """


# ---------------------------------------------------------------------------
# Script-visible board access -- tiles[] reads/writes and updateboard -- shared
# by BOTH engines (GS1's `tiles[x,y]` builtin below, GS2's tiles_view in
# gs2_client.py). Coordinates are in the SCRIPT frame: world tiles while
# standing on a gmap segment (LTTP's -Player/Movement indexes 0..width*64),
# plain local 0..63 in a standalone level (houses, classic servers) -- the
# same frame split every other client-side probe (tiletype, onwall, playerx)
# already uses. Frame math comes from reborn_protocol.coords per house rules.
# ---------------------------------------------------------------------------

def _board_locate(client, x, y):
    """Resolve script-frame tile coordinates.

    Return (level_name, lx, ly, grid). If the coordinates are outside the world
    or in a gmap grid hole, level_name is None. For a gmap, grid is the (gx, gy)
    segment. For a standalone level, grid is None.
    """
    if client is None:
        return None, 0, 0, None
    tx, ty = int(math.floor(x)), int(math.floor(y))
    if getattr(client, "in_gmap_segment", False) and getattr(client, "gmap_grid", None):
        grid = segment_at(tx, ty)
        level = client.gmap_grid.get(grid)
        if not level:
            return None, tx, ty, grid
        lx, ly = world_to_local(tx, ty)
        return level, int(lx), int(ly), grid
    if 0 <= tx < 64 and 0 <= ty < 64:
        return getattr(client, "_current_level_name", "") or None, tx, ty, None
    return None, tx, ty, None


def _board_list(client, level_name):
    """Return the 4096-entry tile list for `level_name`, or None.

    The function uses the renderer's _segment_tiles resolution order. It checks
    the client.levels cache before the active client.tiles.
    Client._apply_board_modify changes both lists.
    """
    levels = getattr(client, "levels", None) or {}
    board = levels.get(level_name)
    if board is None and level_name == getattr(client, "_tiles_level_name", ""):
        board = getattr(client, "tiles", None)
    return board if board is not None and len(board) >= 4096 else None


def board_world_dims(client):
    """Return the script-frame board dimensions in tiles.

    The result is (width, height). It covers the full gmap while the player is
    on a segment. Otherwise, it covers one level.
    """
    if client is not None and getattr(client, "in_gmap_segment", False):
        w = int(getattr(client, "gmap_width", 0) or 0)
        h = int(getattr(client, "gmap_height", 0) or 0)
        if w > 0 and h > 0:
            return w * 64, h * 64
    return 64, 64


def board_tile_read(client, x, y):
    """Read tiles[x,y].

    Return None if the coordinate is outside the world. Also return None if the
    server did not stream the segment board. Callers select the miss value for
    their engine.
    """
    level, lx, ly, _grid = _board_locate(client, x, y)
    if level is None:
        return None
    board = _board_list(client, level)
    if board is None:
        return None
    return float(board[level_index(lx, ly)])


def board_tile_write(client, x, y, tile_id) -> bool:
    """Write id to tiles[x,y].

    The function uses Client._apply_board_modify. A PLO_BOARDMODIFY server
    change uses the same path. Thus, the function changes the REAL board in
    client.levels and active client.tiles. The change also affects collision.
    The function then fires the on_board_modify callback. The pygame client
    connects this callback to the renderer's per-segment surface patcher. The
    function discards writes outside the world or without a board. This matches
    a server change for a level that the client does not have.
    """
    level, lx, ly, grid = _board_locate(client, x, y)
    if level is None or _board_list(client, level) is None:
        return False
    info = {"layer": 0, "x": lx, "y": ly, "width": 1, "height": 1,
            "tiles": [max(0, int(to_num(tile_id))) & 0xFFF]}
    if grid is not None:
        info["map_x"], info["map_y"] = grid
    client._apply_board_modify(level, info)
    cb = getattr(client, "on_board_modify", None)
    if cb:
        cb(info)
    return True


def board_update_region(client, x, y, w, h) -> None:
    """`updateboard x,y,width,height` -- re-blit the rect from current board
    data. Oracle: GServer-v2 GS1Commands.cpp:3560-3575 (fn_updateboard /
    fn_updateboard2): exactly this argument order, each value clamped at 0,
    the rect handed to Level::updateBoard for a region redraw. Updateboard2
    also saves the level server-side, which has no client-side
    meaning, so both spellings redraw here. Scripts edit tiles[] first and
    then call this to publish the change (LTTP's CheckTiles bush slash).
    board_tile_write already patches the renderer per write, so this is the
    idempotent region form -- and the only path that repaints edits made
    behind the callback's back."""
    if client is None:
        return
    cb = getattr(client, "on_board_modify", None)
    if cb is None:
        return
    x0 = max(0, int(math.floor(x)))
    y0 = max(0, int(math.floor(y)))
    ww, wh = board_world_dims(client)
    x1 = min(x0 + max(0, int(math.floor(w))), ww)
    y1 = min(y0 + max(0, int(math.floor(h))), wh)
    if x1 <= x0 or y1 <= y0:
        return
    on_gmap = bool(getattr(client, "in_gmap_segment", False)
                   and getattr(client, "gmap_grid", None))
    targets = []
    if on_gmap:
        for gy in range(y0 // 64, (y1 - 1) // 64 + 1):
            for gx in range(x0 // 64, (x1 - 1) // 64 + 1):
                level = client.gmap_grid.get((gx, gy))
                if not level:
                    continue
                targets.append((level, (gx, gy),
                                max(x0, gx * 64) - gx * 64,
                                max(y0, gy * 64) - gy * 64,
                                min(x1, (gx + 1) * 64) - gx * 64,
                                min(y1, (gy + 1) * 64) - gy * 64))
    else:
        level = getattr(client, "_current_level_name", "") or None
        if level:
            targets.append((level, None, x0, y0, x1, y1))
    for level, grid, lx0, ly0, lx1, ly1 in targets:
        board = _board_list(client, level)
        if board is None:
            continue
        tiles = [board[level_index(tx, ty)]
                 for ty in range(ly0, ly1) for tx in range(lx0, lx1)]
        info = {"layer": 0, "x": lx0, "y": ly0,
                "width": lx1 - lx0, "height": ly1 - ly0, "tiles": tiles}
        if grid is not None:
            info["map_x"], info["map_y"] = grid
        cb(info)
